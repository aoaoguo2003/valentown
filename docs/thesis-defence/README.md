# UCL MSc Defence — Presentation Package

Ten-minute viva presentation for the dissertation *Time-Expanded Perch Embeddings for
Feeding-Buzz Detection, Retrieval and Field Candidate Discovery* (Candidate WPNS1,
BIOS0057, MSc Ecology and Data Science, UCL).

## Deliverables

| File | What it is |
|------|------------|
| `WPNS1_defence_deck.pptx` | 14 presentation slides + 5 backup slides. The spoken script is in each slide's Speaker Notes. |
| `WPNS1_defence_deck.pdf` | Flattened backup for the projector. |
| `SPEAKER_SCRIPT.md` | Full script with per-slide timings, backup-slide index, ten anticipated viva questions with prepared answers, and delivery notes (bilingual EN/中文). |

Every figure quoted in the deck is taken from the dissertation; nothing is invented.
Timing is 1,310 spoken words ≈ 9 min 30 s at 138 wpm.

## Rebuilding

`script.json` is the single source of truth for the spoken script — both the PowerPoint
speaker notes and `SPEAKER_SCRIPT.md` are generated from it, so they cannot drift apart.

```bash
npm install                 # pptxgenjs
pip install numpy Pillow    # figure generation

python3 make_figures.py     # schematic spectrogram panels -> build/
python3 make_bat.py         # bat silhouettes -> build/
node render_icons.js        # cricket icon (react-icons) -> build/
node build_deck.js          # -> WPNS1_defence_deck.pptx (notes read from script.json)
python3 make_script.py      # -> SPEAKER_SCRIPT.md
```

To change what is said, edit `script.json` and rerun `build_deck.js` and `make_script.py`.

## Artwork

`build/spec_*.png` are **schematic illustrations** of the acoustic patterns discussed in
the dissertation, drawn in the deck palette. They are drawings, not data from the study,
and the deck labels them as such.

`make_bat.py` draws the bat silhouette from scratch — a small body, tall ears and the
scalloped trailing edge where the wing membrane spans the elongated finger bones. Stock
bat icons are Halloween-styled and read wrong in a viva. The bat appears five times, each
time carrying meaning rather than decorating:

| Slide | Placement | What it says |
|-------|-----------|--------------|
| 1 Title | at the head of the call sequence on the strip | the bat emits the pulses that compress into the terminal buzz |
| 2 Motivation | in the lead-in of the buzz spectrogram | same, matching the caption beneath it |
| 6 Time expansion | in the "384 kHz / Source" card | where the bat call enters the pipeline |
| 11 Buzz vs insect | on the "Buzz-like" label, opposite a cricket on "Insect-like" | labels which panel is which |
| 14 Thank you | corner mark, plus the strip bat | closing motif |
