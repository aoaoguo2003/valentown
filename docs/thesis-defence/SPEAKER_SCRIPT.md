# 答辩讲稿 · Speaker Script
### Time-Expanded Perch Embeddings for Feeding-Buzz Detection, Retrieval and Field Candidate Discovery
**Candidate WPNS1 · BIOS0057 · MSc Ecology and Data Science, UCL**

> ⚠️ 本文件由 `script.json` 自动生成（`python3 make_script.py`）。要改讲稿请改 `script.json`
> 再重新生成，这样 PPT 备注栏和本文件永远一致。

**配套文件**
- `WPNS1_defence_deck.pptx` — 14 张正式幻灯片 + 5 张备用幻灯片，讲稿已写入每页备注栏（Speaker Notes）
- `WPNS1_defence_deck.pdf` — 放映备份，现场 PowerPoint 出问题可直接用


---

## 时间分配 / Timing plan

| # | Slide | 内容 | 词数 | 时长 |
|---|-------|------|------|------|
| 1 | Title | 开场 | 55 | 0:24 |
| 2 | Hours of audio, seconds of signal | 研究动机 | 138 | 1:00 |
| 3 | Detectors exist; transfer is untested | 研究缺口与三个问题 | 105 | 0:46 |
| 4 | Curated clips, and continuous field audio | 数据 | 87 | 0:38 |
| 5 | Three representations, one detector | 三种表征 | 87 | 0:38 |
| 6 | Making ultrasound legible to a 32 kHz model | 十倍时间拉伸 | 117 | 0:51 |
| 7 | Three levels of difficulty, plus retrieval | 评估设计 | 90 | 0:39 |
| 8 | Not just better on average — more stable | 检测结果 RQ1 | 104 | 0:45 |
| 9 | The same ranking, without a threshold | 检索结果 RQ2 | 87 | 0:38 |
| 10 | Field candidate discovery in Kenya | 野外应用 RQ3 | 100 | 0:43 |
| 11 | Inside 0.25 s, these look alike | 蝙蝠 vs 昆虫 | 98 | 0:43 |
| 12 | What I would ask about this work | 主动交代局限 | 121 | 0:53 |
| 13 | Representation matters, but is not enough | 结论与下一步 | 113 | 0:49 |
| 14 | Thank you | 收尾 | 8 | 0:03 |
| | | **合计** | **1310** | **9:30** |

> 以 **138 词/分钟** 计约 **9:30**；语速偏慢（130 词/分）时约
> 10:05。
> 十分钟的场子留出了 30 秒左右的缓冲。
>
> **需要再压到 9 分钟**：按讲稿中标 `[可删]` 的段落删，不要靠加快语速解决。


---

## 讲稿正文 / Full script


### Slide 1 — Title  *(0:24)*

> Good morning, and thank you for your time. My dissertation is titled 'Time-Expanded Perch Embeddings for Feeding-Buzz Detection, Retrieval and Field Candidate Discovery.'

> It sits between bat bioacoustics and machine learning, and asks one question: moving a feeding-buzz detector from curated clips to real field recordings, how much does the representation of the sound matter?

🇨🇳 *开场只做一件事：把整篇论文压成一个问题。不要念标题里的每个词，重音放在 representation 上。*

---

### Slide 2 — Hours of audio, seconds of signal  *(1:00)*

> Passive acoustic monitoring is now standard in biodiversity work — recorders sit in the field for weeks with almost no disturbance to the animals. The problem is what comes afterwards: many hours of audio for very few events of interest. In my Kenya subset alone, 9.4 hours became 270,156 analysis windows to score.

> Automated detectors reduce that workload, but a detector never sees the sound — it sees a numerical representation of it, and different feature strategies give different answers on the same recordings.

> Feeding buzzes are a good test case. Behaviourally they matter: in the terminal phase of prey pursuit, call rates can exceed 200 vocalisations per second, so a buzz is evidence of foraging, not just of presence. Acoustically they are hard — brief, ultrasonic at 384 kilohertz, and easily confused with other short pulse trains.

`[可删]` 第二段可删（约 8 秒）

🇨🇳 *这一页把「为什么值得做」和「为什么难做」一次讲完。说 behaviourally / acoustically 时指右边的频谱图，观众会自然跟着看。*

---

### Slide 3 — Detectors exist; transfer is untested  *(0:46)*

> Specialised detectors already exist. Buzzfindr uses hand-crafted pulse timing and signal statistics, developed on Ontario recordings. BatBuddy uses a deep-learning object detector over spectrogram images, trained on Dutch recordings. Both do well on their own held-out data — and both sets of authors note that broader geographic transfer still needs validation.

> So I asked three questions. Representation: does a pretrained Perch v2 representation generalise across held-out recording groups better than simpler spectral statistics? Retrieval: how well do those representations support similarity search, with no threshold fixed? And field transfer: can a detector built on curated clips support candidate discovery in long, noisy, unlabelled field audio?

🇨🇳 *三个 RQ 是整场答辩的骨架 —— 第 8、9、10 页会一一对应回来。念 RQ 时依次点三张卡片。*

---

### Slide 4 — Curated clips, and continuous field audio  *(0:38)*

> Two datasets. The labelled set comes from Buzzfindr: all 158 buzz clips plus 158 non-buzz clips sampled with a fixed seed — 316 balanced files across six folders and five Ontario locations, all 384 kilohertz. Note the highlighted rows: buzzes_sp and buzzes_spmylu are both Site 4. That matters later.

> The field set is a deployment at site MT18 in the Mara Triangle, Kenya — 564 one-minute recordings, 9.4 hours, one AudioMoth. Crucially there is no exhaustive ground truth, and that bounds what I can claim from it.

🇨🇳 *主动埋两个伏笔：Site 4 重复，和 Kenya 没有 ground truth。到第 12 页时考官会觉得「他早就知道」，而不是「被我们抓到了」。*

---

### Slide 5 — Three representations, one detector  *(0:38)*

> I compared three complete pipelines behind one identical detector — standardisation plus L2-regularised logistic regression. Because the classifier is held constant, any difference is attributable to the representation.

> The baseline is 1,543 dimensions: the temporal mean, standard deviation and maximum for each of 513 frequency bins. The compact version asks whether that detail is necessary — 64 bands instead of 513 bins, 199 features. The third is Perch v2: frozen, pretrained on multi-taxa data, no fine-tuning, one 1,536-dimensional embedding per clip. That one needed an input adaptation.

🇨🇳 *强调 one identical detector —— 这是实验设计干净的地方，考官会认可。最后一句自然过渡到下一页。*

---

### Slide 6 — Making ultrasound legible to a 32 kHz model  *(0:51)*

> Perch could not take my audio directly. Its frontend assumes 32 kilohertz, which represents frequencies only up to 16 kilohertz — my bat calls live far above that, and ordinary resampling would simply discard the signal.

> So instead of resampling down to 32k, I resampled 384 to 320 kilohertz and let the 32 kilohertz frontend read those samples as its own. That is an exact tenfold time expansion: 0.25 seconds is heard as 2.5, with frequency shifted down by the same factor. It preserves the relative pulse pattern and moves it into a range Perch can process.

> Only the Perch route carries that conversion — so what follows compares complete pipelines, not embedding architectures under identical preprocessing.

🇨🇳 *全场最技术、也最有自己贡献的一页 —— 语速放慢，四个方块一个一个过。最后一句是主动认领局限，不要省。*

---

### Slide 7 — Three levels of difficulty, plus retrieval  *(0:39)*

> I evaluated at three increasing levels of difficulty. A stratified random split as a conventional benchmark. A grouped-site split, holding out two geographically distinct folders. And six-fold leave-one-folder-out, refitting the scaler and detector inside every round.

> For retrieval, all 158 buzz clips were queries, the query's own folder was excluded, and candidates were ranked by cosine similarity against a seeded random baseline.

> One caveat I'll state up front rather than be asked about: buzzes_sp and buzzes_spmylu are both Site 4. So these are folder-level robustness results, not strict five-location isolation.

`[可删]` 第二段可缩为一句（约 6 秒）

🇨🇳 *「rather than be asked about」这句很关键 —— 它把弱点转成严谨性的证据。语气要平稳自信，不要像在道歉。*

---

### Slide 8 — Not just better on average — more stable  *(0:45)*

> The grouped-site test turned out to be easy — all three reached an F1 of 1.0, so that test did not discriminate between them.

> Leave-one-folder-out is where they separate. Mean F1 was 0.872 for the baseline, 0.870 for compact, 0.989 for Perch. But the more informative number is the worst folder — the amber bars: 0.727, 0.691, and 0.950. Standard deviation across rounds was 0.020 for Perch, against roughly 0.10 for both spectral pipelines. Perch is not just better on average; it is far more stable when the held-out data changes.

> And compact matched baseline to within 0.002 F1 using one-eighth of the dimensions.

🇨🇳 *这一页的论点不是「Perch 分数高」，而是「Perch 方差小」。一定要把 worst-folder 和 SD 讲出来 —— 这才是 generalisation 的证据。*

---

### Slide 9 — The same ranking, without a threshold  *(0:38)*

> Retrieval shows the same ranking without fixing any threshold. Macro-averaged Precision at 10 was 0.831, 0.830, and 0.984 for Perch — against a random floor of 0.500.

> Perch's average precision over the full list was 0.879 — lower than its own top-k precision, so its separation is concentrated near the top of the ranking. For a review workflow, where the annotator inspects the highest-ranked candidates first, that is the right shape.

> The balanced pool does make this easier than real field data, where buzzes are far rarer.

🇨🇳 *AP 低于 P@10 听起来像缺点，但你把它解释成「正好适合人工复审」，这是加分的解读。*

---

### Slide 10 — Field candidate discovery in Kenya  *(0:43)*

> Then the honest test: 564 unlabelled recordings, 270,156 windows, both detectors applied. Perch was the more conservative — 2.14% of windows above 0.95, against 4.43% for the baseline. Different score scales, so this compares how they prioritised the recordings, not their precision.

> I then manually reviewed 69 candidates, each from a different one-minute recording, using the 0.25-second window, 1.25 seconds of context, pulse timing and time-expanded audio. Nineteen — 27.5% — were buzz-like. But the largest category, 27 candidates or 39.1%, was insect-like pulse trains.

> These were selected by Perch score, so those proportions describe the reviewed set, not prevalence.

🇨🇳 *「the honest test」让考官意识到你清楚 curated 和 field 的差别。最后一句是关键的方法论自觉。*

---

### Slide 11 — Inside 0.25 s, these look alike  *(0:43)*

> This is the key field finding. Inside a 0.25-second window, a feeding buzz and an insect pulse train can both look like dense repeated pulses — which is why so many scored highly.

> It is the surrounding second that separates them. Insect sequences are regular and continue far longer; buzz-like sequences are shorter, change faster, and stop. That points at a design change: wider contextual windows, or a second-stage model that examines the temporal neighbourhood around a high-scoring window.

> And the 27 insect-like candidates are not a waste — they are ready-made hard negatives for an active-learning cycle.

🇨🇳 *全场最有说服力的一页，因为它把一个「错误」变成了一个「设计洞察」。指着左右两张图说 compress and stop 对 metronomic and persistent。*

---

### Slide 12 — What I would ask about this work  *(0:53)*

> I would rather flag the limitations myself than defend them.

> First, the Site 4 folder pairing — my LOFO and retrieval numbers may be optimistic relative to a strict five-location rerun. The grouped-site test does remain geographically isolated.

> Second, a duration confound. At a 0.5-second window, class label aligned perfectly with padded-versus-cropped — an obvious shortcut. I chose 0.25 seconds to weaken it, but 127 buzz clips were still padded, and Perch should not be assumed immune just because its features are pretrained.

> Third, only the Perch route carries the resampling, so I compare pipelines rather than isolating the embedding. And fourth, Kenya has no ground truth, so those review proportions are descriptive — I cannot report event-level precision or recall.

`[可删]` 第四段的「Third」一句可删（约 8 秒）

🇨🇳 *主动认领局限是英国答辩最吃香的一招。四点讲得快、清楚、不带情绪 —— 语气是「我已经想过了」，不是「对不起」。*

---

### Slide 13 — Representation matters, but is not enough  *(0:49)*

> To conclude. On RQ1, after tenfold time expansion, frozen Perch embeddings gave the strongest and most stable folder-held-out detection — mean F1 0.989, standard deviation 0.020. On RQ2, the same ordering in retrieval, Precision at 10 of 0.984. On RQ3, in the field, representation choice is necessary but not sufficient — temporal context and human review still do essential work.

> A secondary result worth keeping: 199 compact dimensions matched 1,543 baseline dimensions almost exactly. More hand-crafted features are not automatically better.

> The most useful next step is an independently sampled, exhaustively reviewed Kenya subset — event-level precision and recall, both detectors on the same confirmed events, and those insect-like candidates as hard negatives.

🇨🇳 *结论页严格按 RQ1 / RQ2 / RQ3 回答，让考官在脑中打勾。最后落在 next step 上，主动把话题引向你准备好的方向。*

---

### Slide 14 — Thank you  *(0:03)*

> Thank you — I'm happy to take questions.

🇨🇳 *说完停住，不要加「就这些了」之类的填充语。*

---

## 备用幻灯片 / Backup slides

放在正式结尾之后。答问时按 <kbd>PgDn</kbd>，或直接输入页码 + <kbd>Enter</kbd> 跳转。

| 页 | 内容 | 什么时候用 |
|----|------|-----------|
| **B1** (15) | 检测全套指标：random / grouped / LOFO、accuracy、precision、recall、ROC-AUC、AP、各 folder 数值、三种 split 的划分 | 问「还有别的指标吗」「每个 folder 具体多少」 |
| **B2** (16) | Retrieval 全套指标 + 检索流程细节 + 随机基线构造 | 问 retrieval 怎么做的、随机基线怎么来的 |
| **B3** (17) | 预处理敏感性：窗长 0.10–0.50 s、频谱分辨率、裁剪位置 | 问「为什么选 0.25 s」—— **最可能被问到的一页** |
| **B4** (18) | Kenya 阈值表、覆盖文件数、时间分布（23:00 EAT 峰值）、候选筛选与复审流程 | 问 Kenya 的时间模式，或 69 个候选怎么选出来的 |
| **B5** (19) | 实现细节：软件版本、超参数、滑窗方案 | 问可复现性 / 具体参数 |

---

## 预判问题与回答 / Anticipated questions

**Q1. 为什么用 0.25 秒的窗？0.5 秒的 F1 明明更高。** → 跳 B3
> Because 0.5 seconds is exactly where the shortcut is total: all 158 buzz clips required padding and all 158 non-buzz clips were cropped, so the class label was perfectly predictable from the padding decision alone. The 0.994 F1 there is measuring that shortcut, not the acoustics. At 0.25 s the association is weaker — 127 buzz clips padded, 189 clips cropped — so I took it as the compromise between a short analysis window and a less extreme confound. I report both, and I'd treat a duration-matched benchmark as the proper fix.

**Q2. 十倍拉伸是怎么定的？试过别的倍数吗？**
> Tenfold was chosen because it is exact — 320 kHz read at 32 kHz — and because tenfold expansion already has precedent in bat acoustic datasets. I did not sweep the expansion factor, and I flag it in the dissertation as one of the two changes most likely to affect field performance, alongside the amount of temporal context. It is the first thing I would test next.

**Q3. Perch 的优势会不会只是因为它多了那一步预处理？**
> That is exactly the confound I state on the methods slide, and I cannot rule it out from this design — I compared complete pipelines, not embedding architectures under identical preprocessing. What I can say is that the advantage appears in two independent ways: in threshold-based detection, and in threshold-free retrieval, where no classifier is fitted at all. A duration-matched or duration-only benchmark would separate the representation effect from the preprocessing effect.

**Q4. 六折 LOFO 不是真正的 leave-one-site-out，为什么不重做？**
> Correct, and I say so explicitly rather than presenting it as five-site validation. buzzes_sp and buzzes_spmylu are both Site 4, so those two rounds leave the same location in training. The grouped-site test on buzzes_tb *is* geographically isolated — and all three representations reached F1 = 1.000 there, so that test doesn't discriminate. A strict five-location rerun is a small change to the grouping code and is the first item in my future work.

**Q5. Kenya 那 27.5% 的 buzz-like，说明检测器精度是 27.5% 吗？**
> No — and I'd resist that reading. Those 69 candidates were selected *by Perch score*, through two deliberately different routes: the top-50 windows, and a stratified sample across four score bands. So the proportions describe the reviewed set. Precision would need an independently sampled, exhaustively annotated subset, which is precisely what I propose as the next step.

**Q6. 为什么冻结 Perch 而不微调？**
> Two reasons. Practically, 316 labelled clips is a very small dataset to fine-tune a large pretrained model on without overfitting. Methodologically, Perch 2.0 was designed to be used frozen with a linear probe and for similarity search — that is its intended use case, and it keeps the representation comparison clean, because the classifier is identical across all three pipelines.

**Q7. 为什么用 logistic regression 而不是更强的模型？**
> Because the question is about the representation, not the classifier. A linear model on fixed features is the standard linear-probe protocol. If I had used gradient boosting or an MLP, any difference could be the classifier exploiting the features differently — holding it fixed is what lets me attribute the difference to the representation.

**Q8. Compact 只比 baseline 差 0.002，那你为什么还推荐 Perch？**
> The compact result is a statement about the *baseline family*: within hand-crafted spectral statistics, more frequency detail added nothing on these clips. That is a useful negative result on its own. Perch is a different claim — it is much more stable across held-out folders (SD 0.020 vs ~0.10) and much better at retrieval (P@10 0.984 vs 0.83). If someone needed a lightweight, fully transparent pipeline, compact would be a reasonable choice; if they need robustness across sites, Perch is the better bet on this evidence.

**Q9. 这套方法能推广到别的物种或别的声音吗？**
> The time-expansion trick generalises to any ultrasonic signal a low-sample-rate frontend cannot otherwise see — other bat call types, and in principle ultrasonic insect or rodent vocalisations. What would *not* transfer automatically is the detector itself: everything here is trained on Ontario buzzes, and the Kenya results show how quickly acoustically similar non-target sounds appear in a new environment.

**Q10. 实际部署时你会怎么用这套东西？**
> As a triage layer, not an oracle. Perch scores rank the windows, similarity retrieval expands from a handful of confirmed examples, and a human reviews the top of the list with at least a second of surrounding context. The insect-like detections then feed back as hard negatives. That is the agile-modelling loop, and my results support the retrieval step specifically — high precision exactly where the reviewer looks.

---

## 现场提示 / Delivery notes

1. **不要念稿。** 每页记住 2–3 个「锚点」就够了：第 8 页锚在 *0.950 / 0.020*，第 10 页锚在 *19 vs 27*，第 6 页锚在 *384 → 320 → ×10*。
2. **数字要慢。** F1 = 0.989 这类数字放慢一拍念，其余句子正常速度。
3. **主动交代局限。** 第 6、7、10、12 页都有主动认领的句子 —— 这些是拿分点，不要因为紧张跳过。
4. **过渡句。** 每页结束时用一句话带到下一页（讲稿里已内置，例如第 5 页结尾的 "That one needed an input adaptation"）。
5. **提问环节。** 听完整个问题再答。不确定时说 "That's not something I tested — what I *can* say is…"，然后给出你确实做过的部分。
6. **计时演练。** 完整计时排练三次。超过 10 分 15 秒，就按 `[可删]` 删段落。
