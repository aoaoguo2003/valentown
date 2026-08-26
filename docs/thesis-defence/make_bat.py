"""A field-guide style bat silhouette, drawn rather than borrowed.

Halloween clip-art reads wrong in a viva; what reads right is the shape a bat
actually makes in flight — small body, tall ears, and the scalloped trailing
edge where the wing membrane spans the elongated finger bones.
"""
import numpy as np
from PIL import Image, ImageDraw

SS = 4  # supersampling factor


def bez(p0, p1, p2, p3, n=60):
    t = np.linspace(0, 1, n)[:, None]
    p0, p1, p2, p3 = map(np.array, (p0, p1, p2, p3))
    return ((1 - t) ** 3 * p0 + 3 * (1 - t) ** 2 * t * p1
            + 3 * (1 - t) * t ** 2 * p2 + t ** 3 * p3)


def half_outline():
    """Right half of the bat, from the crown clockwise round to the tail tip."""
    pts = []

    def add(seq):
        pts.append(np.asarray(seq, dtype=float))

    # crown -> base of the right ear
    add(bez((0, 5), (3, 3), (4, 5), (5, 11)))
    # ear: up the inner edge, over a rounded tip, back down the outer edge
    add(bez((5, 11), (6, 2), (8, -2), (10, -1)))
    add(bez((10, -1), (12, 0), (13, 8), (12, 16)))
    # cheek and neck into the shoulder
    add(bez((12, 16), (11, 20), (10, 22), (11, 26)))
    # leading edge: forearm out to the wrist, then on to the wingtip
    add(bez((11, 26), (55, 11), (112, 7), (157, 20)))
    # trailing edge, wingtip back to digit IV (the membrane bows inward)
    add(bez((157, 20), (133, 33), (117, 33), (100, 47)))
    # digit IV -> digit V
    add(bez((100, 47), (86, 38), (76, 42), (63, 55)))
    # digit V -> ankle
    add(bez((63, 55), (48, 43), (33, 46), (20, 55)))
    # tail membrane: ankle down to the tail tip on the mid-line
    add(bez((20, 55), (15, 62), (8, 64), (0, 71)))
    return np.vstack(pts)


def outline():
    r = half_outline()
    left = r[::-1].copy()
    left[:, 0] *= -1
    return np.vstack([r, left[1:]])


def wing_bones():
    """Arm and finger bones — the lines that make it read as a bat, not a bird."""
    wrist = (107, 16)
    return [
        ((13, 27), wrist),     # humerus + radius, shoulder to wrist
        (wrist, (156, 21)),    # digit III, out to the wingtip
        (wrist, (100, 47)),    # digit IV
        (wrist, (64, 54)),     # digit V
    ]


def render(path, w=1400, color=(14, 27, 51), bones=True, bone_alpha=64):
    o = outline()
    span = o[:, 0].max() - o[:, 0].min()
    scale = (w * 0.94) / span * SS
    cx = w * SS / 2
    top = o[:, 1].min()

    def T(p):
        return (cx + p[0] * scale, (p[1] - top) * scale + 6 * SS)

    h = int((o[:, 1].max() - top) * scale + 14 * SS)
    img = Image.new("RGBA", (w * SS, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.polygon([T(p) for p in o], fill=color + (255,))

    if bones:
        for a, b in wing_bones():
            for sx in (1, -1):
                d.line([T((a[0] * sx, a[1])), T((b[0] * sx, b[1]))],
                       fill=(255, 255, 255, bone_alpha), width=max(int(1.1 * SS), 2))

    img = img.resize((w, h // SS), Image.LANCZOS)
    img.save(path)
    return img.size


OUT = "/home/user/valentown/docs/thesis-defence/build"
# with bones: for large placements where the anatomy is legible
print("bat_ink       ", render(f"{OUT}/bat_ink.png", color=(14, 27, 51)))
print("bat_white_bone", render(f"{OUT}/bat_white_bones.png", color=(255, 255, 255),
                               bones=True, bone_alpha=0))
# plain silhouettes: for small accents where bone lines would just be noise
print("bat_white     ", render(f"{OUT}/bat_white.png", color=(255, 255, 255), bones=False))
print("bat_amber     ", render(f"{OUT}/bat_amber.png", color=(242, 165, 65), bones=False))
print("bat_teal      ", render(f"{OUT}/bat_teal.png", color=(30, 122, 112), bones=False))
print("bat_ink_plain ", render(f"{OUT}/bat_ink_plain.png", color=(14, 27, 51), bones=False))
