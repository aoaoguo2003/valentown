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
node build_deck.js          # -> WPNS1_defence_deck.pptx (notes read from script.json)
python3 make_script.py      # -> SPEAKER_SCRIPT.md
```

To change what is said, edit `script.json` and rerun `build_deck.js` and `make_script.py`.

`build/spec_buzz.png`, `build/spec_insect.png` and `build/spec_strip.png` are **schematic
illustrations** of the two acoustic patterns discussed in the dissertation, drawn in the
deck palette. They are drawings, not data from the study, and the deck labels them as such.
