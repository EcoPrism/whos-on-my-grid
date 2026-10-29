"""The share card as a 1200x630 PNG, drawn with Pillow: no browser in the
container. The layout mirrors web/src/components/ShareCard.tsx, whose sizes
are percentages of the card width (cqw); here 1cqw is 12 px. Keep the two in
step. Deterministic: fixed fonts, no timestamps, so one spec is one byte string."""

import io
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from app.card.spec import CardSpec

W, H = 1200, 630
CQW = W / 100

# web/src/index.css tokens.
INK, PAPER, SIGNAL = "#15202b", "#eef0f2", "#ffc300"

FONT = Path(__file__).parent / "fonts" / "Archivo-Variable.ttf"
# The variable font's axes, as the CSS sets them: body 100, .sign 68, .wide 118.
WDTH_BODY, WDTH_SIGN, WDTH_WIDE = 100, 68, 118

PAD = round(4.5 * CQW)  # p-[4.5%]: CSS padding percentages are of the width
BAND_PAD = round(0.6 * CQW)
GAP = 24  # gap-6
HYPOTHETICAL = "HYPOTHETICAL · modelled, not measured"
WORDMARK = "Who's on my grid"

Font = ImageFont.FreeTypeFont


@lru_cache(maxsize=64)
def font(size: int, weight: int = 400, width: int = WDTH_BODY) -> Font:
    f = ImageFont.truetype(str(FONT), size)
    # Axis order in the file: Weight, Width.
    f.set_variation_by_axes([weight, width])
    return f


def mix(fg: str, bg: str, alpha: float) -> tuple[int, int, int]:
    """`opacity-80` on a flat background, without an alpha layer."""
    a = [int(fg[i : i + 2], 16) for i in (1, 3, 5)]
    b = [int(bg[i : i + 2], 16) for i in (1, 3, 5)]
    r, g, bl = (round(x * alpha + y * (1 - alpha)) for x, y in zip(a, b, strict=True))
    return r, g, bl


def wrap(text: str, f: Font, width: float) -> list[str]:
    """Greedy word wrap by measured width. A word longer than the line stands alone."""
    lines: list[str] = []
    line = ""
    for word in text.split():
        trial = f"{line} {word}" if line else word
        if line and f.getlength(trial) > width:
            lines.append(line)
            line = word
        else:
            line = trial
    if line:
        lines.append(line)
    return lines


def ellipsize(text: str, f: Font, width: float) -> str:
    if f.getlength(text) <= width:
        return text
    while text and f.getlength(text + "…") > width:
        text = text[:-1]
    return text.rstrip() + "…"


def line_height(f: Font, leading: float) -> int:
    return round(f.size * leading)


def _band(draw: ImageDraw.ImageDraw, top: int, text: str, f: Font, fill: str, ink: str) -> int:
    """A full-width band of small type; returns its height. Drawn only when
    `top` is not negative, so it can be measured first."""
    lines = wrap(text, f, W - 2 * PAD)
    lh = line_height(f, 1.25)
    height = 2 * BAND_PAD + lh * len(lines)
    if top >= 0:
        draw.rectangle([0, top, W, top + height - 1], fill=fill)
        for i, line in enumerate(lines):
            draw.text((PAD, top + BAND_PAD + i * lh), line, font=f, fill=ink)
    return height


def fit_title(text: str, width: float) -> tuple[Font, list[str]]:
    """The place as a street sign: steps down in size until it wraps to two
    lines. Still longer at the smallest size, the second line ends in an
    ellipsis, so a dropped state code shows it was cut."""
    size = round(9 * CQW)
    while True:
        sign = font(size, 800, WDTH_SIGN)
        lines = wrap(text, sign, width)
        if len(lines) <= 2 or size <= round(5 * CQW):
            break
        size -= 6
    if len(lines) > 2:
        lines = [lines[0], " ".join(lines[1:])]
    return sign, [ellipsize(line, sign, width) for line in lines]


def render_png(spec: CardSpec) -> bytes:
    """Deterministic: same spec, same bytes (fixed fonts, no timestamps in the PNG)."""
    img = Image.new("RGB", (W, H), INK)
    draw = ImageDraw.Draw(img)
    small = font(round(1.8 * CQW))

    # Bands first: the ink panel is what is left between them.
    top = 0
    if spec.hypothetical:
        top = _band(draw, 0, HYPOTHETICAL, font(round(1.8 * CQW), 700, WDTH_WIDE), SIGNAL, INK)
    bottom = H - _band(draw, -1, spec.disclosure, small, PAPER, INK)
    _band(draw, bottom, spec.disclosure, small, PAPER, INK)
    panel_h = bottom - top

    # Top row: the place as a street sign, the wordmark to its right. A long
    # place name steps down in size until it fits on two lines.
    mark = font(round(2.6 * CQW), 600, WDTH_WIDE)
    mark_w = mark.getlength(WORDMARK)
    draw.text((W - PAD, top + PAD), WORDMARK, font=mark, fill=PAPER, anchor="ra")
    title_w = W - 2 * PAD - mark_w - GAP
    sign, title = fit_title(spec.title, title_w)
    lh = line_height(sign, 0.92)
    for i, line in enumerate(title):
        draw.text((PAD, top + PAD + i * lh), line, font=sign, fill=PAPER, anchor="la")
    title_bottom = top + PAD + lh * len(title)

    # Bottom row: the big number in signal on the right, its caption wrapped to
    # the number's width; the lines take what is left, at most 62% of the row.
    row_bottom = top + panel_h - PAD
    right_w = 0.0
    if spec.big:
        big = font(round(8.5 * CQW), 800)
        cap = font(round(2.4 * CQW))
        right_w = max(big.getlength(spec.big), 0.38 * (W - 2 * PAD))
        cap_lines = wrap(spec.big_caption, cap, right_w) if spec.big_caption else []
        right_w = max([big.getlength(spec.big)] + [cap.getlength(c) for c in cap_lines])
        cap_lh = line_height(cap, 1.3)
        cap_y = row_bottom - cap_lh * len(cap_lines)
        for i, line in enumerate(cap_lines):
            draw.text(
                (W - PAD, cap_y + i * cap_lh),
                line,
                font=cap,
                fill=mix(PAPER, INK, 0.8),
                anchor="ra",
            )
        draw.text((W - PAD, cap_y), spec.big, font=big, fill=SIGNAL, anchor="rd")

    col = 0.62 * (W - 2 * PAD)
    if right_w:
        col = min(col, W - 2 * PAD - right_w - GAP)
    room = row_bottom - title_bottom - GAP
    gap = round(0.8 * CQW)
    # Step the type down until the lines fit under the title; drop the last
    # line only when even the smallest size does not.
    lines = list(spec.lines)
    while True:
        for size in (round(2.9 * CQW), 32, 29, 26, 24):
            body = font(size)
            lh = line_height(body, 1.25)
            blocks = [wrap(line, body, col) for line in lines]
            height = sum(lh * len(blk) for blk in blocks) + gap * max(0, len(blocks) - 1)
            if height <= room:
                break
        if height <= room or len(lines) <= 1:
            break
        lines.pop()
    y = row_bottom - height
    for block in blocks:
        for line in block:
            draw.text((PAD, y), line, font=body, fill=PAPER)
            y += lh
        y += gap

    # Sources, small and dim, 2% above the bottom of the ink panel.
    if spec.footer:
        foot = ellipsize(spec.footer, small, W - 2 * PAD)
        draw.text(
            (PAD, top + panel_h - round(0.02 * panel_h) - line_height(small, 1.25)),
            foot,
            font=small,
            fill=mix(PAPER, INK, 0.6),
        )

    out = io.BytesIO()
    img.save(out, format="PNG", optimize=False)
    return out.getvalue()
