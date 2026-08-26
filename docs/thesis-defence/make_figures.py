"""Synthetic, illustrative spectrogram panels for the defence deck.

These are schematic illustrations of the acoustic patterns discussed in the
thesis (bat feeding buzz vs. insect pulse train), rendered in the deck palette.
They are drawings, not data from the study.
"""
import numpy as np
from PIL import Image, ImageFilter

OUT = "/home/user/valentown/docs/thesis-defence/build"

# Deck palette ramp: night navy -> teal -> amber -> near-white
ANCHORS = [
    (0.00, (0x0E, 0x1B, 0x33)),
    (0.32, (0x1B, 0x4F, 0x63)),
    (0.55, (0x2A, 0x9D, 0x8F)),
    (0.78, (0xF2, 0xA5, 0x41)),
    (1.00, (0xFF, 0xF1, 0xDC)),
]


def ramp(x):
    x = np.clip(x, 0.0, 1.0)
    out = np.zeros(x.shape + (3,), dtype=np.float64)
    for i in range(len(ANCHORS) - 1):
        p0, c0 = ANCHORS[i]
        p1, c1 = ANCHORS[i + 1]
        m = (x >= p0) & (x <= p1)
        t = np.zeros_like(x)
        t[m] = (x[m] - p0) / (p1 - p0)
        for ch in range(3):
            out[..., ch][m] = c0[ch] + (c1[ch] - c0[ch]) * t[m]
    return out


def blank(nf, nt, seed):
    rng = np.random.default_rng(seed)
    # faint textured background noise floor
    bg = rng.random((nf, nt)) * 0.03
    bg += np.linspace(0.028, 0.0, nf)[:, None]  # slight low-frequency haze
    return bg


def sweep(S, t0, dur, f_hi, f_lo, amp=1.0, width=3.0):
    """Add one FM downsweep pulse (a bat call) to spectrogram S."""
    nf, nt = S.shape
    t_idx = np.arange(nt)
    f_idx = np.arange(nf)[:, None]
    n = max(int(dur), 2)
    for k in range(n):
        t = t0 + k
        if not (0 <= t < nt):
            continue
        frac = k / (n - 1)
        # frequency falls quickly then flattens (typical FM sweep shape)
        f = f_hi + (f_lo - f_hi) * (frac ** 0.55)
        row = (1.0 - f) * (nf - 1)
        env = np.sin(np.pi * (0.15 + 0.85 * frac)) ** 0.4
        S[:, t] += amp * env * np.exp(-((f_idx[:, 0] - row) ** 2) / (2 * width ** 2))


def cqpulse(S, t0, dur, f_c, amp=1.0, width=2.2, harm=(1.0, 0.45, 0.2)):
    """Add one narrowband + harmonics pulse (an insect tick) to S."""
    nf, nt = S.shape
    f_idx = np.arange(nf)
    for k in range(max(int(dur), 1)):
        t = t0 + k
        if not (0 <= t < nt):
            continue
        env = 1.0 - (k / max(dur, 1)) * 0.5
        for h, ha in enumerate(harm, start=1):
            row = (1.0 - min(f_c * h, 0.97)) * (nf - 1)
            S[:, t] += amp * ha * env * np.exp(-((f_idx - row) ** 2) / (2 * width ** 2))


def render(S, path, gain=1.0):
    S = np.clip(S * gain, 0, 1.4)
    S = S / 1.4
    S = S ** 0.85
    img = Image.fromarray(np.clip(ramp(S), 0, 255).astype(np.uint8), "RGB")
    img = img.filter(ImageFilter.GaussianBlur(0.6))
    img = img.resize((img.width * 2, img.height * 2), Image.LANCZOS)
    img.save(path)
    return path


def pulse_times(t_start, gap0, ratio, gap_min, n_terminal, limit):
    """Inter-pulse intervals that shorten into a terminal buzz, then stop."""
    times, t, gap, at_floor = [], float(t_start), float(gap0), 0
    while t < limit:
        times.append(int(t))
        t += gap
        if gap <= gap_min * 1.001:
            at_floor += 1
            if at_floor >= n_terminal:
                break
        gap = max(gap_min, gap * ratio)
    return times


def buzz(nf=160, nt=560, seed=7):
    S = blank(nf, nt, seed)
    times = pulse_times(30, 88, 0.66, 6.5, 16, nt - 20)
    n = len(times)
    for i, t in enumerate(times):
        frac = i / max(n - 1, 1)
        # terminal calls are shorter, quieter and cover a narrower band
        dur = max(3, int(round(9 - 5 * frac)))
        f_hi = 0.93 - 0.14 * frac
        f_lo = 0.28 + 0.20 * frac
        sweep(S, t, dur, f_hi, f_lo, amp=1.25 - 0.30 * frac, width=2.9)
    return S


# -------------------------------------------------------------- insect panel
def insect(nf=160, nt=560, seed=11):
    S = blank(nf, nt, seed)
    rng = np.random.default_rng(seed)
    t = 18
    while t < nt - 8:
        cqpulse(S, t, 6, 0.26, amp=1.5, width=3.0, harm=(1.0, 0.62, 0.34))
        t += 30 + int(rng.integers(-2, 3))   # metronomic, long-running
    return S


def strip(nf=110, nt=1180, seed=3):
    S = blank(nf, nt, seed)
    times = pulse_times(55, 235, 0.68, 13.0, 24, nt - 30)
    n = len(times)
    for i, t in enumerate(times):
        frac = i / max(n - 1, 1)
        dur = max(3, int(round(10 - 5 * frac)))
        sweep(S, t, dur, 0.94 - 0.14 * frac, 0.30 + 0.20 * frac,
              amp=1.2 - 0.25 * frac, width=2.4)
    return S


print(render(buzz(), f"{OUT}/spec_buzz.png", gain=1.05))
print(render(insect(), f"{OUT}/spec_insect.png", gain=1.05))
print(render(strip(), f"{OUT}/spec_strip.png", gain=1.0))
