# ICAC 2026 · Paper 108 — 10 分钟演讲稿

**A Lightweight LLM-Driven Multi-Agent Framework for Virtual Society Simulation with Memory Feedback**
Aoao Guo, Xinyi Tao, Huakang Li, Xuewu Dai

- 时间：2026 年 8 月 27 日（周四）17:35 – 17:50 (BST)
- 场次：Parallel Session 3 — Robotics & Autonomous Systems，会场 N2.10
- 幻灯片：`ICAC2026_Paper108_Valentown.pptx`（14 页，英文讲稿已放进每页备注栏 / Speaker Notes，用演示者视图即可看到）

---

## 一、时间分配

全文约 **1,285 词**。按 125–135 词/分钟计约 **9.5 – 10.3 分钟**。若 15 分钟的时段含问答，这个长度刚好留出 4–5 分钟提问。

| # | 页面 | 内容 | 目标用时 | 累计 |
|---|---|---|---|---|
| 1 | Title | 自我介绍 + 一句话概括 | 0:30 | 0:30 |
| 2 | Motivation | 两条路线各自的短板 | 0:55 | 1:25 |
| 3 | Problem statement | 一个问题、三项要求 | 0:45 | 2:10 |
| 4 | Framework | 后端 / 前端 / 五个模块 | 0:40 | 2:50 |
| 5 | Mechanism 1 & 2 | 日程驱动 + 时空交互 | 0:55 | 3:45 |
| 6 | Mechanism 3 | 记忆反馈闭环（**重点**） | 1:00 | 4:45 |
| 7 | Execution | 一个模拟日的完整流程 | 0:40 | 5:25 |
| 8 | Implementation | Valentown 实际运行截图 | 0:40 | 6:05 |
| 9 | Experiments | 实验设置与关注点 | 0:45 | 6:50 |
| 10 | Result 1 | 交互消融 | 0:50 | 7:40 |
| 11 | Result 2 | 记忆随时间演化 | 0:50 | 8:30 |
| 12 | Discussion | 优势与局限 | 0:45 | 9:15 |
| 13 | Conclusion | 结论 + 未来工作 | 0:50 | 10:05 |
| 14 | Thank you | 致谢，进入提问 | 0:10 | 10:15 |

**超时应急**：文中标 `[可删]` 的句子共约 90 词，全部略过可省下约 45 秒。真的紧张时，优先压缩第 4 页（架构）和第 12 页（讨论）——这两页照着卡片念要点即可。

---

## 二、逐页讲稿

> 英文为要讲的原话；中文为要点提示，不用念。

### 1 · Title

> Good afternoon. I'm Aoao Guo, from University College London, and this is joint work with Xinyi Tao, Huakang Li and Xuewu Dai. We present a lightweight, LLM-driven multi-agent framework for simulating a virtual society, built around a memory feedback loop. Our system is a small town called Valentown, with seven residents who plan their own days, meet each other, remember what happened, and adapt because of it.

- 中文要点：自我介绍 + 合作者 → 一句话说清做了什么（轻量的 LLM 多智能体虚拟社会框架，核心是记忆反馈闭环）→ 点名 Valentown 与七位居民。
- 动作：说到 "Valentown" 时可以用手示意底部那排像素小人，观众立刻会有画面感。

### 2 · Motivation — Two ways to simulate people

> Multi-agent simulation is the standard way to model complex systems: social networks, transport, smart cities. But classical agent-based models run on predefined rules. They capture macro patterns well and human behaviour badly — no context, no planning, no memory.
>
> Large language models changed what an agent can do. An LLM agent produces coherent language, keeps context, and imitates parts of human reasoning.
>
> But something is still missing. Most LLM agent systems are reactive: they answer the prompt in front of them. There is no daily structure, and interaction is ad hoc. So behaviour drifts, the dynamics are hard to control, and results are hard to reproduce. That is the gap we target.

- 中文要点：左卡＝传统 ABM（规则固定、宏观可以、个体不像人）；右卡＝LLM 智能体（会说话、有上下文，但**是反应式的**）；下方黄条＝真正缺的东西：行为、交互、反馈都没有显式结构。
- 讲法：讲到 "That is the gap we target" 时停顿一拍，这是全场的转折点。

### 3 · Problem statement — One question, three requirements

> Our question is: how do we design a virtual society where agents are structured, evolving and controllable at the same time?
>
> That breaks into three requirements, and each one is answered by one mechanism. These are also our three contributions. [可删]
>
> Temporal structure: behaviour has to be organised as a day. Our answer is a schedule-driven agent design.
>
> Evolution: yesterday has to change tomorrow. Our answer is a memory-based feedback loop.
>
> Controllability: interaction must follow an explicit rule, and a human should be able to step in. Our answer is a deterministic co-location trigger, plus optional human-in-the-loop feedback.

- 中文要点：黑框里的问题就是全篇的研究问题；三张卡＝三项要求，每张卡下面绿色小块＝我们的答案，也正好是三个贡献。
- 讲法：三点要讲得干脆、节奏一致（"Temporal structure… Evolution… Controllability…"），这是评委记住你的地方。

### 4 · Framework — A backend that thinks, a frontend that shows

> The framework has two halves. The backend, in Python, is where the agents think: daily planning, dialogue, reflection and memory management. It is the only part that calls the language model — we use the DeepSeek API. The frontend, in Phaser, renders the town and the conversations, and talks to the backend over REST.
>
> Underneath there are five modules — Agent Manager, Scheduler, Interaction Engine, LLM Interface and Memory Manager — and each can be replaced without touching the others. [后半句「and each can be replaced…」可删]

- 中文要点：只需要传达两件事——(1) 认知在后端、展示在前端，唯一调用 LLM 的地方是后端；(2) 五个模块彼此解耦、可替换。
- 讲法：这页不要逐条念图，指一下图说 "as you can see" 就够，节省时间给第 5、6 页。

### 5 · Mechanism 1 & 2 — Plan the day, then let the town decide who meets

> The first two mechanisms.
>
> Schedule-driven behaviour. Instead of asking an agent what to do at every moment, the day starts with an explicit schedule. The prompt combines identity, personality and goals with memories retrieved as context, and the model returns activities and the destinations they imply. That is what makes routines coherent over time, and interpretable for us.
>
> Second, interaction. We do not sample conversations at random. Two agents talk when they are in the same place in the same period — plain co-location. The rule is deterministic, so the social dynamics are reproducible; what gets said is still generated by the model.
>
> That is the design principle of the paper: deterministic when, generative what.

- 中文要点：机制一＝先有日程再有行为（prompt = 身份 + 性格 + 目标 + 检索到的记忆）；机制二＝同时同地才对话，触发是**确定性**的，内容才交给 LLM。
- 讲法：底部黄条那句 "deterministic *when*, generative *what*" 是全场最好记的一句，放慢、加重语气。左卡下面四个小标签只是**示意**的一天，若被问可以说明 "illustrative"。

### 6 · Mechanism 3 — Memory is where the days connect ★重点

> The third mechanism, and the heart of the paper: memory.
>
> Everything an agent produces goes into one store. Plans are kept as behavioural records, conversations as social experience, reflections as summaries. Every entry has a category, a timestamp and an importance score.
>
> And everything reads from that store. Planning retrieves relevant memories, dialogue retrieves recent history, and reflection summarises the important ones into compact insight and writes it back. That is the loop in the figure.
>
> Retrieval favours recent and high-importance entries, and the store stays bounded, so agents keep what mattered. [可删]
>
> Two notes. A person can write feedback directly into memory, through the same channel. And the language model itself is stateless — all continuity lives in the memory system.

- 中文要点：**写入**（计划／对话／反思，带类别、时间戳、重要度）→ **读出**（规划检索、对话检索、反思压缩后写回）→ 图 3 就是这个闭环；再补两点：人可以从同一通道注入反馈；LLM 本身无状态，连续性全在记忆里。
- 讲法：这是评审最可能追问的一页，宁可在这里多花 10 秒。指着图讲 "store in / generate" 两个方向。

### 7 · Execution — One simulation day, end to end

> This is one simulation day in the implemented system.
>
> Agents initialise from their profile and their memory. On day one there is nothing to reflect on, so they plan straight from the profile. On every later day they first retrieve and reflect on memory, and that reflection feeds the planning call.
>
> Then: generate the plan, save it, determine the destination, move there, and if another agent is present, they talk. The conversation goes back into memory. Nine steps, and the loop is closed.

- 中文要点：只强调一个分叉——第一天直接规划，之后先反思再规划；其余步骤用手沿流程图划一遍即可。
- 讲法：不要逐框念，沿着箭头走一遍手势，最后落在 "the loop is closed"。

### 8 · Implementation — Valentown: the framework, running

> Here is the framework running. Valentown: homes along the top, the café, supermarket and pharmacy below, a park on the left. Those locations are the spatial anchors that make co-location, and therefore interaction, possible.
>
> Seven residents live there, each with their own age, role, personality and goals — a case study, not part of the method.
>
> All generation goes through one LLM interface: prompt construction, the call, and validation before anything enters the simulation. Behaviour is pre-computed asynchronously, so the client never stalls waiting for an API call. [末句可删]

- 中文要点：截图是真实运行画面 → 地点＝共处的空间锚点 → 七个居民只是 case study，框架不绑定他们 → 所有生成都经过统一接口并**先校验再入库**。
- 讲法：这页最抓人，可以稍微停一下让观众看图；如果现场有网络也可以说 "the code and a live demo are available"，但不要临场演示，风险太高。

### 9 · Experiments — What we ran, and what we looked for

> For the experiments we instantiate the framework with seven agents: a supermarket owner, a pharmacist, a couple with a seven-year-old, a family teacher and an architect. Their attributes ground everything the model generates. [第二句可删]
>
> The environment is the structured town, with co-location as the interaction condition. We run multiple consecutive virtual days, and each day is a full cycle — schedule, movement, interaction, logging, reflection.
>
> Scheduling is deterministic while the generated content is stochastic: a reproducible pipeline with diverse behaviour inside it. And we ask three questions — what interaction does, what memory does, and whether social structure emerges.

- 中文要点：人群异质（年龄／角色／性格／目标）→ 环境与交互条件 → 多个连续虚拟日、每日完整周期 → 「确定性流程 + 随机内容」的取舍 → 三个评估关注点（正好对应后面两页结果）。

### 10 · Result 1 — Turn interaction off, and the town goes quiet

> The first experiment is an ablation on interaction.
>
> With interaction on, agents produce richer and more varied behaviour. The reason is mechanical: a conversation puts new context into memory, and memory is an input to the next plan. So what someone said to you yesterday shows up in what you do today. We see agents scheduling follow-ups, returning to the same places, and repeated contact reinforcing specific pairs.
>
> With interaction off, the town goes quiet. No new social information enters the system, agents fall back on their initial goals, and schedules stay static across days.
>
> So interaction is not decoration here — it drives diversity and adaptation together.

- 中文要点：开／关交互的对照；解释**为什么**会这样（对话 → 记忆 → 下一次规划的输入），这句因果是本页的关键，不要只念现象。
- 讲法："what someone said to you yesterday shows up in what you do today" 是通俗版解释，用它把机制讲活。

### 11 · Result 2 — Memory changes shape as the days pass

> The second result is about memory over time.
>
> Memory content does not stay the same. Early on it is mostly plans and observations. As the days pass, conversations and reflections become prominent. Later, high-importance interaction and reflection memories form the dominant context for new decisions — the store turns from a log of activity into accumulated experience.
>
> And that content tracks behaviour. Agents with rich interaction and reflection memories adapt more and behave more coherently. Repeated interaction between two agents forms a persistent bond, visible later as repeated co-location. Nobody wrote a friendship rule; it comes out of memory plus retrieval. Where memory influence is limited, adaptation is weaker. [末句可删]

- 中文要点：上排三张卡＝记忆构成随时间迁移（计划／观察 → 对话／反思 → 高重要度记忆主导）；下方＝记忆内容与行为变化相关（持久社交关系、目标导向的任务选择）。
- 讲法："Nobody wrote a friendship rule" 是本页的记忆点，说完稍停。注意措辞是「相关 / 观察到」，不要说成统计显著。

### 12 · Discussion — What this buys us, and what it costs

> Briefly, the trade-offs.
>
> The framework is lightweight and reproducible, because the pipeline and the interaction triggers are explicit. It is controllable, through schedules, the co-location rule and the human channel. [第二句可删] And it is extendable — every module, including the model behind the interface, can be swapped.
>
> The limitations are real. Cost: every plan, conversation and reflection is an API call, and that scales with agents times days. Scale: this is a small study in a simple town. And stochasticity: outputs vary between runs, which is why our current evaluation is qualitative rather than numeric.

- 中文要点：优势三点（轻量可复现 / 可控 / 可扩展），局限三点（成本、规模、随机性）。
- 讲法：**主动讲清局限**。评审最可能问的就是「没有定量指标」，你先说出来，等于把这个问题接了下来，气场完全不同。

### 13 · Conclusion — Where this leaves us

> To conclude. We presented a schedule-driven multi-agent framework in which planning, interaction and reflection are linked through a memory-centred feedback loop. Importance-based memory keeps what mattered, and reflection turns it into insight that guides the next day.
>
> The experiments show that these simple mechanisms are enough: agents develop consistent routines, form lasting relationships and adapt from experience, with no hand-written behavioural rules.
>
> Three directions ahead. Quantitative evaluation is the most important — network analysis, interaction frequency, plan coherence, plus user studies. Then larger populations and real-time reaction. [可删] And finally deeper reasoning, with applications to game NPCs, education and embodied agents.

- 中文要点：结论一句话＝简单的生成式机制足以产生连贯routine、持久关系与经验驱动的适应；未来工作三条，把「定量评估」放在第一位。

### 14 · Thank you

> Thank you very much for your attention. I am happy to take questions.

- 提问阶段把这一页留在屏幕上（有你的邮箱和论文标题）。

---

## 三、问答预案

> 每条先给一句英文回答，后面是中文补充要点。回答控制在 20–40 秒。

**Q1. 和 Stanford 的 Generative Agents（Park et al., 2023）有什么区别？** ——最可能被问到

> Generative Agents is the work we build on, and the difference is structure. First, our behaviour is schedule-first: an agent commits to a day, rather than deciding step by step, which is what keeps long runs temporally coherent. Second, our interaction trigger is deterministic co-location rather than an ad-hoc or sampled encounter, so the social dynamics are controllable and repeatable. Third, the system is deliberately lightweight and modular, and it adds an explicit human-in-the-loop channel into memory.

- 中文补充：措辞上要「站在巨人肩上」，先肯定对方是基础工作，再讲三点差异：日程优先、确定性触发、轻量可复现 + 人在环。

**Q2. 为什么用确定性的共处触发，而不是概率触发？**

> Because we wanted the dynamics to be controllable and reproducible. If encounters are sampled, every run differs for two reasons at once — the sampling and the model — and you cannot attribute a behavioural change to either. With a deterministic trigger, the only stochastic component is the generated content. Adding a probabilistic gate on top is straightforward, and it would be a natural extension.

**Q3. 你们的结果是定性的，有量化指标吗？**

> Not yet, and we say so in the paper. Strict quantitative evaluation is hard when the generator itself is stochastic, so the current results are qualitative and comparative. Quantitative evaluation is our first future direction: social network analysis over the interaction graph, interaction frequency, plan coherence and task completion rates, plus user studies for perceived realism.

- 中文补充：坦诚 + 给出具体计划，比含糊其辞好。第 12 页你已经先说过局限，这里可以说 "as I mentioned"。

**Q4. 一天的 LLM 调用成本大概多少？**

> It scales with agents times days. Per agent per day it is on the order of a few calls: one for the schedule, one for the nightly reflection, plus one per conversation the agent takes part in. That is exactly why cost is listed as a limitation — with larger populations the interaction term is what grows fastest.

- 中文补充：只讲量级和增长项，不要报没测过的具体数字。

**Q5. 记忆会无限膨胀吗？怎么控制？**

> No. Every entry carries a category, a timestamp and an importance score, retrieval favours recent and high-importance entries, and the store is kept bounded by prioritisation. Low-value records are not preserved indefinitely — the design treats memory as compressed experience rather than a full log.

**Q6. 怎么保证 LLM 输出可用？出现无效地点或胡编怎么办？**

> Every response passes through the LLM interface, which parses and validates it before anything enters the simulation. Destinations have to resolve to locations that exist in the town; anything invalid is rejected rather than replayed into the state.

**Q7. 反思机制真的改变了行为，还是只是好看？**

> It changes behaviour, and that is one of the things we looked at. Reflections are written back into memory and retrieved during the next planning call, so they are literally an input to the next day's schedule. Where memory influence is limited, we observe weaker adaptation and less consistency over time.

**Q8. 能扩展到几百个智能体吗？**

> Not as it stands. Two bottlenecks: the number of LLM calls, and interaction detection, which grows with co-located pairs. Scaling would need batching and caching of generation, cheaper reflection, and a more efficient interaction index. That is our second future direction.

**Q9. 是实时的吗？**

> Not currently. Behaviour is pre-computed by the backend and replayed by the client, which is what keeps the visualisation smooth. Real-time decision-making — so agents can react to unexpected events or user intervention as they happen — is explicitly on our roadmap.

**Q10. 为什么选 DeepSeek？换成别的模型可以吗？**

> The model sits behind a single interface, so it is swappable — nothing in the framework depends on the provider. We used DeepSeek for its cost-to-capability ratio at the scale we needed. Comparing models is a reasonable experiment we have not run yet.

**Q11. 人在环反馈会不会让结果不再是「自主涌现」？**

> That is why it is optional and off by default. Baseline operation uses no human input at all — the results I showed come from that setting. The channel exists for cases where you want to steer a scenario, and because feedback enters through the same memory path, its influence is traceable.

**Q12. 这个框架有什么实际应用？**

> Three that we find promising: game NPCs with behaviour that persists across sessions, educational and social-science simulation where you need interpretable individual behaviour, and smart-environment or embodied-agent settings where an agent has to plan a day and remember what happened.

**如果被问到答不上来的问题：**

> That is a very good point — we have not evaluated that yet. My expectation is …, but I would rather check it properly than guess. Could we discuss it after the session?

---

## 四、临场提示

- **语速**：全稿按 125–135 词/分钟写。练习时用手机计时，第 6 页结束应该在 **4:45** 左右，这是最好的中途检查点。
- **开场**：抬头，别看屏幕，第一句话「Good afternoon.」说完再开始换气。
- **三个必须说清楚的句子**（其他都可以临场压缩）：
  1. "deterministic *when*, generative *what*"（第 5 页）
  2. "the language model itself is stateless — all continuity lives in the memory system"（第 6 页）
  3. "what someone said to you yesterday shows up in what you do today"（第 10 页）
- **主席举牌提示时间**：直接跳到第 13 页说结论 + 未来工作三条，不要在讨论页停留。
- **设备**：自带 U 盘 + 一份 PDF 备份（`ICAC2026_Paper108_Valentown.pdf`，已在同目录）。PPTX 里用的是 Cambria / Calibri，Windows 和 Office 上都自带，不会掉字体。
- **演示者视图**：每页英文讲稿已经在备注栏里，PowerPoint 里按 `Alt + F5` 可单机预览演示者视图。
