"""Render SPEAKER_SCRIPT.md from script.json so the deck notes and the
handout can never drift apart."""
import json

WPM = 138
D = json.load(open("/home/user/valentown/docs/thesis-defence/script.json"))

CN_TITLE = {
    1: "开场", 2: "研究动机", 3: "研究缺口与三个问题", 4: "数据", 5: "三种表征",
    6: "十倍时间拉伸", 7: "评估设计", 8: "检测结果 RQ1", 9: "检索结果 RQ2",
    10: "野外应用 RQ3", 11: "蝙蝠 vs 昆虫", 12: "主动交代局限",
    13: "结论与下一步", 14: "收尾",
}


def secs(e):
    return round(sum(len(p.split()) for p in e["say"]) / WPM * 60)


def mmss(t):
    return f"{t // 60}:{t % 60:02d}"


total = sum(secs(e) for e in D)

out = []
out.append("""# 答辩讲稿 · Speaker Script
### Time-Expanded Perch Embeddings for Feeding-Buzz Detection, Retrieval and Field Candidate Discovery
**Candidate WPNS1 · BIOS0057 · MSc Ecology and Data Science, UCL**

> ⚠️ 本文件由 `script.json` 自动生成（`python3 make_script.py`）。要改讲稿请改 `script.json`
> 再重新生成，这样 PPT 备注栏和本文件永远一致。

**配套文件**
- `WPNS1_defence_deck.pptx` — 14 张正式幻灯片 + 5 张备用幻灯片，讲稿已写入每页备注栏（Speaker Notes）
- `WPNS1_defence_deck.pdf` — 放映备份，现场 PowerPoint 出问题可直接用
""")

# ---------------------------------------------------------------- timing
out.append("\n---\n\n## 时间分配 / Timing plan\n")
out.append("| # | Slide | 内容 | 词数 | 时长 |")
out.append("|---|-------|------|------|------|")
for e in D:
    out.append(f"| {e['n']} | {e['title']} | {CN_TITLE[e['n']]} | "
               f"{sum(len(p.split()) for p in e['say'])} | {mmss(secs(e))} |")
out.append(f"| | | **合计** | **{sum(sum(len(p.split()) for p in e['say']) for e in D)}** "
           f"| **{mmss(total)}** |")
WORDS = sum(len(p.split()) for e in D for p in e["say"])
out.append(f"""
> 以 **{WPM} 词/分钟** 计约 **{mmss(total)}**；语速偏慢（130 词/分）时约
> {mmss(round(WORDS / 130 * 60))}。
> 十分钟的场子留出了 30 秒左右的缓冲。
>
> **需要再压到 9 分钟**：按讲稿中标 `[可删]` 的段落删，不要靠加快语速解决。
""")

# ---------------------------------------------------------------- script
out.append("\n---\n\n## 讲稿正文 / Full script\n")
for e in D:
    out.append(f"\n### Slide {e['n']} — {e['title']}  *({mmss(secs(e))})*\n")
    for para in e["say"]:
        out.append(f"> {para}\n")
    if e.get("cut"):
        out.append(f"`[可删]` {e['cut']}\n")
    out.append(f"🇨🇳 *{e['cn']}*\n")
    out.append("---")

out.append("""
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
""")

open("/home/user/valentown/docs/thesis-defence/SPEAKER_SCRIPT.md", "w").write("\n".join(out))
print("SPEAKER_SCRIPT.md regenerated")
