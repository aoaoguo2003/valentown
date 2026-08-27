# Valentown — Agent Loop 改造

七个 LLM 居民的小镇模拟。**正在进行的改造：把反应式 agent 变成完整的 ReAct 循环。**

改造前每个 tick 只发生一次 LLM 调用：模型被强制填一张表（`choose_next_action`），
程序照着执行，环境永远说 yes。现在是：模型自己选工具 → 环境可以拒绝 →
被拒后带着理由重新规划。

---

## 目标形态

```
State_t → LLM → Action → Tool → Environment → Observation → State_t+1 → LLM → ...
```

一轮的形状是 **N 个准备动作 + 1 个时间动作**：

```
recall → check_inbox → send_mail → stay("等回音")
└────── 不占游戏时间 ──────┘   └── 占时间，收敛 ──┘
```

---

## 架构分层

依赖方向是**严格单向**的，从下往上：

```
world/          小镇里有什么、规则是什么。数据 + 原子操作
   ↑            只依赖 config 和它自己
tools/          agent 能对世界做什么。每个工具 = schema + handler
   ↑
runtime/        决策循环。不认识任何具体工具
   ↑
api/ + main.py  HTTP 契约与启动入口
```

`agents/`（角色定义 + 上下文组装）、`memory/`（记忆与检索）、
`observability/`（追踪与指标）横跨在旁边，被上面几层使用。

| 包 | 职责 |
|---|---|
| **`world/`** | 世界服务。`clock` `locations` `economy` `weather` `goals` `mailbox` `snapshot` |
| **`tools/`** | 工具注册表。14 件工具，每件 = schema + handler + 三个标记 |
| **`runtime/`** | `agent_runtime.py` 决策循环 · `scheduler.py` 隔离小镇 + 全局时钟 · `context_builder.py` 这一轮让居民看见什么 |
| **`agents/`** | `agent.py` 角色与上下文组装，`state.py` 需求值与触发器 |
| **`memory/`** | 记忆库、三因子检索、反思、persona |
| **`observability/`** | `trace.py` 写日志（热路径），`metrics.py` 读日志算指标 |
| **`evals/`** | 做得好不好。`scenarios` 出题 · `ablations` 对照 · `runner` + `report` 记分卡 |
| **`llm/`** | `client.py`，和大模型唯一的接触面 |
| **`api/`** | `routes.py` Flask 路由。两段锁：取快照 / 提交决策 |
| `main.py` | 薄启动器，`from api.routes import app` 然后 run |
| `config.py` | 全局配置 |

### `world/` —— 整个后端的地基

```
clock.py      时间文本 <-> 分钟数。一个项目模块都不 import
locations.py  地理与居民名册。ALLOWED_DESTINATIONS 就是 move_to 的取值范围
economy.py    钱 + 货 + 店铺。**故意不拆成 inventory + economy**（见规则 3）
weather.py    天气。这个项目唯一的真外部依赖
mailbox.py    信箱
goals.py      任务与约定。共享的承诺账本，约定给双方各建一条
snapshot.py   把上面这些装配成一份给模型看的快照。**唯一的装配点**（规则 4）
__init__.py   ⚠️ 必须保持空的
```

⚠️ **`world/__init__.py` 里一个 import 都不能加。**`tools/__init__.py` 顶层要
`from world.economy import SHOP_OWNERS`，这会先跑一遍那个 `__init__`；它若
import 了 `tools`（哪怕只为 re-export 一个常量），就绕回去了——**循环导入，
整个后端起不来**。

对比 `runtime/__init__.py` 和 `llm/__init__.py`：那两个**可以** re-export，
因为没有任何下层模块会反过来 import 它们。规则一句话——
**`__init__` 里放不放东西，取决于这个包会不会被它的下游 import。**

### `tools/` —— 门

```
base.py            ToolSpec · reject/accept · THOUGHT_FIELD
movement.py        move_to · stay · sleep            占用游戏时间，会收敛本轮
communication.py   send_mail · check_inbox           改变世界但不占时间
shopping.py        check_stock · buy · restock       同上
wallet.py          transfer · give_item              同上
tasks.py           accept_task                       记下跨轮才做得完的事
meetings.py        accept_meeting                    和人约时间地点
weather.py         check_weather                     纯查询
remembering.py     recall                            纯查询
__init__.py        TOOL_REGISTRY + get_tool/function_schemas + re-export
```

**工具是门，世界服务是房间。**每加一个系统都是这个模式：
`world/mailbox.py + tools/communication.py`、`world/economy.py + tools/shopping.py`。
**这条路已经走过五遍**（stay、通信、库存、钱包、天气），决策循环
从写完到现在一行没改过——这是注册表设计最好的证据。

### 工具过滤：摘的是字数，不是能力

量出来的事实：一次决策 `prompt_tokens` 中位 **4279**，而真正的决策上下文只有
约 **649**——**输入的 85% 是工具 schema**，而且每次调用一模一样。

所以 `ToolSpec.available_now` 这个谓词回答「此刻调它会不会**必被拒**」。
命中的工具**完整 schema 不进请求**（一件 150–350 tokens），改成上下文里一行
「buy（要先进店）」（约 11 tokens）。实测 Emma 在家 13 件 → 10 件，净省
约 470 tokens ≈ **整个输入的 11%**。

⚠️ **能力的可见性是规划的前提**这条没变。看不见的能力模型不会为它做计划，
只会在「当下能做什么」里打转——errand 那道题的唯一出路是写信借钱，而 Emma
当时站在药房里。所以那一行必须点明「它们还在，只是得先满足条件」。

⚠️ 谓词和 handler 里的检查是**同一件事写了两遍**，走散的后果不对称：
谓词过严 → 模型看不见一件其实能用的工具（**丢能力**）；过松 → 白给一次拒绝
（无害）。所以拿不准就返回 None，并且 `test_tool_filter.py` 有一组参数化测试
（5 件工具 × 5 个地点 × 3 个居民）拿真 handler 反着对账。

`move_to` / `stay` 故意没有谓词——它们是**本轮唯一的收敛点**，摘光了这一轮
无论如何都做不出动作，而且不会报错。

### `runtime/context_builder.py` —— 这一轮让居民看见什么

原本是 `agents/agent.py` 里一个 110 行、12 个参数的方法。搬出来是因为
**它干的事跟「谁」无关**：七个居民用同一套组装规则，把规则藏在角色定义里，
规则就只能以注释的形式散在函数体中间。

三条规则，每条写在对应的段函数的 docstring 里：

```
① 分界线是「这是关于谁的」，不是信息量
     自己的（钱、背包、需求、任务）免费进
     别人的、店里的、信里的，要花一个动作去取
② 当下免费，未来要查
     当前天气免费（抬头看得见），预报要调 check_weather
③ 本轮的经历分两段摆
     「已经知道的」只给结果；「被拒绝的」保留工具和参数
```

抽的时候先把三份输出录成标尺（`tests/fixtures/decision_context.json`），
重构后**一字不差**才算搬完——「我只是搬了个家」不能只是自称。
那份标尺现在兼职另一件事：**prompt 变了测试就红**，逼你确认那是有意的。
确认之后用 `python -m tests.regenerate_context_fixture` 重录。

### `observability/` —— 两个方向

```
trace.py     写。每次 LLM 调用、每步工具调用当场追加一条 JSONL。在热路径上
metrics.py   读。行为指标（summarise）+ 成本指标（summarise_cost）。零项目依赖

**行为和成本来自两份日志，故意不并成一张表**：动作日志一步一条，
LLM 日志一次请求一条——**一步不等于一次请求**（重试会多几次，兜底则
一次都不发）。硬凑成一行会让人以为它们是同一批样本。
__init__.py  只 re-export 写那一侧——读日志的工具不该让写日志的热路径多付钱
```

⚠️ **`observability` 回答「发生了什么」，`evals/` 回答「做得好不好」。**
所以 `metrics.py` 里没有任何场景知识，随便一份线上日志都能算；
「任务达成没达成」得对着题目才判得了，那个归 `evals/`。

`metrics.py` 故意**不 import 工具注册表**（为了能独立对着任何一份日志跑），
代价是分类可能和代码走散，所以 `test_metrics.py` 里有两个对账测试：
一个拿真注册表核工具分类，一个扫源码里所有 `reject(...)` 核拒绝理由。
谁先走散谁红。

### `evals/` —— 做得好不好

```
scenarios.py   场景注册表：seed(埋一个起因) + judge(只看世界状态判成败)
ablations.py   消融注册表：关掉一个能力再跑同一道题
runner.py      跑 场景 x 消融 x 重复，每格一座独立小镇，判据一过就早停
report.py      记分卡排版
```

**判据只看世界状态**：`holdings("Adam Harris")["cold_medicine"] > 0`。
不看模型说没说"我送到了"。

⚠️ **判据里不掺行为指标。**「买到了 **且** 没反复撞墙」——后半句是行为不是
世界状态，混进 `passed` 就把这条原则搞糊了。记分卡里两列并排：judge 说过没过，
metrics 说撞了几次。

⚠️ **一道题埋完之后判据必须是「没做到」。**否则早停会在第一批决策后立刻触发，
那一格什么都没测到却显示满分——不报错，只是记分卡说谎。
`test_evals.py` 逐条钉死了这一点。

**消融是这套东西最值钱的部分**——基线自己跑出 80% 说明不了什么；基线 80%、
关掉某个能力掉到 20%，那个能力才算被证明有用。

⚠️ **`single-step` 不是「改造前」，`pre-rebuild` 才是。**
改造前是「只有 `move_to` + 强制调用 + 单步」，模型每轮必定产出一个动作。
而 `single-step` 给了它十四件工具的选择权却不给第二步——它一旦挑了
`check_inbox`，这一轮就作废了（首跑：空转轮次 18–21%，基线 5–7%，
改变世界的动作 0 个）。**拿它冒充改造前是稻草人**：它比改造前更差，
而差的那部分不是改造带来的。

读表时另一个坑：**单步的两条消融，「无效调用率」必然是 0**——不是它们
更准，是 `already_known` / `rate_limited` 天生需要前一步存在。

挑消融项的标准是**信息量不是覆盖率**：`no-outgoing-mail` 只摘 `send_mail`
而保留 `check_inbox`——三道题的起因都在信箱里，连收信一起摘必然零分，
跑它只是烧钱确认"看不见任务就做不成任务"。

### `runtime/scheduler.py` —— 两个调用方共用的引擎

`dry_run` 和 `evals/runner` 跑的是同一份代码，只有"跑完拿它干什么"不同。
不共用的话，规则 4 那个教训会原样重演一遍。

`Town` 是个上下文管理器，进块时把**九处**全局指向沙盒，出块时原样还原。
还原是给评估用的：一次评估在同一进程里连跑几十座小镇，漏还原一处，
第二座就继承了第一座的世界。

⚠️ `persona_store` 换的是**对象身上的目录**，不是模块上的名字——
`agents/agent.py` 和 `memory/reflection.py` 都在模块顶层绑死了那个对象。
（这个缺口是抽 scheduler 时才发现的：`dry_run` 一直宣称"一个字节都不碰真实
存档"，而每晚的反思其实都写进了真实的 `memory/agent_personas/`。）

⚠️ **评估时天气必须钉死。**天气是真实伦敦数据，今天下雨明天不下，
同一道题两次跑就不可比了——那对比的是天气，不是模型。`Town` 默认关掉
真实调用走降级路径，它用 `life_day` 做种子。

### 分包时踩到的两个坑

**① 字符串形式的 monkeypatch 目标躲过一切 import 重写。**
`monkeypatch.setattr("economy.economy", store)` 里的模块路径是个字符串，
正则扫 import 语句扫不到它，25 处全在测试里。改模块名时记得连它一起找。

**② 一个被迫存在的重复，随着环消失而消失。**
`SHOP_OWNERS` 曾被复制成两份，注释写着理由：`world.py` 要 import `tools`，
`tools` 要 import `economy`，反向导入就成环。`locations.py` 搬进 `world/`
之后 `snapshot.py` 不再依赖 `tools`，环没了，复制也就删了。
**分包真正的回报不是文件挪了位置，是这种东西。**

## 五条不能破的规则

### 1. `terminal` 的判据是「占不占用游戏时间」

**不是**「改不改变世界」。发一封信改变了世界却不占时间——若判它 terminal，
本轮就在时钟没推进的情况下结束，下一轮立刻重来，白白空转一次 HTTP 请求
和一次 LLM 调用。**不花时间的工具一律 `terminal=False`。**

推论：`terminal=True` 的工具大概率永远只有 `move_to` / `stay`（也许加 `sleep`）。
钱包、天气接进来仍然都是非终止的，**循环的收敛点不随工具增多而变复杂**。

### 2. 信息不对称：居民看不见远处的人

世界知道所有人在哪，**但没有任何一个居民知道**。只看得见同一区域的人
（`world.visible_agents()`）。想知道远处某人在哪 → 只能写信打听。

⚠️ **拒绝理由绝不能泄露对方去向**：

```
✅ "Emma Harris is not at Café_bar."
❌ "Emma Harris is at Park."        ← 等于白送全局位置表，通信就没意义了
```

`test_rejection_never_reveals_where_the_target_is` 钉死了这条。

同源规则：`check_stock` 要求人在店里（除非你是店主，店主有账本）；
`buy` **不适用**这条例外——账本能远程看，东西不能远程拿。

### 3. 超卖只能靠原子扣减挡住

`check_stock` 的结果**从返回那一刻就是缓存**。防线在 `inventory.buy` 的
那一把锁里（检查+扣减+入袋同时完成）。任何"先查再改"的写法必然超卖。

同一个模式的另一个实例：`runtime._commit` 提交决策前**重跑一次 handler**，
因为模型思考的几十秒里座位可能被抢了。

买东西要**同时**改五样（查余额→扣钱→减货架→入袋→店主收钱），必须一起成功
或一起失败。这也是 `inventory.py` 合并成 `economy.py` 的全部理由——
**原子性边界决定模块边界**：用两把锁做一件原子的事，除了部分失败，还会
循环等待死锁。

### 4. 世界快照只能由一处拼装

`world.snapshot()` 是唯一的组装点，**不要在别处直接 `World(...)`**（测试里
手工构造无妨，那是刻意只填关心的字段）。

曾经 `main.py` 和 `dry_run.py` 各拼了一份。给 World 加 `holdings` 时只有前者
跟上了，于是离线试跑里每个人的口袋都读作空的：买到药的人被告知自己两手
空空，转身又去药房买了一遍；所有「把东西交给某人」的任务都拿空背包做判定，
**永远无法达成**。一次十七分钟的跑，出来的数字全是废的，而日志里只显示
「模型没做到」。

问题不在漏掉的那一行，在于同一个对象由两处拼装——**给其中一处加字段，
另一处就开始说谎**。

### 5. 慢 I/O 永远不进临界区

LLM 调用（最长 60 秒）和天气请求都在锁外完成，锁只在取快照与提交时持有。

**这条有数字撑着**，见 `tests/test_concurrency.py`：

```
七人单步并发   0.25s     一次调用 0.20s，几乎完全重叠
七人两步并发   0.42s     两次调用 0.40s，同样重叠
锁内做慢调用   1.43s     7 x 0.20，彻底串行  <- 改造前的形态
```

第三个测试是**反证**：留着它是为了证明前两个测的是真东西。将来谁把慢调用
放回锁里，测试立刻变红。

⚠️ **不要改成 asyncio。**七个居民已经在完美重叠等待——线程在 I/O 期间会
释放 GIL，GIL 挡的是 CPU 并行不是 I/O 并发。协程的收益要到成百上千并发才
显现，在这里换不来可测量的性能，却要重写 Web 层、两个 HTTP 客户端、六把锁
和几乎全部测试。**能说清"为什么不用 asyncio"比用了更值钱。**

---

## 决策循环（`runtime/agent_runtime.py`）

三个出口，缺一不可：

1. **行动类工具成功** → 拿到可播放的动作，正常收敛
2. **步数用完**（`MAX_STEPS = 5`）→ 确定性兜底
3. **LLM 不可用** → 立刻兜底，不空转重试

锁只在两个瞬间持有（微秒级）：**取世界快照** 和 **提交决策**。
LLM 调用全在锁外——改造前整个决策包在全局锁里，七个居民彻底串行。

护栏 `ToolSpec.max_per_turn` 也是数据驱动的：循环只数次数，
不需要知道"发信"该限几次。

---

## 工具箱

| 工具 | terminal | 每轮上限 | 备注 |
|---|---|---|---|
| `move_to` | ✅ | — | destination 枚举 112 个值，占了 schema 的近一半 |
| `stay` | ✅ | — | 包括「等」；不查容量（位子本来就是你的），仍查营业时间与天气 |
| `sleep` | ✅ | — | 唯一能横跨整夜的动作，上限 12 小时。⚠️ **带前端跑时不会被调用**（前端到 bedTime 自己接管） |
| `send_mail` | ❌ | 1 | 改变世界但不占时间的典型 |
| `check_inbox` | ❌ | 1 | 读完自动标已读；读到请求时会提示用 `accept_task` |
| `check_stock` | ❌ | 2 | 要在店里，除非是店主（店主有账本） |
| `buy` | ❌ | 2 | 必须在店里；五件事的原子事务 |
| `restock` | ❌ | 3 | **只有店主**（永久门槛 → 不进其他人的 schema），且要在自己店里 |
| `transfer` | ❌ | 1 | 不可逆；**不需要见面** |
| `give_item` | ❌ | 2 | **必须当面**——和 transfer 相反；「帮人跑腿」唯一的终点 |
| `check_weather` | ❌ | 1 | 查**预报**；当前天气免费进 context |
| `accept_task` | ❌ | 1 | 跨轮的差事，判定 = `holdings(某人)[某物] > 0` |
| `accept_meeting` | ❌ | 1 | 约时间地点，**给双方各建一条**；判定 = 两人都在那个区域 |
| `recall` | ❌ | 3 | 主动检索记忆（原本是被动注入 top-12） |

⚠️ **`check_balance` 已删。**钱和背包是「关于自己的、不用动作就知道的」，
免费进 context。它曾在三天里被调 161 次，其中一人 43 次而余额从未变过。

**免费进 context**：能看见的人、未读信**数量**、自己的钱和背包、**当前**天气、
在办的任务、临近的约定（强制顶到最前）。

**要花一步去取**：信的内容、店里的货、天气**预报**、记忆。

分界线**不是信息量，是「这是关于谁的」**：自己的东西随时知道，别人的钱、
店里的货、信的内容都得动作才能得知。天气正好横跨两边——抬头看见的当下
免费，预报要查。

scratchpad 也分两段渲染：**「已经知道的」只给结果**（哪个工具查到的无关紧要），
**「被拒绝的」保留工具与参数**（要防的正是重复同一个调用）。混在一起时，
一条刚学到的事实和一扇刚关上的门长得一模一样。

---

## 世界规则

**营业时间**：Café_bar 7:00–22:00 · Supermarket 8:00–21:00 · Pharmacy 9:00–18:00。
Park 与住宅全天开放。**店主不受营业时间限制**（可提前备货）。

**容量**：每家店 3 个顾客位，**店主不占名额**。Park/住宅不限。

**店主**：Supermarket→Ron Parker，Pharmacy→Ella Parker。
**Café_bar 无人经营**（库存只能亲自去看，问不到人——这个不对称是刻意的）。

**商品**：Supermarket 五种各 4 元/上限 3 个 · Café_bar coffee 8·tea 6·cake 6/上限 4 个 ·
Pharmacy 四种药各 8 元/**上限仅 2 个**（稀缺是故意的，否则超卖路径永远走不到）。

**钱**：初始 15，**每三天领 15 社保**，除店主外没有别的收入。一天摊下来 5 块，
**一杯 8 块的咖啡都买不起**——所以开口借钱是必需行为，不是点缀。

**补货分两套**：
- 有主的店（Supermarket/Pharmacy）→ **店主自己调 `restock` 掏钱进货**，
  进货价 = 售价 − 2，差价是毛利；钱不够就按买得起的量进（小店能自举）。
  开局满货，所以第一天就有东西可卖。
- Café_bar 无人经营 → 系统每日**自动补满**。它的钱进虚空、货从虚空来，收支中性。

**天气**：真实数据来自 Open-Meteo（免费、无需 API key），坐标写死伦敦。
**每个游戏日只调一次**，缓存 24 小时逐小时数据；游戏时钟走到几点就用那一小时。
大雨/暴雪/雷暴时**户外锚点被拒**（`move_to` 和 `stay` 都拒），小雨和毛毛雨不拦。

⚠️ **户外是锚点级判断，不是区域级**——`Café_bar.Patio` 是露台，同一家店里
既有室内也有户外。营业时间和容量按区域算，天气按锚点算，**见面按区域算**。

**任务与承诺**：期限一律是「当天几点」，跨天即作废。同类任务每人同时最多 2 件
（跑腿和赴约分开计数）。承诺 = 一次 `accept_meeting` 给**双方各建一条**记录，
判定要求**两人都在**那个区域——只查自己的话，一个人在空荡荡的公园干等也会
算作履约。任何一方排不下就整体作废，**绝不留单边约定**。

**动作时长会被裁剪**：定下时长的那一刻，若 `now + duration` 会越过手上最早的
一个截止时刻，就裁到那之前 15 分钟（要留时间赶路）。没有这一步，一个九小时
的午觉就能把当天所有约定和差事一并作废——而动作一旦开始，后端就退出了，
播放期间没人会再问它任何事，**「到时候提醒他」根本无从发生**。

---

## 环境

- **模型**：`deepseek-v4-flash`（旧别名 `deepseek-chat` 仍可用但已过时）
- ⚠️ **DeepSeek v4 思考模式拒绝任何 `tool_choice`（HTTP 400）**，
  所以 `llm.py` 在统一出口注入 `thinking: {"type": "disabled"}`
- 多工具选择用 `tool_choice: "required"`，已实测可用（5/5 选对，thought 字段 100% 填充）
- 接口体检：`python scripts/probe_tool_choice.py`（读 `backend/.env`）
- **天气**是唯一的真外部依赖：三层保底 = 真实调用 → 重试（指数退避 + **jitter**）
  → 熔断 → 确定性降级。全部用**故障注入**测试，一次真网络都不打。
  降级天气用 `life_day` 做种子，保证同一天两次查询一致——否则模型会看到
  自相矛盾的世界；而且降级天气**也会变坏**，否则接口一挂，"下雨改计划"
  那条分支就再也走不到了。

## 命令

```bash
cd backend && python -m pytest tests/ -q      # 353 个测试，无 LLM 调用、无真实网络
node scripts/smoke_24h.js                     # 路径 smoke test
python scripts/dry_run.py --days 2            # 真实 LLM 驱动整座小镇（花钱）
python scripts/dry_run.py --days 2 --scenario errand   # 埋一个起因，验证协作链
python -m observability.metrics logs/action_trace.jsonl   # 从日志算行为指标（离线、免费）
python -m evals.runner --scenario scarcity --ablate none        # 跑一格（花钱）
python -m evals.runner --scenario all --ablate all --repeats 2  # 整张记分卡（很花钱）
```

---

## 进度

**已完成**
- 工具注册表 + 多工具选择 + ReAct 循环 + 锁重构 + 动作日志
- 四个世界系统：通信、经济（货+钱+进货）、天气、任务
- `stay` / `sleep` / `give_item` / `accept_task` / `accept_meeting`
- 工具白名单（只按**永久**资格筛）、重复查询拦截、动作时长裁剪
- 并发验证：七人并发 0.25s vs 串行 1.43s
- 装配冒烟测试（`test_app.py`）——曾经 215 个测试全绿而 `main.py` 起不来
- **删掉改造前的单步决策路径**（`decide_next_action` / `llm.call_tool` / 旧 `eval/`）——
  代码库里只剩一条决策路径了。删掉的三个测试不丢覆盖，都能在新路径的测试里找到对应
- **指标层**（`observability/metrics.py`）：从动作日志算行为指标，15 个测试
- **按框架分包**：`world/` `runtime/` `llm/` `api/` `evals/` 建起来了，106 处 import 跟着改。
  依赖方向变成严格单向，`SHOP_OWNERS` 那份被环逼出来的重复也跟着删了
- **评估集**：`runtime/scheduler.py`（`dry_run` 和 `evals` 共用的引擎）+ 四道题 +
  七种消融 + 记分卡。`scarcity` 首跑 PASS，**没有超卖**——那把原子锁第一次被真正考验
- **成本指标**：token / 延迟 / 重试从 LLM 日志算，评估按格拆
- **LLM 熔断**：401/402/403 不会自己好，撞上就拉闸。同样的故障下发出的请求
  从 1927 次降到 1 次
- **记分卡分得清「模型没做到」和「后端挂了」**：模型一次都没成功应答过的格子
  标 `ERR`，**整个不进对照表**。一张会说谎的记分卡比没有记分卡糟
- **工具按此刻状态过滤**（省 11% 输入）+ **`context_builder` 抽出**（纯结构，输出不变）
- **架构约束进了测试**（`tests/test_layout.py`）：存档必须在 backend/ 根下、
  `world/` 顶层不许 import 上层、`world/__init__.py` 必须空、`SHOP_OWNERS` 只许有一处
- **分段判据**：一道题拆成 3-6 环，看得出卡在**哪一环**
- **单步工具选择评估**（`evals/tool_choice.py`）：8 条用例，一次 24 调用两分钟
- **事件系统**（`world/events.py`）：世界里发生过什么 + **谁察觉得到**。
  转账原本对收款人完全无声
- **每人每天的调用/token 预算**（`runtime/budgets.py`）
- **动作日志带 trace_id 和 goal**：行为和成本现在能对上

## 评估：交接要点

### 怎么跑

```bash
cd backend
python -m evals.runner --scenario errand --ablate none,pre-rebuild --repeats 2 --note 头条
python -m evals.runner --scenario all --ablate all --repeats 2 --note 全矩阵   # 约 6 小时
python -m evals.tool_choice --repeats 3 --note 基线                 # 单步题，两分钟
python -m observability.metrics logs/<某个>.jsonl                   # 离线算指标，免费
```

每跑完一格立刻落盘到 `logs/eval_v*/rows.jsonl`——中途 Ctrl-C 不会把已经花掉的
钱扔掉。撞到账户级故障（401/402/403）会自动中止整张表。

### 版本号：v1、v2、v3……新的数字更大

```
logs/eval_v10_修了递交/       ← --note 的内容跟在号后面，可选
logs/toolchoice_v7_修了递交/
```

编号由 `evals/run_dir.py` 自动取「现有最大值 + 1」，**只看名字不看修改时间**
——目录会被复制、备份、同步，时间靠不住，名字靠得住。看错了会覆盖旧结果。

⚠️ **版本号只有配上「跑的是哪个 commit」才有意义**，否则它只是个流水号：
v7 和 v8 结果不同，中间改了什么无从查起。所以每个目录里落一份 `run.json`，
记命令、commit、分支，以及**工作区脏不脏**——脏的时候那个 commit 号并不能
唯一确定代码，这一点必须写在脸上，不能让人事后误以为两次可比。

### 两类题，问的不是同一件事

```
evals/scenarios.py    跑一整天，看**结果**   —— 药到 Adam 手上没有
evals/tool_choice.py  跑一步，  看**选择**   —— 这个处境它第一个挑了什么工具
```

单步题便宜两个数量级，适合验证一次措辞改动；场景题贵，适合出最终结论。

### 场景与预算

```
errand      6 环   300 次决策   跑腿：读信→接任务→借钱→买→约见面→当面交付
rendezvous  4 环   300 次决策   非见面不可：东西只能当面交
scarcity    3 环   120 次决策   只剩一盒药两个人抢：不能超卖
natural     控制组  40 次决策   什么都不埋
```

预算给得宽是**故意的**：一天到天黑自然结束（约 120-150 次决策），早停又兜着，
所以富余的预算不会真花掉。给紧了会**伪造失败**（见下面第三个坑）。

### 十一种消融

```
none                  基线
pre-rebuild           单步 + 只有 move_to —— **真正的改造前**
single-step           单步但十四件工具可选 —— 不是改造前，见 evals/ablations.py
no-outgoing-mail / no-meetings / no-recall / no-tasks     各摘一件工具
no-prices / no-events                                     各关一段 context
no-handover-window    人在眼前时不提醒他交得出去 —— 摘的是**三行字**，
                      `give_item` 照样在。见"时机的另一半"那节
state-filtered-tools  此刻用不了的工具不进 schema
```

⚠️ 加了新旋钮要同时登记进 `test_evals.py` 的 `knobs`，否则一条"什么都没
关掉"的消融会安静地和基线跑出同样的数字，被读成"这个能力没用"。

### ⚠️ 评估设计踩过的三个坑（都已修，别再踩回去）

**① 二元判据在多环任务上没有信息量。**`errand` 十四格全 ✗，其中一格已经把药
买到手（六环走了五环），另一格一个改变世界的动作都没有——**记分卡上一模一样**。
所以有了分段判据。⚠️ 很多里程碑是转瞬即逝的（借到钱那一刻余额是 8，买完变 0），
所以要**每批决策查一次、记最高水位**，只在最后查等于什么都看不见。

**② 记分卡会把「后端挂了」说成「模型很差」。**账户余额见底之后，系统又打了
1927 次注定失败的请求，产出三十格 `FAIL / wasted 100%`。现在：客户端撞到
401/402/403 就拉闸，runner 中止，那些格子标 `ERR` 且**整个不进对照表**。

**③ 决策预算太紧会伪造失败。**`errand` 那条链 11:05 约好 12:00 见面、对方
11:20 已经动身，评估在 11:30 掐断了。差三十分钟游戏时间，记分卡上却和
「一环都没走」长得一样。现在跑到上限结束的格子标 `✗⏱`，和真做不到分开。

### 目前已知的数字

```
改造前 vs 现在（errand / rendezvous / scarcity）
  pre-rebuild   0/6 环，改变世界 0 次 —— 它只会走路
  none          errand 3 次里 2 次完整通关（6/6 环）

单一能力的因果（干净的一条）
  scarcity  none 2/2 通关 → no-tasks 0/2   摘掉 accept_task 就做不成

反向证据
  rendezvous  no-meetings 和基线一样 —— 摘掉一个它本来就不用的东西，当然没影响

成本
  一次决策 prompt_tokens 中位 4279，其中**约 85% 是工具 schema**
  p90 延迟 2.2-2.9s
```

⚠️ 这些数字来自**不同批次**的跑，中间行为改过好几次，**不能直接横向比**。
README 要用的那组必须来自同一次全矩阵。

### 还没解决的模型毛病（这次评估会量出来）

**① 默认别人在他该在的地方。**单步用例 `they_are_not_here` 三次全错，
都选了 `move_to` 去碰运气。真跑里 `target_absent` 一天 44-53 次。

**② 买之前不检查买不买得起。**单步用例 `short_of_money_in_the_shop` 三次全错。
四个实验证明**事前**怎么提示都没用（见「怎么让模型改变行为」那节），
只有撞墙那一刻说话管用——但那救的是多步场景，救不了单步的第一个选择。

**接下来**（按建议顺序 A → B → D → C）

### A. 跑那张决定性的记分卡 ← **下一步就是这个**

行为已经冻结（这一批全部提交完毕），可以跑了。三个选项：

```
A 全矩阵      3 题 x 10 消融 x 2 次 = 60 格   约 5.5 小时   最完整
B 只跑头条    3 题 x (none/pre-rebuild) x 2 = 12 格   约 1 小时
C 全矩阵但 repeats=1                          约 2.5 小时   n=1 不敢下结论
```

**建议 B 先跑**：README 的核心叙事只需要「改造前 vs 改造后」，一小时拿到；
完整消融表是给面试深挖用的，可以在写 README 的时候后台补。两件事并行。

⚠️ **跑之前别再改行为**——任何一处改动都会让这张表和下一张不可比。
⚠️ 长跑期间**别动注册表**：加消融/加场景要在启动前做完，这个错犯过两次。

### B. 评估指出来的问题（每改一条，跑同一张记分卡对比）

- [ ] **B1 跨轮不该重走死路。** errand 的 trace 铁证：Emma 在 9:20 / 10:35 / 11:50
  把「走到药房 → 买 → 差 5 块 → 兜底」原样重演三遍。轮**内** replan 92.9% 很好，
  轮**与轮之间**只传了一条 `last_observation`。对应框架里的 `BLOCKED / WAITING`
- [ ] ~~**B2 JSON 解析失败**~~ —— 量过了，只影响 **0.25%**（8/3200 轮），不值得优先。
  原文留档： 模型把 `"nobody"` 写成裸
  `nobody`，`call_tools` 返回 None，循环判成「LLM 不可用」当场放弃整轮；而编错
  工具名只被拒一步还能重来。同样的小错，代价差一个数量级——该给它一次带着
  「你的 JSON 坏了」重来的机会
- [ ] **B3 `already_known` 拦下了，但仍烧掉一整轮 LLM 调用。** 三天真跑 45 次
- [ ] **B4 视 `rendezvous` 结果决定要不要动约见面。** `target_absent` 44–53 次，
  `accept_meeting` 三天只用过 1 次
- [ ] **B5 输入 token 的 85% 是工具 schema。** 两天真跑实测：一次决策
  `prompt_tokens` 中位 4279，而 messages 只有约 649 tokens——**真正的决策上下文
  只占 15%**。schema 每次调用一模一样。三个方向：prompt 缓存、瘦身
  `destination` 那个 112 值枚举（一件占 20%）、按人裁剪工具。
  ⚠️ 但**不能按「此刻能不能用」裁**：看不见的能力模型不会为它做计划
- [ ] **待定** 拒绝理由要不要往出路上指（「你可以写信问别人借」）。这是
  **喂答案 vs 测能力**的取舍，得先定了才好动

### C. 框架里规划了、还没长出来的

- [x] ~~**C1** `runtime/context_builder.py`~~ —— 抽完了，输出一字不差，12 个契约测试
- [ ] **C2** `runtime/budgets.py` —— 框架 Phase 7 缺的唯一一项：token / 每日调用预算
- [ ] **C3** `api/persistence.py` —— `routes.py` 五百多行里六个路由是纯存档读写
- [ ] **C4** `world/events.py` + 事件驱动唤醒。
  ⚠️ **真事件驱动要改前端**（`game.js` 才是生产的 scheduler），而约定是前端不改。
  守约定的话只能做后端半事件驱动：事件进队列，等该居民下次来问时作为 trigger 塞进 context

### D. 呈现（投递用，需要 A/B 的数字才写得好）

- [ ] **D1 README 重写** —— 现在通篇还在讲「模型被强制填一张表」，一个字没提
  工具注册表、会拒绝的世界、四个世界系统、评估集。**这是简历链接过去第一眼看到的**
- [ ] **D2** 记分卡数字进 README（「基线 ✓ / 改造前 ✗」比任何形容词都硬）
- [ ] **D3** GitHub About + topics + 演示 GIF

## 怎么让模型改变行为（四个实验，一正三负）

`errand` 这道题上，七种配置十四格**全部卡死在「凑够药钱」这一环**——
她读到信、记下任务、走到药房、发现钱不够，然后就再也没有开口借过钱。
围绕这一个卡点做了四次实验，每次都用单步评估量（一次 24 调用、两分钟）：

| 做法 | 落点 | 结果 |
|---|---|---|
| 把价格放进 context | 买之前 | **没用** 0/3 |
| 工具描述里叮嘱「先对一下钱包」 | 买之前 | **没用** 0/3 |
| 必填一个 `cost` 字段，逼它把数字打出来 | 买之前 | **没用** 0/3 |
| **拒绝理由里点明「写信问人借」** | **撞墙那一刻** | **有用** 0/14 → 3/3 |

三次失败的共同点是它们都在**事前**做文章。看它当时的 thought 就明白了：

```
"I need to buy cold medicine for Adam who has a fever."
"My son Adam has a fever and needs cold medicine. I'm at the pharmacy."
```

**任务一急，约束就隐形。**价格摆在余额下一行也不看，必填字段填了照样点 buy。

所以这条经验是：

> **在撞墙的那一刻指出那条路，比在系统提示里泛泛叮嘱管用得多。**

同一条规律此前已经在 `movement.py` 的 `target_absent` 上出现过一次（旧措辞
只说"你得先弄清楚他们在哪"，三天 94 次撞墙，模型一次都没想到写信打听；
改成点明"可以写信问"之后就用上了）。现在有**两个独立的例子**，而且这次是
**先做了三个失败的实验、再做成功的**——对比比孤立的成功案例值钱。

### 措辞怎么写

给**岔路口**，不是给答案：

```
You are 5 short. Decide whether you really need it: if it can wait, or
something cheaper will do, leave it. If you do need it, write to someone
and ask them to send you the money — nobody can hand you cash in person.
```

- **先让它判断这东西是不是非要不可**——直接说"去借钱"会把它推向一个未必
  对的方向，镇上大多数东西本来就可以不买
- **最后那句是世界规则，不是喂答案**：镇上没有当面要钱这件事，钱只能由
  对方主动 `transfer`。模型无从推断这一点，除非告诉它

⚠️ 这条经验**不能推广成"多写提示"**。三个失败的实验恰恰证明了：写在
schema 里、写在描述里、写成必填字段，都不管用。有效的是**时机**——
失败刚发生、模型正要重新规划的那一刻。

## 时机的另一半：机会窗口

上面那条讲的是**撞墙**的那一刻。还有一个对称的时刻：**窗口刚打开**的那一刻。

rendezvous 两次真跑，Arthur 和 Mia 都碰上了面，蛋糕**两次都留在他手里**——
`give_item` 在 302 轮里**一次都没调过**（不是调了被拒，是压根没想到）。
其中一次 151 轮里走了 **150 轮**。

诊断不是"它不会用这个工具"，是**三条信息在上下文里分三段摆着**：

```
People you can see from here: Mia Thompson.              ← 一段
You have 8 in your purse and are carrying cake x1.       ← 另一段
- meet Mia Thompson at Park at 3:00 PM [already satisfied] ← 第三段
```

三条都在，模型没连起来。所以在窗口打开的那一刻拼成一句顶到最前
（`world/goals.py` 的 `summary_for`），和临近约会的置顶行同级：

```
You are with Mia Thompson right now. Handing something over only works
face to face — if there is anything you meant to give them, it has to
happen before either of you moves on.
```

同样只说**世界规则**（只能当面）和**那个会消失的事实**，不点工具名、
不说"去递"。这也把 `due_now` 那条时间线补完整了——原本说到"你三点要去
见谁"就断了，而**碰上的那一刻**才是窗口真正打开。

### ⚠️ 修得对，不等于修的那条路上有人走

第一版只挂在 **DELIVER 任务**上。单步用例 `person_is_right_here` 立刻从
0/4 变 6/6，看起来成了。于是拿 rendezvous 去验——**那行字在一整次跑里
出现 0 次**。

因为 Arthur 开局就拿着蛋糕、信里问的是"约个时间地点"，他直接
`accept_meeting`，**从没调过 `accept_task`**。这道题走的是 MEET 那条路，
而我只接了 DELIVER 那条。

那一跑还 1 PASS 1 FAIL，**差点被读成"修好了一半"**——真实情况是这两格
和改动完全无关，只是两个新的基线样本。

留下两条规矩：

- **先验那行字出现了没有，再看通没通关。**一次 `grep "right here with you"
  logs/eval_v*/**.jsonl` 就能戳破，比看记分卡快、比看记分卡准
- **测量口径要覆盖真实路径。**单步用例是自己摆的处境，它证明"给了提示模型
  会用"，不证明"真跑里这个提示会出现"。两者之间隔着一整条行为路径

## 工作约定

- **前端不改**。响应**只加字段不改字段**（`decision` 结构与改造前一致），
  前端因此一行不用动，demo 始终能跑。
- **每一步都要能在面试里逐行讲**——所以分步做、每步跑测试、每步 review diff，
  不攒着最后一起看。
- ⚠️ **Git Bash 的 heredoc 会吃掉 `\n` 转义和全角引号**。写含中文或转义的
  patch 脚本时用 Write 工具写成 `.py` 文件再执行，不要用 `python - <<'EOF'`。
- ⚠️ **每个字符串替换都要 `assert` 命中次数。**漏了 assert 的 `str.replace`
  在锚点写错时会静默返回原文——曾因此让 `main.py` 引用了一个不存在的名字，
  而 215 个测试全绿，因为没有一个测试 import 过它。
- 改动都在工作区**未提交**，`git diff` 可 review。
