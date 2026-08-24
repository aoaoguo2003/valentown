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

| 层 | 文件 | 职责 |
|---|---|---|
| **世界状态** | `world.py` `mailbox.py` `economy.py` `weather.py` | 世界里有什么、规则是什么。数据 + 原子操作。 |
| **工具** | `tools/`（包） | agent 能对世界做什么。每个工具 = schema + handler。 |
| **运行时** | `runtime.py` | 决策循环。**不认识任何具体工具。** |
| **路由** | `main.py` | 两段锁：取快照 / 提交决策。 |
| **居民** | `agents/agent.py` | 角色定义 + 上下文组装。常量从 `tools` re-export。 |

`tools/` 包的内部分层：

```
locations.py       小镇的地理与居民名册（不依赖任何项目模块，可被 world.py 安全导入）
base.py            ToolSpec · reject/accept · THOUGHT_FIELD
movement.py        move_to · stay                    占用游戏时间，会收敛本轮
communication.py   send_mail · check_inbox           改变世界但不占时间
shopping.py        check_stock · buy · restock       同上
wallet.py          check_balance · transfer          同上
weather.py         check_weather                     纯查询
remembering.py     recall                            纯查询
__init__.py        TOOL_REGISTRY + get_tool/function_schemas + re-export
```

**工具是门，状态模块是房间。**每加一个系统都是这个模式：
`mailbox.py + tools/communication.py`、`economy.py + tools/shopping.py`。
**这条路已经走过五遍**（stay、通信、库存、钱包、天气），`runtime.py`
从写完到现在一行没改过——这是注册表设计最好的证据。

依赖方向：`tools/movement.py` 等在**函数内部**才 import `world`，
所以 `world.py` 能在模块顶层 `from tools.locations import AGENT_NAMES`
而不引起循环。

---

## 四条不能破的规则

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

### 4. 慢 I/O 永远不进临界区

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

## 决策循环（`runtime.py`）

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
| `move_to` | ✅ | — | destination 枚举 112 个值 |
| `stay` | ✅ | — | 包括「等」；不查容量（位子本来就是你的），仍查营业时间与天气 |
| `send_mail` | ❌ | 1 | 改变世界但不占时间的典型 |
| `check_inbox` | ❌ | 1 | 读完自动标已读 |
| `check_stock` | ❌ | 2 | 要在店里，除非是店主（店主有账本） |
| `buy` | ❌ | 2 | 必须在店里；五件事的原子事务 |
| `restock` | ❌ | 3 | **只有店主**，且要在自己店里；进货价 = 售价 − 2 |
| `check_balance` | ❌ | 2 | 只看得到自己的钱 |
| `transfer` | ❌ | 1 | 不可逆；不需要见面 |
| `check_weather` | ❌ | 1 | 查**预报**；当前天气免费进 context |
| `recall` | ❌ | 3 | 主动检索记忆（原本是被动注入 top-12） |

**免费进 context 的**（随世界快照一起取，同一时刻的横截面）：
当前位置能看见的人、未读信**数量**、自己的余额、**当前**天气。

**要花一步去取的**：信的内容、店里的货、天气**预报**、记忆。

分界线是**信息量**：一个数字塞进每次决策的 prompt 无所谓，一堆内容就意味着
每次决策都在为可能用不上的东西付 token。抬头看天免费，看预报要花时间。

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
既有室内也有户外。营业时间和容量按区域算，天气按锚点算。

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
cd backend && python -m pytest tests/ -q      # 156 个测试，无 LLM 调用、无真实网络
node scripts/smoke_24h.js                     # 路径 smoke test
python eval/run_eval.py --repeats 2           # 端到端，会真实调 LLM
```

---

## 进度

**已完成**
- Step 1 工具注册表（`ToolSpec` + `TOOL_REGISTRY`）
- Step 2 多工具选择（`llm.call_tools` + `tool_choice: "required"`）
- Step 3 环境会说不（营业时间 / 容量 / 在场判定）
- Step 4 决策循环（`runtime.py`）
- Step 5 锁重构（LLM 移出锁外 + 提交前重校验）
- Step 6 动作日志（`backend/logs/action_trace.jsonl`）
- `stay` 工具（补上「等待」这个能力，通信的前置条件）
- 通信系统（`mailbox.py` + 两个工具 + 未读提示进 context）
- 库存与经济（`economy.py` + `check_stock`/`buy`/`restock`/`check_balance`/`transfer`）
- 天气（`weather.py` + `check_weather` + 户外约束 + 故障注入测试）
- 并发验证（`tests/test_concurrency.py`，把"锁没毁掉并发"量成了数字）

**🔴 下一步（优先级最高）：用真实 LLM 跑一次**

11 个工具、156 个测试，**全部是脚本化的假 LLM 测的**——验证的是"循环逻辑
对不对"，完全没验证**真实模型面对 11 个工具会怎么表现**。未知的很多：

- 11 个 schema 全进 prompt（`move_to` 光枚举就 112 个值），会不会选择困难？
- **会不会用 `stay` 来等**？这是通信链条的关键一环，但模型可能想不到
- 会不会疯狂调查询工具，五步用完还没做出行动？
- 会不会根本不碰新工具，永远只用 `move_to`？
- 被拒之后是真重新规划，还是换个说法再撞一次？

这些只有真跑才知道，而且**会直接影响设计**（可能要减工具、改 description、
调 `MAX_STEPS`）。成本大约几毛钱。**在继续加系统之前先做这个。**

**之后**
- 承诺机制（约定 + 冲突检测 + 履约判定 → 产出「承诺履约率」指标）
- 评估集 + 指标（任务成功率 / 无效工具调用率 / 平均重规划次数）+ baseline 对照
- 可选：`main.py` 515 行可抽个 `persistence.py`（装配 + 持久化 + 17 个路由混在一起）

---

## ⚠️ 两条平行的决策路径

改造后决策逻辑有两条路，**改一条时必须想到另一条**：

```
生产:  main.py -> runtime.run_decision_loop -> llm.call_tools
       7 个工具、多步循环、环境会拒绝、提交前重校验

评估:  eval/run_eval.py -> agent.decide_next_action -> llm.call_tool
       单步、强制单函数、只有 move_to      <- 改造前的老路
```

也就是说 **eval 现在测的不是生产走的那条路**，它全绿并不能说明新循环没问题。
tests/test_core.py 里的三个测试同样挂在旧路径上。

用户决定评估留到项目改完再统一重做（届时评分标准也要重设计：该测工具选得对
不对、被拒后会不会重规划、无效调用率，而不只是目的地对不对症）。
在那之前 `decide_next_action` 和 `llm.call_tool` **不能删**。

## 工作约定

- **前端不改**。响应**只加字段不改字段**（`decision` 结构与改造前一致），
  前端因此一行不用动，demo 始终能跑。
- **每一步都要能在面试里逐行讲**——所以分步做、每步跑测试、每步 review diff，
  不攒着最后一起看。
- ⚠️ **Git Bash 的 heredoc 会吃掉 `\n` 转义和全角引号**。写含中文或转义的
  patch 脚本时用 Write 工具写成 `.py` 文件再执行，不要用 `python - <<'EOF'`。
- 改动都在工作区**未提交**，`git diff` 可 review。
