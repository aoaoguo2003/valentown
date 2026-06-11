from pathlib import Path

from PIL import Image
from PIL import ImageDraw


ASSET_DIR = Path(__file__).resolve().parents[1] / "frontend" / "assets"
CHARACTERS = ["ron", "ella", "arthur", "mia", "emma", "gavin", "adam"]


def alpha_bounds(image):
    alpha = image.getchannel("A")
    return alpha.getbbox() or (0, 0, image.width, image.height)


def make_walk_frame(source, direction):
    image = source.convert("RGBA")
    bbox = alpha_bounds(image)
    subject = image.crop(bbox)

    canvas = Image.new("RGBA", image.size, (0, 0, 0, 0))
    crop_w, crop_h = subject.size
    split_y = int(crop_h * 0.62)
    split_x = crop_w // 2
    lower = subject.crop((0, split_y, crop_w, crop_h))
    lower_left = lower.crop((0, 0, split_x + 2, lower.height))
    lower_right = lower.crop((split_x - 2, 0, lower.width, lower.height))

    x0, y0 = bbox[0], bbox[1]
    canvas.alpha_composite(subject, (x0 + int(1.2 * direction), y0 - 1))

    lower_y = y0 + split_y + 1

    lead_dx = int(-6 * direction)
    trail_dx = int(5 * direction)
    lead_dy = 9
    trail_dy = -2

    lead_leg = lower_left.copy()
    trail_leg = lower_right.copy()
    lead_leg.putalpha(lead_leg.getchannel("A").point(lambda value: int(value * 0.96)))
    trail_leg.putalpha(trail_leg.getchannel("A").point(lambda value: int(value * 0.82)))

    canvas.alpha_composite(lead_leg, (x0 + lead_dx, lower_y + lead_dy))
    canvas.alpha_composite(trail_leg, (x0 + split_x - 2 + trail_dx, lower_y + trail_dy))

    # Add a small low-alpha foot echo so the alternating step reads clearly at in-game scale.
    foot_band_h = max(8, int(crop_h * 0.12))
    feet = subject.crop((0, crop_h - foot_band_h, crop_w, crop_h))
    feet_alpha = feet.getchannel("A").point(lambda value: int(value * 0.2))
    feet.putalpha(feet_alpha)
    canvas.alpha_composite(feet, (x0 + int(7 * direction), y0 + crop_h - foot_band_h + 4))
    draw_step_feet(canvas, subject, bbox, direction)

    return canvas


def sample_shoe_color(subject):
    crop_w, crop_h = subject.size
    bottom = subject.crop((0, int(crop_h * 0.74), crop_w, crop_h))
    pixels = [
        pixel
        for pixel in bottom.getdata()
        if pixel[3] > 120 and (pixel[0] + pixel[1] + pixel[2]) < 260
    ]
    if not pixels:
        return (56, 54, 52, 255)

    pixels.sort(key=lambda pixel: pixel[0] + pixel[1] + pixel[2])
    return pixels[len(pixels) // 3]


def draw_step_feet(canvas, subject, bbox, direction):
    crop_w, crop_h = subject.size
    x0, y0, _, _ = bbox
    shoe_color = sample_shoe_color(subject)
    outline = (38, 38, 38, 220)
    draw = ImageDraw.Draw(canvas)

    foot_w = max(12, int(crop_w * 0.16))
    foot_h = max(8, int(crop_h * 0.045))
    center_x = x0 + (crop_w / 2)
    base_y = y0 + crop_h - foot_h
    lead_x = center_x - (foot_w / 2) + (direction * crop_w * 0.18)
    trail_x = center_x - (foot_w / 2) - (direction * crop_w * 0.12)

    draw.rectangle(
        [lead_x, base_y + foot_h * 0.45, lead_x + foot_w, base_y + foot_h * 1.45],
        fill=shoe_color,
        outline=outline
    )
    draw.rectangle(
        [trail_x, base_y - foot_h * 0.2, trail_x + foot_w * 0.85, base_y + foot_h * 0.65],
        fill=tuple(int(channel * 0.82) if index < 3 else channel for index, channel in enumerate(shoe_color)),
        outline=outline
    )


def main():
    for name in CHARACTERS:
        source_path = ASSET_DIR / f"{name}.png"
        source = Image.open(source_path)

        for suffix, direction in [("walk1", -1), ("walk2", 1)]:
            frame = make_walk_frame(source, direction)
            frame.save(ASSET_DIR / f"{name}_{suffix}.png")
            print(f"wrote {name}_{suffix}.png")


if __name__ == "__main__":
    main()
