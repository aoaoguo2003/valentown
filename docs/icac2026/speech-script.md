# ICAC 2026 · Paper 108 — 10 分钟演讲稿（含 2 分钟演示视频）

**A Lightweight LLM-Driven Multi-Agent Framework for Virtual Society Simulation with Memory Feedback**
Aoao Guo, Xinyi Tao, Huakang Li, Xuewu Dai

- 时间：2026 年 8 月 27 日（周四）17:35 – 17:50 (BST)
- 场次：Parallel Session 3 — Robotics & Autonomous Systems，会场 N2.10
- 幻灯片：`ICAC2026_Paper108_Valentown.pptx` —— **正式页 12 页 + 备用页 3 页**，图为主、字为辅
- 中英对照版：`ICAC2026_Paper108_Script_EN-CN.docx`（左英右中，逐段语义对照，只有讲稿本身）
- 英文讲稿已放进每页备注栏 / Speaker Notes；页面上只留关键词和示意图，**照着页面念是不够的，按下面的讲稿讲**

---

## 一、这一版砍了什么

为了腾出 2 分钟放演示视频，从正式流程里拿掉了两页（约 1 分 25 秒的讲话量）。**它们没有删除，而是移到致谢之后当备用页**，问答时可以直接跳过去：

| 原来的页 | 原用时 | 现在在哪 | 为什么可以拿掉 |
|---|---|---|---|
| Framework（架构图，图 1） | 0:40 | 备用页 **B1** | 视频里就能看到前后端各自在干什么，五个模块的名字对 10 分钟的报告没有价值 |
| Discussion（优势 / 局限） | 0:45 | 备用页 **B3** | 局限已经压成三个词并入结论页；优势在前面几页已经讲过 |

**Execution（流程图，图 2）留在正式流程里，就放在视频前面**——先把"一天怎么跑"讲清楚，再让观众看它跑，视频就成了这页的证据，而不是重复。为了配合，这页的讲稿压到 35 秒，最后一句直接接视频。

另外原来的实现页（Valentown 静态截图）变成了备用页 **B2**——它同时是**视频放不出来时的兜底**：直接跳过去，照着视频的讲法讲这张图。

---

## 二、时间分配

正式部分讲话约 **1,080 词** + 2 分钟视频。按 130 词/分钟计约 **10 分 15 秒**；讲得慢一些（120 词/分钟）会到 10 分 40 秒，所以留了 `[可删]` 的缓冲。

| # | 页面 | 内容 | 目标用时 | 累计 |
|---|---|---|---|---|
| 1 | Title | 自我介绍 + 一句话概括 | 0:35 | 0:35 |
| 2 | Motivation | 两条路线各自的短板 | 0:55 | 1:30 |
| 3 | Problem statement | 一个问题、三项要求 | 0:45 | 2:15 |
| 4 | Mechanism 1 & 2 | 日程驱动 + 时空交互 | 0:55 | 3:10 |
| 5 | Mechanism 3 | 记忆反馈闭环（**重点**） | 1:00 | 4:10 |
| 6 | Execution | 一个模拟日的完整流程 | 0:40 | 4:50 |
| 7 | **DEMO** | **运行视频** | **2:00** | **6:50** |
| 8 | Experiments | 实验设置与关注点 | 0:35 | 7:25 |
| 9 | Result 1 | 交互消融 | 0:55 | 8:20 |
| 10 | Result 2 | 记忆随时间演化 | 0:50 | 9:10 |
| 11 | Conclusion | 结论 + 局限 + 未来工作 | 1:00 | 10:10 |
| 12 | Thank you | 致谢，进入提问 | 0:05 | 10:15 |
| B1–B3 | Backup | 架构 / 截图 / 优势局限 | — | 问答时用 |

**时间锚点：第 5 页讲完 4:10，视频 4:50 开始、6:50 结束。**

**超时怎么办**：文中标 `[可删]` 的句子共约 65 词，全略可省 30 秒，落到 9:45；还不够就把第 8 页（实验设置）压成一句 "seven heterogeneous agents, several consecutive days"，直接进结果。

---

## 三、逐页讲稿

> 英文为要讲的原话；中文为要点提示，不用念。

### 1 · Title

> Good afternoon. I'm Aoao Guo, from University College London, and this is joint work with Xinyi Tao, Huakang Li and Xuewu Dai. We've built a lightweight, LLM-driven multi-agent framework for simulating a virtual society, and the piece that holds it together is a memory feedback loop. The system is a small town called Valentown, where seven residents plan their own days, run into each other, remember what happened, and change what they do because of it.

- 中文要点：自我介绍 + 合作者 → 一句话说清做了什么 → 点名 Valentown 与七位居民。
- 动作：说到 "Valentown" 时用手示意底部那排像素小人，观众立刻有画面感，也为后面的视频埋伏笔。

### 2 · Motivation — Two ways to simulate people

> Multi-agent simulation is how we've modelled complex systems for decades — social networks, transport, smart cities. But classical agent-based models run on predefined rules, and it shows: good at macro patterns, poor at human behaviour. No context, no planning, no memory.
>
> Large language models changed what one agent can do. An LLM agent produces coherent language, holds context, and imitates parts of human reasoning.
>
> But something is still missing. Most LLM agent systems are reactive — they answer whatever prompt is in front of them. There's no structure to the day, and interaction is ad hoc. So behaviour drifts, the dynamics are hard to control, and results are hard to reproduce. That's the gap we're targeting.

- 中文要点：左卡＝传统 ABM（`固定规则 → 行为`）；右卡＝LLM 智能体（`Prompt → LLM → 行为`，会说话但**是反应式的**）；下方黄条＝真正缺的东西：行为、交互、反馈都没有显式结构。
- 讲法：对着两个小流程图讲差别，不要念卡片上的小标签；讲到 "That's the gap we're targeting." 停一拍，这是全场的转折点。

### 3 · Problem statement — One question, three requirements

> So the question we set ourselves is this: how do you design a virtual society where the agents are structured, evolving and controllable — all three at once?
>
> That breaks into three requirements, each answered by one mechanism — and those are our three contributions. [可删]
>
> Temporal structure: behaviour has to be organised as a day. Our answer is a schedule-driven agent design.
>
> Evolution: yesterday has to change tomorrow. Our answer is a memory-based feedback loop.
>
> Controllability: interaction should follow an explicit rule, and a person should be able to step in. Our answer is a deterministic co-location trigger, plus optional human-in-the-loop feedback.

- 中文要点：黑框里就是研究问题；三张卡＝三项要求，卡下面绿色小块＝我们的答案，也正好是三个贡献。
- 讲法：三点节奏一致、干脆（"Temporal structure… Evolution… Controllability…"），这是评委记住你的地方。

### 4 · Mechanism 1 & 2 — Plan the day, then let the town decide who meets

> The first two mechanisms.
>
> Start with schedule-driven behaviour. Rather than asking an agent what to do at every moment, we let the day begin with an explicit schedule. The prompt combines identity, personality and goals with memories retrieved as context, and the model gives back activities and the destinations they imply. That's what keeps routines coherent over time — and interpretable for us.
>
> Second, interaction. We don't sample conversations at random. Two agents talk when they're in the same place in the same period — plain co-location. Because the trigger is deterministic, the social dynamics are reproducible; what gets said is still generated by the model.
>
> That's the design principle of the whole paper: deterministic when, generative what.

- 中文要点：机制一＝先有日程再有行为；机制二＝同时同地才对话，触发是**确定性**的，内容才交给 LLM。
- 讲法：左卡「家 → 咖啡馆 → 超市 → 家」的地点条用手划过去；右卡两个居民站在咖啡馆两侧＝共处触发。底部黑条那句 "deterministic *when*, generative *what*" 放慢、加重。地点条只是示意的一天，页面上已标 illustrative。

### 5 · Mechanism 3 — Memory is where the days connect ★重点

> The third mechanism, and really the heart of the paper: memory.
>
> Everything an agent produces goes into one store. Plans are kept as behavioural records, conversations as social experience, reflections as summaries. Every entry carries a category, a timestamp and an importance score.
>
> And everything reads from that same store. Planning retrieves relevant memories; dialogue retrieves recent history; reflection takes the important ones, compresses them into a short insight, and writes it back. That's the loop in the figure.
>
> Retrieval favours what's recent or important, and the store stays bounded, so what an agent keeps is what mattered. [可删]
>
> Two things worth adding. A person can write feedback into memory through that same channel. And the model itself is stateless — all the continuity lives in the memory system.

- 中文要点：左边两排＝**WRITTEN IN**（计划／对话／反思）和 **READ OUT**（规划／对话／反思），中间一行是条目属性；右边图 3 就是这个闭环。再补两点：人可从同一通道注入反馈；LLM 无状态，连续性全在记忆里。
- 讲法：评审最可能追问这一页，宁可多花 10 秒。指着图讲 "store in / generate" 两个方向。讲完这页应该正好 4:10。

### 6 · Execution — One simulation day, end to end

> Before the demo, one look at that loop as the system runs it.
>
> An agent initialises from its profile and its memory. On day one there's nothing to reflect on yet, so it plans straight from the profile; on every later day it reflects on memory first, and that reflection feeds the planning call.
>
> From there: generate the plan, store it, pick the destination, move, and talk if someone else is there — and the conversation goes back into memory. A closed loop.
>
> Let me show you that running.

- 中文要点：只强调一个分叉——第一天直接规划，之后先反思再规划；其余步骤沿着流程图用手划一遍即可，**不要逐框念**。
- 讲法：这页是视频的引子，40 秒就够。最后一句 "Let me show you that running." 说完直接翻页点播放，**中间不要停顿解释**，两页要连成一个动作。
- 好处：观众带着这张流程图去看视频，画面里发生的每件事都能对上号——视频因此是这页的证据，不是重复。

### 7 · DEMO — Valentown, running ★视频页（2:00）

**开场一句话说完就点播放，然后让画面自己走。**下面这段约 180 词，摊在 2 分钟里讲，中间大方留白——观众正在看画面，不需要你一直说话。

> **[点播放]** So that's the loop. Here it is running.
>
> This is Valentown. The whole town sits on one plane: homes along the top, the café, the supermarket and the pharmacy below, a park on the left. Everything you're seeing was produced by the Python backend — the planning, the dialogue and the reflection, and the only calls to DeepSeek — and the client simply replays it.
>
> **[约 0:20]** Watch one resident. He wakes up at home, and the schedule he generated at the start of the day sends him out to a destination. Nobody is steering him.
>
> **[约 0:50，两人相遇时]** Here two residents arrive at the same place in the same period — that's the co-location trigger firing. What they say is generated from their context and their recent memory, and it goes straight back into memory.
>
> **[约 1:30，入夜／反思时]** And at the end of the day each agent reflects on what happened — the step you just saw in the flow chart — and that reflection is what tomorrow's plan is built on.
>
> **[视频结束]** So the schedule, the trigger and the memory loop — everything from the last four slides — this is all of it, running.

- 中文要点：这 2 分钟要让观众亲眼看到前三页讲的三个机制，所以旁白只做**三次指认**：① 自主生成的日程 ② 共处触发对话 ③ 反思影响第二天。页面底部那行小字就是这三个指认，顺序一致。
- 剪辑建议（视频本身）：
  - 时长控制在 **1:50 – 2:00**，宁短勿长；用 2× 或 4× 倍速跑，让一整天（甚至两天）能放完。
  - 必须拍到的三个镜头：早晨居民从家出发 / 两人在同一地点弹出对话气泡 / 夜里反思与第二天不同的日程。
  - **静音**，或者直接导出无音轨——会场音响多半没接，有声反而出岔子。
  - 关键时刻可以轻微放大（右侧状态面板、对话气泡），远处观众才看得清。
- 风险预案：视频不放、卡住、格式不认——**不要修**，直接说 "let me show you the same thing as a still" 跳到备用页 **B2**（同一张截图，第 14 页），照上面这段讲。练习时至少完整走一遍这个兜底流程。

**怎么把视频放进去（PowerPoint）**

1. 打开第 7 页，那个深色边框里现在放的是一张截图（占位用，也是兜底画面）。
2. 菜单 **插入 → 视频 → 此设备**，选你的录屏文件（推荐 MP4 / H.264）。
3. 把视频拖到与深色边框**完全重合**：点视频 → 格式 → 大小与位置，填 **宽 26.9 cm、高 15.1 cm**，**水平 3.5 cm、垂直 2.2 cm**（相对左上角）。用英寸的话是 10.6 × 5.96 in，位置 1.37 / 0.88 in。截图会被完全盖住。
4. 选中视频 → **播放** 选项卡：开始设为 **自动**，勾选 **循环播放直到停止**（可选），**不要**勾"全屏播放"。音量设为**静音**。
5. 用 **文件 → 信息 → 压缩媒体** 压一下，避免文件过大在会场机器上卡顿。
6. 存成 `.pptx`（不要 `.ppsx`），拷 U 盘时确认视频是**嵌入**而不是链接——重新打开演示一遍确认能播。

### 8 · Experiments — What we ran, and what we looked for

> For the experiments we instantiate the framework with seven agents: a supermarket owner, a pharmacist, a couple with a seven-year-old, a family teacher and an architect. Their attributes ground everything the model generates. [可删]
>
> We run several consecutive virtual days, each one a full cycle. Scheduling is deterministic while the content is stochastic — a reproducible pipeline with diverse behaviour inside it.
>
> And we're asking three questions: what interaction does, what memory does, and whether social structure emerges on its own.

- 中文要点：人群异质 → 多个连续虚拟日、每日完整周期 → 「确定性流程 + 随机内容」的取舍 → 三个评估关注点（正好对应后面两页结果）。
- 讲法：视频刚放完，观众还在回味，这页要**快**，别恋战。

### 9 · Result 1 — Turn interaction off, and the town goes quiet

> The first experiment is an ablation on interaction.
>
> With interaction on, agents produce noticeably richer and more varied behaviour. The reason is mechanical, not mysterious: a conversation puts new context into memory, and memory is an input to the next plan. So what someone said to you yesterday shows up in what you do today. We see agents scheduling follow-ups, going back to the same places, and repeated contact reinforcing particular pairs.
>
> With interaction off, the town goes quiet. No new social information enters at all, so agents fall back on their initial goals, and schedules stay static day to day.
>
> So interaction isn't decoration here — it drives diversity and adaptation at the same time.

- 中文要点：页面上是两条链——绿色那条 `对话 → 记忆 → 第二天的计划 → 更丰富的行为`，灰色那条在第一个箭头上打了叉，链条断掉，结果是重复、孤立、日程不变。因果是关键，不要只念现象。
- 加分：可以回指视频——"the conversation you just saw is exactly this first box"。

### 10 · Result 2 — Memory changes shape as the days pass

> The second result is about memory over time.
>
> The content of memory doesn't stay the same. Early on it's mostly plans and observations. As the days pass, conversations and reflections become more prominent. Later still, the high-importance interaction and reflection memories form the dominant context for new decisions — the store turns from a log of activity into accumulated experience.
>
> And that content tracks behaviour. Agents with rich interaction and reflection memories adapt more and behave more coherently. Repeated interaction between two agents forms a persistent bond, which shows up later as repeated co-location. Nobody wrote a friendship rule; it comes out of memory plus retrieval. Where memory influence is limited, adaptation is weaker. [可删]

- 中文要点：左边三根柱子＝记忆构成随时间迁移（绿＝计划与观察，黄＝对话，深色＝反思）；右边两张卡＝记忆内容与行为变化相关。
- 讲法："Nobody wrote a friendship rule" 是本页记忆点，说完稍停。**柱状图是示意图**，页面下方已标 schematic；被问比例来源就直说这是定性趋势、不是实测比例。措辞用「相关 / 观察到」，不要说成统计显著。

### 11 · Conclusion — Where this leaves us

> To conclude. We've presented a schedule-driven multi-agent framework where planning, interaction and reflection are linked through a memory-centred feedback loop. Importance-based memory keeps what mattered, and reflection turns it into insight that guides the next day.
>
> What the experiments show is that these simple mechanisms are enough: agents develop consistent routines, form lasting relationships, and adapt from experience — with no hand-written behavioural rules anywhere.
>
> We're open about the limits. Every plan, conversation and reflection is an API call, so cost scales with agents times days; the study is small; and output varies between runs, which is why our evaluation is qualitative for now.
>
> And that sets the agenda: quantitative evaluation first, then scale and real-time reaction, then deeper reasoning — with applications to game NPCs, education, and embodied agents. [可删]

- 中文要点：结论一句话＝简单的生成式机制足以产生连贯 routine、持久关系与经验驱动的适应；接着**主动认三个局限**（成本、规模、随机性，页面左下就是这三个词）；最后用局限自然引出未来工作三条，把「定量评估」放第一位。
- 讲法：主动讲局限是这页的重点——评审最想问的就是"没有定量指标"，你先说出来，气场完全不同（原来单独的讨论页现在是备用页 B3，要展开就跳过去）。

### 12 · Thank you

> Thank you very much for your attention. I'm happy to take questions.

- 提问阶段把这一页留在屏幕上（有邮箱和论文标题）。后面还有 3 页备用页，需要时按页码直接跳。

---

## 四、备用页怎么用

放映时输入页码 + Enter 即可直接跳转（例如按 `1` `3` `Enter` 到 B1）。

| 页码 | 备用页 | 什么时候跳过去 |
|---|---|---|
| 13 | **B1 · Framework**（图 1） | 问"系统怎么搭的""前后端怎么分工""换个模型行不行" |
| 14 | **B2 · Implementation**（截图） | **视频放不出来时的兜底**；或问界面、地点设置 |
| 15 | **B3 · Discussion**（优势/局限） | 讨论深入到方法论取舍、可复现性、成本时 |

流程图（图 2）已经回到正式流程第 6 页，不再需要备用页。

---

## 五、问答预案

> 每条先给一句英文回答，后面是中文补充要点。回答控制在 20–40 秒。

**Q1. 和 Stanford 的 Generative Agents（Park et al., 2023）有什么区别？** ——最可能被问到

> Generative Agents is the work we build on, and the difference is structure. First, our behaviour is schedule-first: an agent commits to a day, rather than deciding step by step, which is what keeps long runs temporally coherent. Second, our interaction trigger is deterministic co-location rather than an ad-hoc or sampled encounter, so the social dynamics are controllable and repeatable. Third, the system is deliberately lightweight and modular, and it adds an explicit human-in-the-loop channel into memory.

- 中文补充：先肯定对方是基础工作，再讲三点差异：日程优先、确定性触发、轻量可复现 + 人在环。

**Q2. 刚才的视频是实时跑的吗？**

> No — it is a recording of a real run, not a live session. Behaviour is generated by the backend first and then replayed by the client, which is what keeps the visualisation smooth instead of stalling on an API call. Nothing in the video is scripted by hand; it is the model's output. Real-time decision-making is on our roadmap.

- 中文补充：如实说是录屏、行为预生成后回放；强调**内容不是人工编排的**，是模型输出；实时是未来工作。

**Q3. 为什么用确定性的共处触发，而不是概率触发？**

> Because we wanted the dynamics to be controllable and reproducible. If encounters are sampled, every run differs for two reasons at once — the sampling and the model — and you cannot attribute a behavioural change to either. With a deterministic trigger, the only stochastic component is the generated content. Adding a probabilistic gate on top is straightforward, and it would be a natural extension.

**Q4. 你们的结果是定性的，有量化指标吗？**

> Not yet, and we say so in the paper. Strict quantitative evaluation is hard when the generator itself is stochastic, so the current results are qualitative and comparative. Quantitative evaluation is our first future direction: social network analysis over the interaction graph, interaction frequency, plan coherence and task completion rates, plus user studies for perceived realism.

- 中文补充：结论页你已经先认了，这里可以 "as I mentioned" 接上，再给具体计划。

**Q5. 一天的 LLM 调用成本大概多少？**

> It scales with agents times days. Per agent per day it is on the order of a few calls: one for the schedule, one for the nightly reflection, plus one per conversation the agent takes part in. That is exactly why cost is listed as a limitation — with larger populations the interaction term is what grows fastest.

- 中文补充：只讲量级和增长项，不要报没测过的具体数字。

**Q6. 记忆会无限膨胀吗？怎么控制？**

> No. Every entry carries a category, a timestamp and an importance score, retrieval favours recent and high-importance entries, and the store is kept bounded by prioritisation. Low-value records are not preserved indefinitely — the design treats memory as compressed experience rather than a full log.

**Q7. 怎么保证 LLM 输出可用？出现无效地点或胡编怎么办？**

> Every response passes through the LLM interface, which parses and validates it before anything enters the simulation. Destinations have to resolve to locations that exist in the town; anything invalid is rejected rather than replayed into the state.

**Q8. 反思机制真的改变了行为，还是只是好看？**

> It changes behaviour, and that is one of the things we looked at. Reflections are written back into memory and retrieved during the next planning call, so they are literally an input to the next day's schedule. Where memory influence is limited, we observe weaker adaptation and less consistency over time.

**Q9. 能扩展到几百个智能体吗？**

> Not as it stands. Two bottlenecks: the number of LLM calls, and interaction detection, which grows with co-located pairs. Scaling would need batching and caching of generation, cheaper reflection, and a more efficient interaction index. That is our second future direction.

**Q10. 为什么选 DeepSeek？换成别的模型可以吗？**

> The model sits behind a single interface, so it is swappable — nothing in the framework depends on the provider. We used DeepSeek for its cost-to-capability ratio at the scale we needed. Comparing models is a reasonable experiment we have not run yet.

- 中文补充：这题可以顺手跳到备用页 **B1**（第 13 页），指着 LLM Interface 讲。

**Q11. 人在环反馈会不会让结果不再是「自主涌现」？**

> That is why it is optional and off by default. Baseline operation uses no human input at all — the results I showed come from that setting. The channel exists for cases where you want to steer a scenario, and because feedback enters through the same memory path, its influence is traceable.

**Q12. 这个框架有什么实际应用？**

> Three that we find promising: game NPCs with behaviour that persists across sessions, educational and social-science simulation where you need interpretable individual behaviour, and smart-environment or embodied-agent settings where an agent has to plan a day and remember what happened.

**如果被问到答不上来的问题：**

> That is a very good point — we have not evaluated that yet. My expectation is …, but I would rather check it properly than guess. Could we discuss it after the session?

---

## 六、临场提示

- **语速**：讲稿按 130 词/分钟写，是口语化的书面语——照着念就是自然的语速，不用刻意加快。练习时用手机计时，**第 5 页讲完 4:10、视频 4:50 开始、6:50 结束**——盯住这三个点就不会崩。
- **第 6 页和第 7 页要连成一个动作**：说完 "Let me show you that running." 立刻翻页点播放，中间不要解释；视频停了先停顿一秒再接第 8 页，不要抢。
- **三个必须说清楚的句子**（其他都可临场压缩）：
  1. "deterministic *when*, generative *what*"（第 4 页）
  2. "the model itself is stateless — all the continuity lives in the memory system"（第 5 页）
  3. "what someone said to you yesterday shows up in what you do today"（第 9 页）
- **主席举牌提示时间**：直接跳到第 11 页讲结论 + 局限 + 未来工作三条。
- **设备**：自带 U 盘（含**嵌入了视频的** pptx）+ 一份 PDF 备份（`ICAC2026_Paper108_Valentown.pdf`，PDF 里没有视频，只有那张截图——所以 PDF 只是最后的兜底）。**提前到场试放一次视频**，这是唯一可能出事的环节。
- **字体**：Cambria / Calibri，Windows 和 Office 都自带，不会掉字体。
- **演示者视图**：每页英文讲稿在备注栏里，PowerPoint 里按 `Alt + F5` 可单机预览。
