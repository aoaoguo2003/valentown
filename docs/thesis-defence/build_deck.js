const pptxgen = require("pptxgenjs");
const path = require("path");
const SCRIPT = require("./script.json");

const B = path.join(__dirname, "build");
const OUT = path.join(__dirname, "WPNS1_defence_deck.pptx");

/* ---------------------------------------------------------------- palette */
const INK   = "0E1B33";   // night navy  – dominant
const INK2  = "17294A";   // raised card on dark
const TEAL  = "2A9D8F";   // spectrogram teal
const TEALD = "1E7A70";   // teal, readable on white
const AMBER = "F2A541";   // buzz energy – accent
const AMBRD = "B9761E";   // amber, readable on white
const CORAL = "E76F51";   // caveats / the confounder
const WHITE = "FFFFFF";
const SURF  = "F2F5F9";
const SURF2 = "E7EDF4";
const BODY  = "22314D";
const MUTED = "5F718C";
const LINE  = "D5DEEA";

const HEAD = "Cambria";
const SANS = "Calibri";

const W = 13.333, H = 7.5, M = 0.62, CW = W - 2 * M;

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE";
pres.author = "Candidate WPNS1";
pres.title  = "Time-Expanded Perch Embeddings for Feeding-Buzz Detection";

const WPM = 138;
function notes(n) {
  const e = SCRIPT.find((x) => x.n === n);
  const words = e.say.reduce((a, p) => a + p.split(/\s+/).length, 0);
  const secs = Math.round((words / WPM) * 60);
  return e.say.join("\n\n") + `\n\n[~${secs} s]` + (e.cut ? `  可删: ${e.cut}` : "");
}

const sh = () => ({ type: "outer", color: "0E1B33", blur: 10, offset: 2, angle: 90, opacity: 0.10 });

/* --------------------------------------------------------------- helpers */
function newSlide(dark) {
  const s = pres.addSlide();
  s.background = { color: dark ? INK : WHITE };
  return s;
}

function head(s, kicker, title, o = {}) {
  s.addText(kicker.toUpperCase(), {
    x: M, y: 0.36, w: CW, h: 0.26, fontFace: SANS, fontSize: 11, bold: true,
    charSpacing: 2.4, color: o.dark ? TEAL : TEALD, isTextBox: true, margin: 0,
  });
  s.addText(title, {
    x: M, y: 0.66, w: o.tw || CW, h: 0.92, fontFace: HEAD, fontSize: o.size || 30,
    bold: true, color: o.dark ? WHITE : INK, isTextBox: true, margin: 0, valign: "top",
  });
}

function foot(s, n, label, dark) {
  const c = dark ? "6E819F" : MUTED;
  s.addText(label, { x: M, y: 6.94, w: 9.5, h: 0.3, fontFace: SANS, fontSize: 9.5,
    color: c, isTextBox: true, margin: 0 });
  s.addText(String(n), { x: W - M - 1.2, y: 6.94, w: 1.2, h: 0.3, fontFace: SANS,
    fontSize: 9.5, color: c, align: "right", isTextBox: true, margin: 0 });
}

function card(s, x, y, w, h, o = {}) {
  s.addShape(pres.ShapeType.roundRect, {
    x, y, w, h, rectRadius: 0.07,
    fill: { color: o.fill || SURF },
    line: o.line === null ? { type: "none" } : { color: o.line || LINE, width: 0.75 },
    shadow: o.shadow ? sh() : undefined,
  });
}

function numDot(s, x, y, n, o = {}) {
  s.addShape(pres.ShapeType.ellipse, { x, y, w: 0.42, h: 0.42,
    fill: { color: o.fill || TEALD }, line: { type: "none" } });
  s.addText(String(n), { x, y, w: 0.42, h: 0.42, fontFace: SANS, fontSize: 14,
    bold: true, color: WHITE, align: "center", valign: "middle", isTextBox: true, margin: 0 });
}

function bullets(s, items, o) {
  s.addText(items.map((t, i) => ({
    text: t, options: { bullet: true, breakLine: i !== items.length - 1 },
  })), Object.assign({ fontFace: SANS, fontSize: 14, color: BODY, isTextBox: true,
    valign: "top", paraSpaceAfter: 7, lineSpacing: 20 }, o));
}

const chartFrame = {
  showLegend: true, legendPos: "t", legendFontFace: SANS, legendFontSize: 11,
  legendColor: BODY,
  catAxisLabelFontFace: SANS, catAxisLabelFontSize: 11, catAxisLabelColor: BODY,
  valAxisLabelFontFace: SANS, valAxisLabelFontSize: 10, valAxisLabelColor: MUTED,
  catGridLine: { style: "none" },
  valGridLine: { color: SURF2, size: 1 },
  catAxisLineShow: false, valAxisLineShow: false,
  showValue: true, dataLabelFontFace: SANS, dataLabelFontSize: 10,
  dataLabelColor: BODY, dataLabelPosition: "outEnd",
  barGapWidthPct: 55,
};

/* =======================================================================
   1 — TITLE
   ===================================================================== */
{
  const s = newSlide(true);
  s.addImage({ path: `${B}/spec_strip.png`, x: 0, y: 4.30, w: W, h: 1.45 });

  s.addText("MSc Ecology and Data Science  ·  Dissertation defence", {
    x: 0.9, y: 1.18, w: 11.5, h: 0.3, fontFace: SANS, fontSize: 13, bold: true,
    charSpacing: 1.4, color: AMBER, isTextBox: true, margin: 0 });

  s.addText("Time-Expanded Perch Embeddings for\nFeeding-Buzz Detection, Retrieval\nand Field Candidate Discovery", {
    x: 0.9, y: 1.62, w: 11.5, h: 2.3, fontFace: HEAD, fontSize: 38, bold: true,
    color: WHITE, lineSpacing: 44, isTextBox: true, margin: 0 });

  s.addText([
    { text: "Candidate WPNS1", options: { bold: true, color: WHITE, breakLine: true } },
    { text: "Supervisors: Santiago Martinez Balvanera · Kate Jones", options: { breakLine: true } },
    { text: "BIOS0057 · University College London · 2025–2026", options: {} },
  ], { x: 0.9, y: 6.02, w: 8.0, h: 1.0, fontFace: SANS, fontSize: 12.5,
       color: "AFC0D8", lineSpacing: 19, isTextBox: true, margin: 0 });

  s.addNotes(notes(1));
}

/* =======================================================================
   2 — MOTIVATION
   ===================================================================== */
{
  const s = newSlide();
  head(s, "Motivation", "Hours of audio, seconds of signal");

  const stats = [
    ["9.4 h", "of Kenya field audio analysed"],
    ["270,156", "0.25 s windows to be scored"],
    ["> 200 / s", "call rate inside a terminal buzz"],
  ];
  const cw = (CW - 2 * 0.36) / 3;
  stats.forEach(([big, lab], i) => {
    const x = M + i * (cw + 0.36);
    card(s, x, 1.68, cw, 1.42, { fill: i === 2 ? INK : SURF, line: i === 2 ? INK : LINE });
    s.addText(big, { x: x + 0.22, y: 1.80, w: cw - 0.44, h: 0.72, fontFace: HEAD,
      fontSize: 36, bold: true, color: i === 2 ? AMBER : TEALD, isTextBox: true, margin: 0 });
    s.addText(lab, { x: x + 0.22, y: 2.50, w: cw - 0.44, h: 0.48, fontFace: SANS,
      fontSize: 12, color: i === 2 ? "C3D2E8" : MUTED, isTextBox: true, margin: 0 });
  });

  s.addText("The recording scales. The analysis does not.", {
    x: M, y: 3.30, w: 6.4, h: 0.34, fontFace: SANS, fontSize: 15, bold: true,
    color: INK, isTextBox: true, margin: 0 });
  bullets(s, [
    "Recorders sit in the field for weeks with almost no disturbance to the animals.",
    "A survey returns many hours of audio for very few events of interest.",
    "Automated detectors cut that workload — but a detector only ever sees a numerical representation of the sound, and different feature strategies give different answers on the same recordings.",
  ], { x: M, y: 3.80, w: 6.4, h: 2.2, fontSize: 13.5 });

  s.addImage({ path: `${B}/spec_buzz.png`, x: 7.30, y: 3.34, w: 5.41, h: 1.55 });
  s.addText("A feeding buzz: search-phase calls compress into a terminal buzz, then stop. Brief, ultrasonic (recorded at 384 kHz), and evidence of foraging — not just of presence.", {
    x: 7.30, y: 5.00, w: 5.41, h: 0.9, fontFace: SANS, fontSize: 11.5, italic: true,
    color: MUTED, isTextBox: true, margin: 0 });

  foot(s, 2, "Motivation");
  s.addNotes(notes(2));
}

/* =======================================================================
   3 — GAP + RESEARCH QUESTIONS
   ===================================================================== */
{
  const s = newSlide();
  head(s, "The gap", "Detectors exist; transfer is untested");

  card(s, M, 1.62, CW, 1.38, { fill: SURF });
  s.addText([
    { text: "Buzzfindr", options: { bold: true, color: INK } },
    { text: "  hand-crafted pulse timing + signal statistics, developed on Ontario recordings.   ", options: { color: BODY } },
    { text: "BatBuddy", options: { bold: true, color: INK } },
    { text: "  a deep-learning object detector over spectrogram images, trained on Dutch recordings.", options: { color: BODY } },
  ], { x: M + 0.28, y: 1.76, w: CW - 0.56, h: 0.58, fontFace: SANS, fontSize: 13.5,
       isTextBox: true, margin: 0, valign: "top", lineSpacing: 19 });
  s.addText("Both perform well on their own held-out data — and both sets of authors note that broader geographic transfer still needs validation. Overall accuracy can hide large site-to-site differences.", {
    x: M + 0.28, y: 2.40, w: CW - 0.56, h: 0.50, fontFace: SANS, fontSize: 12.5,
    italic: true, color: MUTED, isTextBox: true, margin: 0, valign: "top" });

  const rq = [
    ["Representation", "Does a pretrained Perch v2 representation generalise across held-out recording groups better than simpler spectral statistics?"],
    ["Retrieval", "How effectively do those representations support held-out-folder retrieval of feeding buzzes from a labelled query?"],
    ["Field transfer", "Can a detector built on curated clips support candidate discovery in long, noisy, unlabelled field recordings?"],
  ];
  const cw = (CW - 2 * 0.36) / 3;
  rq.forEach(([t, q], i) => {
    const x = M + i * (cw + 0.36);
    card(s, x, 3.22, cw, 2.86, { fill: WHITE, line: LINE, shadow: true });
    numDot(s, x + 0.28, 3.46, i + 1);
    s.addText(`RQ${i + 1} · ${t}`, { x: x + 0.28, y: 4.02, w: cw - 0.56, h: 0.34,
      fontFace: SANS, fontSize: 13, bold: true, charSpacing: 0.6, color: TEALD,
      isTextBox: true, margin: 0 });
    s.addText(q, { x: x + 0.28, y: 4.40, w: cw - 0.56, h: 1.50, fontFace: SANS,
      fontSize: 13.5, color: BODY, lineSpacing: 19, isTextBox: true, margin: 0, valign: "top" });
  });

  foot(s, 3, "The gap and the research questions");
  s.addNotes(notes(3));
}

/* =======================================================================
   4 — DATA
   ===================================================================== */
{
  const s = newSlide();
  head(s, "Data", "Curated clips, and continuous field audio");

  const lw = 6.30, rw = CW - lw - 0.42, rx = M + lw + 0.42;

  card(s, M, 1.62, lw, 4.55, { fill: WHITE, line: LINE, shadow: true });
  s.addText("Labelled — Buzzfindr (Ontario, Canada)", { x: M + 0.26, y: 1.80, w: lw - 0.52,
    h: 0.32, fontFace: SANS, fontSize: 14, bold: true, color: INK, isTextBox: true, margin: 0 });
  s.addText("All 158 buzz clips + 158 non-buzz clips sampled at random (seed 42) = 316 balanced files. Mono, 16-bit, 384 kHz.", {
    x: M + 0.26, y: 2.14, w: lw - 0.52, h: 0.5, fontFace: SANS, fontSize: 12,
    color: MUTED, isTextBox: true, margin: 0 });

  const th = { fontFace: SANS, fontSize: 11, bold: true, color: WHITE, fill: { color: INK } };
  const td = { fontFace: SANS, fontSize: 11, color: BODY };
  const rows = [
    [{ text: "Folder", options: th }, { text: "Buzz", options: th }, { text: "Non-buzz", options: th }, { text: "Total", options: th }, { text: "Location", options: th }],
    ...[["buzzes_o", 21, 23, 44, "Site 3"], ["buzzes_rr", 16, 25, 41, "Site 1"],
        ["buzzes_sp", 29, 34, 63, "Site 4"], ["buzzes_spmylu", 32, 26, 58, "Site 4"],
        ["buzzes_tb", 21, 22, 43, "Site 2"], ["buzzes_u", 39, 28, 67, "Site 5"]]
      .map((r, i) => r.map((c, j) => ({
        text: String(c),
        options: Object.assign({}, td, {
          fill: { color: i % 2 ? SURF : WHITE },
          bold: (j === 4 && (c === "Site 4")),
          color: (j === 4 && c === "Site 4") ? AMBRD : BODY,
        }),
      }))),
    [["Total", 158, 158, 316, "5 sites"]].flat().map((c) => ({
      text: String(c), options: Object.assign({}, td, { bold: true, fill: { color: SURF2 } }) })),
  ];
  s.addTable(rows, { x: M + 0.26, y: 2.70, w: lw - 0.52, colW: [1.86, 0.85, 1.15, 0.85, 1.07],
    rowH: 0.27, align: "left", valign: "middle", border: { type: "none" }, margin: 5 });

  s.addText("buzzes_sp and buzzes_spmylu are both Site 4 — six folders, five geographic locations.", {
    x: M + 0.26, y: 5.62, w: lw - 0.52, h: 0.42, fontFace: SANS, fontSize: 11.5,
    italic: true, color: AMBRD, isTextBox: true, margin: 0 });

  card(s, rx, 1.62, rw, 4.55, { fill: INK, line: INK });
  s.addText("Field — Mara Triangle, Kenya", { x: rx + 0.26, y: 1.80, w: rw - 0.52, h: 0.32,
    fontFace: SANS, fontSize: 14, bold: true, color: WHITE, isTextBox: true, margin: 0 });
  const facts = [
    ["Site MT18", "19 Oct – 8 Nov 2019 deployment"],
    ["564 recordings", "one minute each — 9.4 h analysed"],
    ["1 AudioMoth", "full-spectrum logger, 384 kHz, gain 1"],
    ["18:00–23:00 & 00:00–05:00", "EAT coverage — not a full 24-h cycle"],
  ];
  facts.forEach(([a, b], i) => {
    const y = 2.30 + i * 0.86;
    s.addShape(pres.ShapeType.ellipse, { x: rx + 0.28, y: y + 0.10, w: 0.13, h: 0.13,
      fill: { color: TEAL }, line: { type: "none" } });
    s.addText(a, { x: rx + 0.58, y, w: rw - 0.86, h: 0.32, fontFace: SANS, fontSize: 13.5,
      bold: true, color: WHITE, isTextBox: true, margin: 0 });
    s.addText(b, { x: rx + 0.58, y: y + 0.31, w: rw - 0.86, h: 0.34, fontFace: SANS,
      fontSize: 12, color: "B3C4DC", isTextBox: true, margin: 0 });
  });
  s.addText("No exhaustive ground truth — which bounds every claim I make from this dataset.", {
    x: rx + 0.28, y: 5.66, w: rw - 0.56, h: 0.4, fontFace: SANS, fontSize: 11.5,
    italic: true, color: AMBER, isTextBox: true, margin: 0 });

  foot(s, 4, "Datasets");
  s.addNotes(notes(4));
}

/* =======================================================================
   5 — THREE REPRESENTATIONS
   ===================================================================== */
{
  const s = newSlide();
  head(s, "Method · RQ1", "Three representations, one detector");

  card(s, M, 1.62, CW, 0.78, { fill: SURF });
  s.addText([
    { text: "Held constant:  ", options: { bold: true, color: INK } },
    { text: "StandardScaler fitted on training data only → L2-regularised logistic regression (C = 1.0, lbfgs, balanced class weights, threshold 0.5). Any difference in performance is attributable to the representation, not the classifier.", options: { color: BODY } },
  ], { x: M + 0.28, y: 1.76, w: CW - 0.56, h: 0.56, fontFace: SANS, fontSize: 13,
       isTextBox: true, margin: 0, valign: "top", lineSpacing: 18 });

  const reps = [
    { n: "Baseline", d: "1,543", t: "spectral statistics",
      pts: ["Temporal mean, SD and maximum for each of 513 frequency bins", "Plus 4 global spectrogram statistics", "Fine frequency detail, fully transparent"], hl: false },
    { n: "Compact", d: "199", t: "spectral statistics",
      pts: ["513 bins collapsed into 64 contiguous frequency bands", "Mean, SD, max per band + 7 global statistics", "Tests whether the extra detail is doing any work"], hl: false },
    { n: "Perch v2", d: "1,536", t: "pretrained embedding",
      pts: ["Frozen perch_v2_cpu, no fine-tuning", "Multi-taxa pretraining, built for transfer and similarity search", "Requires an input adaptation — next slide"], hl: true },
  ];
  const cw = (CW - 2 * 0.36) / 3;
  reps.forEach((r, i) => {
    const x = M + i * (cw + 0.36);
    card(s, x, 2.62, cw, 3.66, { fill: r.hl ? INK : WHITE, line: r.hl ? INK : LINE, shadow: !r.hl });
    s.addText(r.n, { x: x + 0.28, y: 2.80, w: cw - 0.56, h: 0.34, fontFace: SANS,
      fontSize: 14, bold: true, color: r.hl ? AMBER : TEALD, isTextBox: true, margin: 0 });
    s.addText(r.d, { x: x + 0.28, y: 3.12, w: cw - 0.56, h: 0.72, fontFace: HEAD,
      fontSize: 40, bold: true, color: r.hl ? WHITE : INK, isTextBox: true, margin: 0 });
    s.addText(`dimensions · ${r.t}`, { x: x + 0.28, y: 3.84, w: cw - 0.56, h: 0.3,
      fontFace: SANS, fontSize: 11.5, color: r.hl ? "B3C4DC" : MUTED, isTextBox: true, margin: 0 });
    bullets(s, r.pts, { x: x + 0.28, y: 4.22, w: cw - 0.56, h: 1.92, fontSize: 12.5,
      color: r.hl ? "DCE5F1" : BODY, lineSpacing: 17 });
  });

  foot(s, 5, "Acoustic representations");
  s.addNotes(notes(5));
}

/* =======================================================================
   6 — TIME EXPANSION
   ===================================================================== */
{
  const s = newSlide();
  head(s, "Method · the key adaptation", "Making ultrasound legible to a 32 kHz model");

  const steps = [
    ["Source", "384 kHz", "Bat calls sit far above the 16 kHz ceiling of a 32 kHz frontend."],
    ["Resample", "320 kHz", "Unpadded waveform resampled, then cropped or padded to 0.25 s = 80,000 samples."],
    ["Frontend reads", "32 kHz", "Perch interprets those samples at its own assumed rate."],
    ["Result", "×10", "0.25 s is heard as 2.5 s; apparent frequency shifts down tenfold."],
  ];
  const bw = 2.60, gap = (CW - 4 * bw) / 3;
  steps.forEach(([k, v, d], i) => {
    const x = M + i * (bw + gap);
    const last = i === 3;
    card(s, x, 1.90, bw, 2.14, { fill: last ? INK : WHITE, line: last ? INK : LINE, shadow: !last });
    s.addText(k.toUpperCase(), { x: x + 0.18, y: 2.12, w: bw - 0.36, h: 0.26, fontFace: SANS,
      fontSize: 10.5, bold: true, charSpacing: 1.8, color: last ? AMBER : TEALD,
      align: "center", isTextBox: true, margin: 0 });
    s.addText(v, { x: x + 0.18, y: 2.42, w: bw - 0.36, h: 0.56, fontFace: HEAD,
      fontSize: 26, bold: true, color: last ? WHITE : INK, align: "center",
      valign: "top", isTextBox: true, margin: 0 });
    s.addText(d, { x: x + 0.18, y: 3.02, w: bw - 0.36, h: 0.92, fontFace: SANS,
      fontSize: 12, color: last ? "C3D2E8" : MUTED, align: "center", lineSpacing: 16,
      valign: "top", isTextBox: true, margin: 0 });
    if (!last) {
      s.addShape(pres.ShapeType.rightArrow, { x: x + bw + gap * 0.30, y: 2.84,
        w: gap * 0.40, h: 0.26, fill: { color: TEAL }, line: { type: "none" } });
    }
  });

  card(s, M, 4.34, 6.30, 1.94, { fill: SURF });
  s.addText("Why not simply resample to 32 kHz?", { x: M + 0.28, y: 4.54, w: 5.74, h: 0.34,
    fontFace: SANS, fontSize: 14, bold: true, color: INK, isTextBox: true, margin: 0 });
  s.addText("A 32 kHz frontend represents frequencies only up to 16 kHz. Ordinary resampling would discard everything above that — which is the entire signal. Time expansion preserves the relative pulse pattern and moves it into a range the model can process.", {
    x: M + 0.28, y: 4.94, w: 5.74, h: 1.20, fontFace: SANS, fontSize: 13, color: BODY,
    lineSpacing: 18, valign: "top", isTextBox: true, margin: 0 });

  card(s, M + 6.72, 4.34, CW - 6.72, 1.94, { fill: WHITE, line: CORAL });
  s.addText("Stated as a limitation, not a footnote", { x: M + 7.00, y: 4.54, w: CW - 7.28,
    h: 0.34, fontFace: SANS, fontSize: 14, bold: true, color: CORAL, isTextBox: true, margin: 0 });
  s.addText("Only the Perch route carries this conversion and expansion. What follows therefore compares complete representation pipelines — not embedding architectures under identical preprocessing.", {
    x: M + 7.00, y: 4.94, w: CW - 7.28, h: 1.20, fontFace: SANS, fontSize: 13, color: BODY,
    lineSpacing: 18, valign: "top", isTextBox: true, margin: 0 });

  foot(s, 6, "Tenfold time expansion");
  s.addNotes(notes(6));
}

/* =======================================================================
   7 — EVALUATION DESIGN
   ===================================================================== */
{
  const s = newSlide();
  head(s, "Method · evaluation", "Three levels of difficulty, plus retrieval");

  const lv = [
    ["Stratified random split", "222 / 48 / 46 clips. All six folders can appear in each subset — a conventional within-dataset benchmark that does not isolate geography."],
    ["Grouped-site split", "buzzes_o (Site 3) for validation, buzzes_tb (Site 2) for test, 229 clips for training. The test site is geographically separated from training."],
    ["Leave-one-folder-out ×6", "Each folder held out in turn; scaler and detector refitted inside every round. Mean, SD and worst-folder F1 summarise the variation."],
  ];
  const lw = 7.10;
  lv.forEach(([t, d], i) => {
    const y = 1.66 + i * 1.52;
    card(s, M, y, lw, 1.36, { fill: WHITE, line: LINE, shadow: true });
    numDot(s, M + 0.26, y + 0.20, i + 1);
    s.addText(t, { x: M + 0.86, y: y + 0.16, w: lw - 1.14, h: 0.30, fontFace: SANS,
      fontSize: 14, bold: true, color: INK, isTextBox: true, margin: 0 });
    s.addText(d, { x: M + 0.86, y: y + 0.52, w: lw - 1.14, h: 0.76, fontFace: SANS,
      fontSize: 12.5, color: BODY, lineSpacing: 17, valign: "top", isTextBox: true, margin: 0 });
  });

  const rx = M + lw + 0.42, rw = CW - lw - 0.42;
  card(s, rx, 1.66, rw, 2.80, { fill: INK, line: INK });
  s.addText("Site-aware retrieval  (RQ2)", { x: rx + 0.28, y: 1.86, w: rw - 0.56, h: 0.30,
    fontFace: SANS, fontSize: 14, bold: true, color: AMBER, isTextBox: true, margin: 0 });
  bullets(s, [
    "All 158 buzz clips used as queries",
    "The query's own folder excluded from the candidate pool",
    "Cross-folder pool scaled and L2-normalised, ranked by cosine similarity",
    "100 seeded random permutations = an unguided reviewer",
  ], { x: rx + 0.28, y: 2.26, w: rw - 0.56, h: 1.96, fontSize: 11.5, color: "DCE5F1",
       lineSpacing: 16, paraSpaceAfter: 6 });

  card(s, rx, 4.66, rw, 1.54, { fill: WHITE, line: CORAL });
  s.addText("Stated up front", { x: rx + 0.28, y: 4.80, w: rw - 0.56, h: 0.30, fontFace: SANS,
    fontSize: 13.5, bold: true, color: CORAL, isTextBox: true, margin: 0 });
  s.addText("buzzes_sp and buzzes_spmylu are both Site 4 — so LOFO and retrieval measure folder-level robustness, not five-location isolation.", {
    x: rx + 0.28, y: 5.16, w: rw - 0.56, h: 0.88, fontFace: SANS, fontSize: 11.5,
    color: BODY, lineSpacing: 16, valign: "top", isTextBox: true, margin: 0 });

  foot(s, 7, "Evaluation design");
  s.addNotes(notes(7));
}

/* =======================================================================
   8 — DETECTION RESULTS
   ===================================================================== */
{
  const s = newSlide();
  head(s, "Results · RQ1", "Not just better on average — more stable");

  const labels = ["Baseline (1,543-d)", "Compact (199-d)", "Perch v2 (1,536-d)"];
  s.addChart(pres.ChartType.bar, [
    { name: "LOFO mean F1", labels, values: [0.872, 0.870, 0.989] },
    { name: "Worst-folder F1", labels, values: [0.727, 0.691, 0.950] },
  ], Object.assign({}, chartFrame, {
    x: M - 0.10, y: 1.64, w: 7.70, h: 4.52,
    barDir: "col", chartColors: [TEALD, AMBER],
    valAxisMinVal: 0, valAxisMaxVal: 1.0, valAxisMajorUnit: 0.2,
    dataLabelFormatCode: "0.000",
    showTitle: true, title: "Leave-one-folder-out detection (six rounds)",
    titleFontFace: SANS, titleFontSize: 13, titleColor: INK,
  }));

  const rx = M + 7.86, rw = CW - 7.86;
  const takeaways = [
    ["The grouped-site test was easy", "All three representations reached F1 = 1.000 — that split did not discriminate between them."],
    ["Perch is stable across folders", "LOFO SD 0.020, against 0.101 and 0.114. Worst folder 0.950, against 0.727 and 0.691."],
    ["More features is not better", "199-d compact matched the 1,543-d baseline to within 0.002 F1 — one-eighth of the dimensions."],
  ];
  takeaways.forEach(([t, d], i) => {
    const y = 1.78 + i * 1.52;
    card(s, rx, y, rw, 1.36, { fill: i === 1 ? SURF : WHITE, line: i === 1 ? TEAL : LINE });
    s.addText(t, { x: rx + 0.24, y: y + 0.16, w: rw - 0.48, h: 0.32, fontFace: SANS,
      fontSize: 13, bold: true, color: INK, isTextBox: true, margin: 0 });
    s.addText(d, { x: rx + 0.24, y: y + 0.54, w: rw - 0.48, h: 0.72, fontFace: SANS,
      fontSize: 12, color: BODY, lineSpacing: 16, valign: "top", isTextBox: true, margin: 0 });
  });

  foot(s, 8, "Detection performance");
  s.addNotes(notes(8));
}

/* =======================================================================
   9 — RETRIEVAL RESULTS
   ===================================================================== */
{
  const s = newSlide();
  head(s, "Results · RQ2", "The same ranking, without a threshold");

  const labels = ["Baseline", "Compact", "Perch v2", "Random ranking"];
  s.addChart(pres.ChartType.bar, [
    { name: "Precision@5",  labels, values: [0.834, 0.839, 0.988, 0.500] },
    { name: "Precision@10", labels, values: [0.831, 0.830, 0.984, 0.500] },
    { name: "Precision@20", labels, values: [0.822, 0.821, 0.968, 0.501] },
  ], Object.assign({}, chartFrame, {
    x: M - 0.10, y: 1.64, w: 7.70, h: 4.52,
    barDir: "col", chartColors: [TEALD, TEAL, AMBER],
    valAxisMinVal: 0, valAxisMaxVal: 1.0, valAxisMajorUnit: 0.2,
    dataLabelFormatCode: "0.000", dataLabelFontSize: 9,
    showTitle: true, title: "Macro-averaged held-out-folder retrieval (158 buzz queries)",
    titleFontFace: SANS, titleFontSize: 13, titleColor: INK,
  }));

  const rx = M + 7.86, rw = CW - 7.86;
  card(s, rx, 1.70, rw, 1.90, { fill: INK, line: INK });
  s.addText("Average Precision", { x: rx + 0.24, y: 1.88, w: rw - 0.48, h: 0.28, fontFace: SANS,
    fontSize: 12.5, bold: true, charSpacing: 0.8, color: AMBER, isTextBox: true, margin: 0 });
  s.addText([
    { text: "0.879", options: { fontFace: HEAD, fontSize: 30, bold: true, color: WHITE } },
    { text: "  Perch v2", options: { fontFace: SANS, fontSize: 13, color: "B3C4DC" } },
  ], { x: rx + 0.24, y: 2.18, w: rw - 0.48, h: 0.56, valign: "top", isTextBox: true, margin: 0 });
  s.addText("Baseline 0.770  ·  Compact 0.771", { x: rx + 0.24, y: 2.76, w: rw - 0.48, h: 0.28,
    fontFace: SANS, fontSize: 12.5, color: "B3C4DC", isTextBox: true, margin: 0 });
  s.addText("Below its own top-k precision — the separation sits near the top of the ranking.", {
    x: rx + 0.24, y: 3.06, w: rw - 0.48, h: 0.46, fontFace: SANS, fontSize: 11.5,
    italic: true, color: "8FA5C4", lineSpacing: 15, valign: "top", isTextBox: true, margin: 0 });

  const takeaways = [
    ["That shape suits a review workflow", "An annotator inspects the highest-ranked candidates first, so precision at the top of the list is what saves time."],
    ["An easier problem than the field", "The balanced candidate pool puts random Precision@10 at 0.500. Buzzes are far rarer in continuous PAM data."],
  ];
  takeaways.forEach(([t, d], i) => {
    const y = 3.80 + i * 1.38;
    card(s, rx, y, rw, 1.20, { fill: WHITE, line: i === 1 ? CORAL : LINE });
    s.addText(t, { x: rx + 0.24, y: y + 0.14, w: rw - 0.48, h: 0.30, fontFace: SANS,
      fontSize: 12.5, bold: true, color: i === 1 ? CORAL : INK, isTextBox: true, margin: 0 });
    s.addText(d, { x: rx + 0.24, y: y + 0.50, w: rw - 0.48, h: 0.64, fontFace: SANS,
      fontSize: 11.5, color: BODY, lineSpacing: 15, valign: "top", isTextBox: true, margin: 0 });
  });

  foot(s, 9, "Similarity retrieval");
  s.addNotes(notes(9));
}

/* =======================================================================
   10 — KENYA
   ===================================================================== */
{
  const s = newSlide();
  head(s, "Results · RQ3", "Field candidate discovery in Kenya");

  s.addChart(pres.ChartType.bar, [
    { name: "Baseline", labels: ["score ≥ 0.50", "score ≥ 0.80", "score ≥ 0.95"], values: [22.11, 13.37, 4.43] },
    { name: "Perch v2", labels: ["score ≥ 0.50", "score ≥ 0.80", "score ≥ 0.95"], values: [15.96, 6.55, 2.14] },
  ], Object.assign({}, chartFrame, {
    x: M - 0.10, y: 1.64, w: 6.50, h: 4.10,
    barDir: "col", chartColors: [MUTED, AMBER],
    valAxisMinVal: 0, valAxisMaxVal: 25, valAxisMajorUnit: 5,
    dataLabelFormatCode: '0.00"%"',
    showTitle: true, title: "% of 270,156 windows above each descriptive threshold",
    titleFontFace: SANS, titleFontSize: 12.5, titleColor: INK,
  }));
  s.addText("Different score scales — this compares how each detector prioritised the same recordings, not its precision.", {
    x: M, y: 5.78, w: 6.30, h: 0.5, fontFace: SANS, fontSize: 11, italic: true,
    color: MUTED, lineSpacing: 15, isTextBox: true, margin: 0 });

  const rx = M + 6.72, rw = CW - 6.72;
  s.addText("Manual review — 69 Perch candidates, each from a different one-minute recording", {
    x: rx, y: 1.66, w: rw, h: 0.52, fontFace: SANS, fontSize: 13.5, bold: true,
    color: INK, lineSpacing: 18, isTextBox: true, margin: 0 });

  const cats = [
    ["Insect-like", 27, "39.1%", CORAL],
    ["Buzz-like", 19, "27.5%", AMBER],
    ["Background noise", 10, "14.5%", "9FB0C8"],
    ["Recording artefact", 9, "13.0%", "9FB0C8"],
    ["Single click", 3, "4.3%", "9FB0C8"],
    ["Unclear", 1, "1.4%", "9FB0C8"],
  ];
  const barX = rx + 1.86, barMax = 2.42;
  cats.forEach(([name, n, pct, col], i) => {
    const y = 2.36 + i * 0.53;
    s.addText(name, { x: rx, y, w: 1.78, h: 0.3, fontFace: SANS, fontSize: 12,
      color: BODY, align: "right", valign: "middle", isTextBox: true, margin: 0 });
    s.addShape(pres.ShapeType.rect, { x: barX, y: y + 0.055, w: barMax, h: 0.19,
      fill: { color: SURF2 }, line: { type: "none" } });
    s.addShape(pres.ShapeType.rect, { x: barX, y: y + 0.055, w: barMax * (n / 27), h: 0.19,
      fill: { color: col }, line: { type: "none" } });
    s.addText(`${n}   ${pct}`, { x: barX + barMax + 0.12, y, w: 1.30, h: 0.3, fontFace: SANS,
      fontSize: 11.5, bold: i < 2, color: i < 2 ? INK : MUTED, valign: "middle",
      isTextBox: true, margin: 0 });
  });

  card(s, rx, 5.56, rw, 0.94, { fill: SURF });
  s.addText("Selected by Perch score — these proportions describe the reviewed candidates, not buzz prevalence across all 270,156 windows.", {
    x: rx + 0.24, y: 5.70, w: rw - 0.48, h: 0.70, fontFace: SANS, fontSize: 11.5,
    italic: true, color: BODY, lineSpacing: 15, valign: "top", isTextBox: true, margin: 0 });

  foot(s, 10, "Kenya field application");
  s.addNotes(notes(10));
}

/* =======================================================================
   11 — BUZZ VS INSECT
   ===================================================================== */
{
  const s = newSlide(true);
  head(s, "Results · what the review taught me", "Inside 0.25 s, these look alike", { dark: true });

  const pw = 5.86, gap = CW - 2 * pw;
  const panels = [
    ["Buzz-like", "Intervals compress into a terminal buzz and the sequence stops. Short, and changing rapidly.", AMBER],
    ["Insect-like", "Metronomic intervals that continue for far longer than a buzz ever does. Regular, and persistent.", CORAL],
  ];
  panels.forEach(([t, d, col], i) => {
    const x = M + i * (pw + gap);
    s.addImage({ path: `${B}/${i ? "spec_insect" : "spec_buzz"}.png`, x, y: 2.06, w: pw, h: 1.67 });
    s.addShape(pres.ShapeType.rect, { x, y: 2.06, w: pw, h: 1.67,
      fill: { type: "none" }, line: { color: col, width: 1.25 } });
    s.addText(t, { x, y: 3.86, w: pw, h: 0.34, fontFace: SANS, fontSize: 15, bold: true,
      color: col, isTextBox: true, margin: 0 });
    s.addText(d, { x, y: 4.22, w: pw, h: 0.76, fontFace: SANS, fontSize: 13,
      color: "C3D2E8", lineSpacing: 18, isTextBox: true, margin: 0 });
  });
  s.addText("Schematic illustrations of the two patterns", { x: M, y: 1.72, w: CW, h: 0.28,
    fontFace: SANS, fontSize: 11, italic: true, color: "6E819F", isTextBox: true, margin: 0 });

  card(s, M, 5.16, CW, 1.28, { fill: INK2, line: INK2 });
  s.addText([
    { text: "It is the surrounding second that separates them. ", options: { bold: true, color: WHITE } },
    { text: "Future detectors would benefit from wider contextual windows, or a second-stage model that examines the temporal neighbourhood around a high-scoring short window. The 27 insect-like candidates are ready-made hard negatives for an active-learning cycle.", options: { color: "C3D2E8" } },
  ], { x: M + 0.30, y: 5.34, w: CW - 0.60, h: 0.94, fontFace: SANS, fontSize: 13.5,
       lineSpacing: 19, valign: "top", isTextBox: true, margin: 0 });

  foot(s, 11, "Buzz-like versus insect-like", true);
  s.addNotes(notes(11));
}

/* =======================================================================
   12 — LIMITATIONS
   ===================================================================== */
{
  const s = newSlide();
  head(s, "Limitations", "What I would ask about this work");

  const lims = [
    ["Site 4 folder pairing", "buzzes_sp and buzzes_spmylu are the same location, so LOFO and retrieval never fully isolated geography. These values may be optimistic relative to a strict five-location rerun.", "The grouped-site test on buzzes_tb does remain geographically isolated."],
    ["A duration / padding shortcut", "At a 0.50 s window, class label aligned perfectly with padded-vs-cropped. I chose 0.25 s to weaken that, but 127 buzz clips were still padded while all non-buzz clips were cropped.", "Perch is not immune just because its features are pretrained."],
    ["Pipelines, not architectures", "Only the Perch route carries the 384→320 kHz conversion and tenfold expansion, so the comparison cannot attribute the gain to the embedding alone.", "A duration-matched benchmark would separate the two."],
    ["Kenya has no ground truth", "The 69 reviewed candidates were selected by Perch score, so the review proportions are descriptive. No event-level precision or recall can be computed.", "Category labels are descriptive, not verified ground truth."],
  ];
  const cw = (CW - 0.36) / 2, ch = 2.30;
  lims.forEach(([t, d, n], i) => {
    const x = M + (i % 2) * (cw + 0.36);
    const y = 1.66 + Math.floor(i / 2) * (ch + 0.30);
    card(s, x, y, cw, ch, { fill: WHITE, line: LINE, shadow: true });
    numDot(s, x + 0.26, y + 0.22, i + 1, { fill: CORAL });
    s.addText(t, { x: x + 0.86, y: y + 0.18, w: cw - 1.12, h: 0.34, fontFace: SANS,
      fontSize: 14, bold: true, color: INK, isTextBox: true, margin: 0 });
    s.addText(d, { x: x + 0.26, y: y + 0.70, w: cw - 0.52, h: 1.10, fontFace: SANS,
      fontSize: 12.5, color: BODY, lineSpacing: 17, valign: "top", isTextBox: true, margin: 0 });
    s.addText(n, { x: x + 0.26, y: y + 1.82, w: cw - 0.52, h: 0.42, fontFace: SANS,
      fontSize: 11.5, italic: true, color: TEALD, lineSpacing: 15, valign: "top",
      isTextBox: true, margin: 0 });
  });

  foot(s, 12, "Limitations");
  s.addNotes(notes(12));
}

/* =======================================================================
   13 — CONCLUSIONS
   ===================================================================== */
{
  const s = newSlide();
  head(s, "Conclusions", "Representation matters, but is not enough");

  const cs = [
    ["RQ1", "Perch v2 generalised best", "After tenfold time expansion, frozen embeddings reached mean LOFO F1 = 0.989 with an SD of 0.020 and a worst folder of 0.950."],
    ["RQ2", "And retrieved best", "Precision@10 = 0.984 against 0.831 and 0.830, with separation concentrated at the top of the ranking, where reviewers actually look."],
    ["RQ3", "But the field needs more", "Perch surfaced buzz-like sequences across many recordings, but insect-like pulse trains were the largest reviewed category. Context and human review still do essential work."],
  ];
  const cw = (CW - 2 * 0.36) / 3;
  cs.forEach(([tag, t, d], i) => {
    const x = M + i * (cw + 0.36);
    card(s, x, 1.62, cw, 2.62, { fill: i === 2 ? SURF : WHITE, line: i === 2 ? TEAL : LINE, shadow: i !== 2 });
    s.addText(tag, { x: x + 0.26, y: 1.78, w: cw - 0.52, h: 0.28, fontFace: SANS,
      fontSize: 11, bold: true, charSpacing: 1.6, color: TEALD, isTextBox: true, margin: 0 });
    s.addText(t, { x: x + 0.26, y: 2.08, w: cw - 0.52, h: 0.66, fontFace: HEAD,
      fontSize: 18, bold: true, color: INK, lineSpacing: 22, valign: "top", isTextBox: true, margin: 0 });
    s.addText(d, { x: x + 0.26, y: 2.80, w: cw - 0.52, h: 1.30, fontFace: SANS,
      fontSize: 12.5, color: BODY, lineSpacing: 17, valign: "top", isTextBox: true, margin: 0 });
  });

  card(s, M, 4.44, CW, 0.84, { fill: WHITE, line: LINE });
  s.addText([
    { text: "A secondary result:  ", options: { bold: true, color: INK } },
    { text: "199 compact dimensions matched 1,543 baseline dimensions to within 0.002 F1 and 0.001 Precision@10. More hand-crafted features are not automatically better.", options: { color: BODY } },
  ], { x: M + 0.28, y: 4.58, w: CW - 0.56, h: 0.58, fontFace: SANS, fontSize: 13.5,
       lineSpacing: 18, valign: "top", isTextBox: true, margin: 0 });

  card(s, M, 5.44, CW, 1.10, { fill: INK, line: INK });
  s.addText("Next step", { x: M + 0.30, y: 5.60, w: 1.4, h: 0.3, fontFace: SANS, fontSize: 12,
    bold: true, charSpacing: 1.4, color: AMBER, isTextBox: true, margin: 0 });
  s.addText("An independently sampled, exhaustively reviewed Kenya subset — it would give event-level precision and recall, let both detectors be compared on the same confirmed events, and turn those insect-like candidates into hard negatives for retraining.", {
    x: M + 1.86, y: 5.58, w: CW - 2.16, h: 0.84, fontFace: SANS, fontSize: 13.5,
    color: "DCE5F1", lineSpacing: 18, valign: "top", isTextBox: true, margin: 0 });

  foot(s, 13, "Conclusions and next steps");
  s.addNotes(notes(13));
}

/* =======================================================================
   14 — THANK YOU
   ===================================================================== */
{
  const s = newSlide(true);
  s.addImage({ path: `${B}/spec_strip.png`, x: 0, y: 5.10, w: W, h: 1.30 });

  s.addText("Thank you", { x: 0.9, y: 2.06, w: 11.5, h: 1.0, fontFace: HEAD, fontSize: 52,
    bold: true, color: WHITE, isTextBox: true, margin: 0 });
  s.addText("Questions welcome", { x: 0.9, y: 3.12, w: 11.5, h: 0.5, fontFace: SANS,
    fontSize: 19, color: AMBER, isTextBox: true, margin: 0 });
  s.addText("With thanks to Santiago Martinez Balvanera and Kate Jones for their supervision, and to the researchers who collected and shared the Kenya recordings.", {
    x: 0.9, y: 3.86, w: 8.6, h: 0.8, fontFace: SANS, fontSize: 13, color: "AFC0D8",
    lineSpacing: 19, isTextBox: true, margin: 0 });

  s.addNotes(notes(14));
}

/* =======================================================================
   BACKUP SLIDES
   ===================================================================== */
function backupHead(s, n, title) {
  head(s, `Backup ${n}`, title);
  foot(s, `B${n}`, "Backup slide — not presented");
}

const tblOpt = (w, colW) => ({
  x: M, w, colW, rowH: 0.32, align: "left", valign: "middle",
  border: { type: "none" }, margin: 6,
});
const TH = { fontFace: SANS, fontSize: 11.5, bold: true, color: WHITE, fill: { color: INK } };
function body(i, o = {}) {
  return Object.assign({ fontFace: SANS, fontSize: 11.5, color: BODY,
    fill: { color: i % 2 ? SURF : WHITE } }, o);
}

/* B1 — detection detail */
{
  const s = newSlide();
  backupHead(s, 1, "Detection — full metric set");
  const rows = [
    ["Representation", "Random F1", "Grouped-site F1", "LOFO mean F1", "LOFO SD", "Worst folder", "Mean acc.", "ROC-AUC", "AP"],
    ["Baseline (1,543-d)", "0.930", "1.000", "0.872", "0.101", "0.727", "0.883", "0.9728", "0.9744"],
    ["Compact (199-d)", "0.905", "1.000", "0.870", "0.114", "0.691", "0.881", "0.9716", "0.9737"],
    ["Perch v2 (1,536-d)", "1.000", "1.000", "0.989", "0.020", "0.950", "0.990", "0.9997", "0.9996"],
  ].map((r, i) => r.map((c) => ({ text: c, options: i === 0 ? TH : body(i, { bold: i === 3 }) })));
  s.addTable(rows, Object.assign({ y: 1.66 }, tblOpt(CW, [2.55, 1.15, 1.55, 1.40, 1.05, 1.30, 1.10, 1.05, 0.98])));

  card(s, M, 3.44, CW, 1.24, { fill: SURF });
  s.addText([
    { text: "LOFO mean precision / recall:  ", options: { bold: true, color: INK } },
    { text: "0.910 / 0.857 (baseline) · 0.910 / 0.851 (compact) · 0.994 / 0.984 (Perch).", options: { color: BODY } },
  ], { x: M + 0.28, y: 3.58, w: CW - 0.56, h: 0.32, fontFace: SANS, fontSize: 13, valign: "top", isTextBox: true, margin: 0 });
  s.addText([
    { text: "Folder-level range:  ", options: { bold: true, color: INK } },
    { text: "baseline F1 0.727 (buzzes_sp) → 1.000 (buzzes_tb); compact low 0.691 (buzzes_sp); Perch 0.950 (buzzes_o), 0.983 (buzzes_sp) and 1.000 in the remaining four rounds.", options: { color: BODY } },
  ], { x: M + 0.28, y: 3.96, w: CW - 0.56, h: 0.60, fontFace: SANS, fontSize: 13,
       lineSpacing: 18, valign: "top", isTextBox: true, margin: 0 });

  card(s, M, 4.94, CW, 1.36, { fill: WHITE, line: LINE });
  s.addText("Splits", { x: M + 0.28, y: 5.08, w: CW - 0.56, h: 0.3, fontFace: SANS,
    fontSize: 13, bold: true, color: TEALD, isTextBox: true, margin: 0 });
  s.addText("Random: 222 train / 48 validation / 46 test, stratified.   Grouped-site: buzzes_o (Site 3) validation, buzzes_tb (Site 2) test, 229 train.   LOFO: six rounds, scaler and detector refitted inside each round. Representation definitions, detector settings and the 0.5 threshold were fixed independently of the reserved validation set.", {
    x: M + 0.28, y: 5.40, w: CW - 0.56, h: 0.84, fontFace: SANS, fontSize: 12.5,
    color: BODY, lineSpacing: 18, valign: "top", isTextBox: true, margin: 0 });
}

/* B2 — retrieval detail */
{
  const s = newSlide();
  backupHead(s, 2, "Retrieval — full metric set");
  const rows = [
    ["Representation", "Precision@5", "Precision@10", "Precision@20", "Average Precision"],
    ["Baseline", "0.834", "0.831", "0.822", "0.770"],
    ["Compact", "0.839", "0.830", "0.821", "0.771"],
    ["Perch v2", "0.988", "0.984", "0.968", "0.879"],
    ["Random ranking", "0.500", "0.500", "0.501", "0.510"],
  ].map((r, i) => r.map((c) => ({ text: c, options: i === 0 ? TH : body(i, { bold: i === 3 }) })));
  s.addTable(rows, Object.assign({ y: 1.66 }, tblOpt(9.4, [2.60, 1.70, 1.80, 1.80, 1.50])));

  card(s, M, 3.82, CW, 2.56, { fill: WHITE, line: LINE });
  bullets(s, [
    "All 158 labelled buzz clips used as queries; every clip from the query's own folder excluded from the candidate pool.",
    "StandardScaler fitted on the cross-folder candidate pool only, then applied to both pool and query; vectors L2-normalised and ranked by cosine similarity.",
    "Folder-level values macro-averaged so that folders with more queries do not dominate.",
    "Perch Precision@10 ranged 0.948 (buzzes_o queries) to 1.000 (buzzes_tb); folder-level AP ranged 0.750 to 0.955.",
    "Random baseline: 100 seeded permutations per query (seed 42), generator advancing between repetitions.",
    "Roughly balanced pools put random Precision@10 at ≈ 0.500 — easier than naturally rare field events.",
  ], { x: M + 0.28, y: 4.02, w: CW - 0.56, h: 2.20, fontSize: 12.5, lineSpacing: 17 });
}

/* B3 — preprocessing sensitivity */
{
  const s = newSlide();
  backupHead(s, 3, "Preprocessing sensitivity");

  s.addText("Analysis-window duration (spectral-statistics detector)", { x: M, y: 1.62, w: 7.7,
    h: 0.32, fontFace: SANS, fontSize: 13.5, bold: true, color: INK, isTextBox: true, margin: 0 });
  s.addChart(pres.ChartType.bar, [
    { name: "Mean LOFO F1", labels: ["0.10 s", "0.15 s", "0.20 s", "0.25 s ✓", "0.50 s"],
      values: [0.655, 0.767, 0.802, 0.872, 0.994] },
  ], Object.assign({}, chartFrame, {
    x: M - 0.10, y: 2.00, w: 7.70, h: 3.10, barDir: "col", chartColors: [TEALD],
    valAxisMinVal: 0, valAxisMaxVal: 1.0, valAxisMajorUnit: 0.2,
    dataLabelFormatCode: "0.000", showLegend: false, showTitle: false,
  }));
  s.addText("0.50 s scores highest — and is exactly where the padding shortcut is total: all 158 buzz clips padded, all 158 non-buzz clips cropped. 0.25 s was retained as the compromise (127 buzz clips padded, 189 clips cropped). At 0.10 s, random-test F1 was 0.979 but worst-folder F1 collapsed to 0.050.", {
    x: M, y: 5.16, w: 7.70, h: 1.04, fontFace: SANS, fontSize: 12, italic: true,
    color: MUTED, lineSpacing: 16, isTextBox: true, margin: 0 });

  const rx = M + 7.96, rw = CW - 7.96;
  card(s, rx, 1.62, rw, 2.14, { fill: SURF });
  s.addText("Spectrogram resolution", { x: rx + 0.24, y: 1.78, w: rw - 0.48,
    h: 0.30, fontFace: SANS, fontSize: 13, bold: true, color: INK, isTextBox: true, margin: 0 });
  bullets(s, [
    "1024 / 512 (used): LOFO mean 0.872, worst 0.727",
    "256 / 128: LOFO mean 0.881, worst 0.714",
    "1024 / 900: LOFO mean 0.864, worst 0.691",
  ], { x: rx + 0.24, y: 2.20, w: rw - 0.48, h: 1.46, fontSize: 12, lineSpacing: 16, paraSpaceAfter: 5 });

  card(s, rx, 4.02, rw, 2.54, { fill: WHITE, line: LINE });
  s.addText("Settings used throughout", { x: rx + 0.24, y: 4.18, w: rw - 0.48, h: 0.30,
    fontFace: SANS, fontSize: 13, bold: true, color: INK, isTextBox: true, margin: 0 });
  bullets(s, [
    "Periodic Tukey window (α = 0.25), nfft = 1024",
    "513 frequency bins × 186 time bins per clip",
    "log10(magnitude + 1e-10) applied first",
    "Crop position gave the same pattern",
  ], { x: rx + 0.24, y: 4.64, w: rw - 0.48, h: 1.72, fontSize: 12, lineSpacing: 16, paraSpaceAfter: 5 });
}

/* B4 — Kenya detail */
{
  const s = newSlide();
  backupHead(s, 4, "Kenya — thresholds, coverage and timing");
  const rows = [
    ["Detector", "≥ 0.50 windows", "≥ 0.80 windows", "≥ 0.95 windows", "Files with ≥ 0.95"],
    ["Baseline", "59,741  (22.11%)", "36,110  (13.37%)", "11,978  (4.43%)", "161"],
    ["Perch v2", "43,130  (15.96%)", "17,692  (6.55%)", "5,774  (2.14%)", "121"],
  ].map((r, i) => r.map((c) => ({ text: c, options: i === 0 ? TH : body(i, { bold: i === 2 }) })));
  s.addTable(rows, Object.assign({ y: 1.66 }, tblOpt(CW, [2.30, 2.55, 2.55, 2.55, 2.14])));

  card(s, M, 2.86, 6.30, 1.62, { fill: SURF });
  s.addText("Spread across recordings", { x: M + 0.26, y: 3.00, w: 5.78, h: 0.3, fontFace: SANS,
    fontSize: 13, bold: true, color: INK, isTextBox: true, margin: 0 });
  s.addText("At the lower two thresholds, Perch windows were spread across more recordings despite being fewer in total — 466 files vs 343 at ≥ 0.50, and 328 vs 254 at ≥ 0.80.", {
    x: M + 0.26, y: 3.32, w: 5.78, h: 1.0, fontFace: SANS, fontSize: 12.5, color: BODY,
    lineSpacing: 17, valign: "top", isTextBox: true, margin: 0 });

  card(s, M + 6.72, 2.86, CW - 6.72, 1.62, { fill: SURF });
  s.addText("Temporal pattern (EAT, UTC+3)", { x: M + 6.98, y: 3.00, w: CW - 7.24, h: 0.3,
    fontFace: SANS, fontSize: 13, bold: true, color: INK, isTextBox: true, margin: 0 });
  s.addText("Highest rates at 23:00 EAT — 30.14% / 17.57% / 7.71% at the 0.50, 0.80 and 0.95 thresholds. Highest daily rates on 24 October 2019. Hours without recordings are not treated as zero.", {
    x: M + 6.98, y: 3.32, w: CW - 7.24, h: 1.0, fontFace: SANS, fontSize: 12.5, color: BODY,
    lineSpacing: 17, valign: "top", isTextBox: true, margin: 0 });

  card(s, M, 4.66, CW, 1.66, { fill: WHITE, line: LINE });
  s.addText("Candidate selection and review", { x: M + 0.28, y: 4.80, w: CW - 0.56, h: 0.3,
    fontFace: SANS, fontSize: 13, bold: true, color: TEALD, isTextBox: true, margin: 0 });
  s.addText("Route 1 — top 50 Perch windows, neighbouring high-scoring windows within 1 s grouped into one event, one representative window kept per event.   Route 2 — eight windows sampled from each of four score bands (0.95–1.00, 0.80–0.95, 0.50–0.80, 0.20–0.50).   De-duplicated to one candidate per one-minute recording: 53 retained plus 16 newly reviewed = 69 candidates from 69 distinct recordings. Each reviewed with its 0.25 s spectrogram, 1.25 s of context, pulse-timing structure and time-expanded audio.", {
    x: M + 0.28, y: 5.12, w: CW - 0.56, h: 1.14, fontFace: SANS, fontSize: 12,
    color: BODY, lineSpacing: 17, valign: "top", isTextBox: true, margin: 0 });
}

/* B5 — implementation */
{
  const s = newSlide();
  backupHead(s, 5, "Implementation details");

  const cw = (CW - 2 * 0.36) / 3;
  const cols = [
    ["Environment", ["Python 3.12.13", "SciPy 1.18.0", "scikit-learn 1.9.0", "Perch-Hoplite 1.0.1", "perch_v2_cpu (frozen, no fine-tuning)"]],
    ["Detector", ["StandardScaler, fitted on training data only", "Logistic regression, L2 penalty", "C = 1.0, solver lbfgs", "class_weight = balanced", "random_state = 42, max_iter = 1000", "Decision threshold 0.5"]],
    ["Field scoring", ["Every 60 s recording peak-normalised", "0.25 s windows, 0.125 s hop", "479 windows per recording", "564 files → 270,156 windows", "Perch: 384→320 kHz, 80,000 samples per window, read as 2.5 s", "Timestamps verified against AudioMoth WAV headers, then converted to EAT"]],
  ];
  cols.forEach(([t, items], i) => {
    const x = M + i * (cw + 0.36);
    card(s, x, 1.62, cw, 3.92, { fill: WHITE, line: LINE, shadow: true });
    s.addText(t, { x: x + 0.26, y: 1.80, w: cw - 0.52, h: 0.32, fontFace: SANS,
      fontSize: 14, bold: true, color: TEALD, isTextBox: true, margin: 0 });
    bullets(s, items, { x: x + 0.26, y: 2.18, w: cw - 0.52, h: 3.16, fontSize: 12.5, lineSpacing: 17 });
  });
}

pres.writeFile({ fileName: OUT }).then((f) => console.log("wrote", f));
