#!/usr/bin/env python3
"""Generate the article cover: a dark code-editor card with the real loop.

Reproducible: `.venv/bin/python docs/make_cover.py` -> docs/cover.png
LinkedIn article cover, 1200x644. The snippet is taken from brain/run_brain.py
(the names are real: load_circuit, LIF, weight_scale, DT, filt, step_ms, send).
"""

from __future__ import annotations

import os
import re

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))

W, H = 1200, 644
BG_TOP, BG_BOTTOM = (13, 17, 23), (1, 4, 9)      # #0d1117 -> #010409
WIN_BG = (22, 27, 34)                            # #161b22
WIN_BORDER = (48, 54, 61)                        # #30363d
F_NAME = "brain/run_brain.py"
FOOTER = "github.com/mhdsilva/flywire-arduino"

COL = {
    "text": (201, 209, 217),
    "comment": (139, 148, 158),
    "keyword": (255, 123, 114),
    "string": (165, 214, 255),
    "number": (121, 192, 255),
    "func": (210, 168, 255),
    "linenum": (72, 79, 88),
    "title": (110, 118, 129),
    "footer": (139, 148, 158),
}

CODE = [
    "# FlyWire FAFB v783 - a real looming -> escape circuit",
    '# LC4 + LPLC2 (314) -> interneurons -> DNp01 "Giant Fiber"',
    "",
    "W, roles, _ = load_circuit()     # 583 neurons, 4,799 real synapses",
    "net = LIF(W, roles, weight_scale=WEIGHT_SCALE, dt=DT)",
    "",
    "# every 20 ms over serial: the flashlight approaching",
    "stim = filt.update(raw, CHUNK_MS / 1000.0)",
    "ext[sens] = stim * STIM_GAIN",
    "counts = step_ms(net, ext, CHUNK_MS)",
    "",
    "# did the Giant Fiber fire? then - and only then - the wings move",
    "mspikes = int(counts[motor].sum())",
    "angle = fly.update(now, CHUNK_MS / 1000.0, mspikes)",
    "send(ser, led_sens, led_inter, mspikes, angle)",
]

KEYWORDS = {
    "def", "class", "if", "else", "elif", "for", "while", "return", "import",
    "from", "in", "not", "and", "or", "is", "None", "True", "False", "self",
    "lambda", "with", "as", "pass", "break", "continue",
}
TOKEN = re.compile(r'("[^"]*"|\'[^\']*\'|\b\d[\d_,.]*\b|\b[A-Za-z_]\w*\b|\s+|.)')


def mono(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    base = "/usr/share/fonts/truetype/dejavu/"
    name = "DejaVuSansMono-Bold.ttf" if bold else "DejaVuSansMono.ttf"
    return ImageFont.truetype(base + name, size)


def tokenize(code: str) -> list[tuple[str, str]]:
    """Split a code line into (text, colour-key) tokens."""
    out: list[tuple[str, str]] = []
    toks = TOKEN.findall(code)
    for i, tok in enumerate(toks):
        if tok.startswith(('"', "'")):
            key = "string"
        elif tok and tok[0].isdigit():
            key = "number"
        elif tok in KEYWORDS:
            key = "keyword"
        elif tok.isidentifier():
            nxt = next((t for t in toks[i + 1:] if t.strip()), "")
            key = "func" if nxt.startswith("(") else "text"
        else:
            key = "text"
        out.append((tok, key))
    return out


def main() -> int:
    img = Image.new("RGB", (W, H), BG_TOP)
    d = ImageDraw.Draw(img)

    # vertical background gradient
    for y in range(H):
        t = y / (H - 1)
        d.line([(0, y), (W, y)], fill=tuple(
            round(a + (b - a) * t) for a, b in zip(BG_TOP, BG_BOTTOM)))

    f_code = mono(23)
    f_small = mono(16)
    f_footer = mono(17)
    cw = f_code.getlength("M")          # monospace advance
    lh = 30

    # code window geometry (computed from the content)
    pad = 26
    gutter = int(cw * 3)                # room for line numbers
    code_w = int(max(f_code.getlength(ln) for ln in CODE) + gutter + cw * 3)
    win_w = min(W - 120, code_w + pad * 2)
    title_h = 40
    win_h = title_h + pad * 2 + lh * len(CODE)
    wx, wy = (W - win_w) // 2, (H - win_h) // 2 - 18

    d.rounded_rectangle([wx, wy, wx + win_w, wy + win_h],
                        radius=12, fill=WIN_BG, outline=WIN_BORDER, width=1)
    # title bar
    d.line([(wx + 1, wy + title_h), (wx + win_w - 1, wy + title_h)], fill=WIN_BORDER)
    for i, c in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
        cx = wx + 22 + i * 20
        d.ellipse([cx, wy + 15, cx + 11, wy + 26], fill=c)
    d.text((wx + 90, wy + 12), F_NAME, font=f_small, fill=COL["title"])

    # code
    y = wy + title_h + pad
    for n, line in enumerate(CODE, start=1):
        d.text((wx + pad + gutter - int(cw * 2.2), y + 2), str(n),
               font=f_small, fill=COL["linenum"])
        x = wx + pad + gutter
        if "#" in line:
            idx = line.index("#")
            code_part, comment = line[:idx], line[idx:]
        else:
            code_part, comment = line, ""
        for tok, key in tokenize(code_part):
            d.text((x, y), tok, font=f_code, fill=COL[key])
            x += f_code.getlength(tok)
        if comment:
            d.text((x, y), comment, font=f_code, fill=COL["comment"])
        y += lh

    d.text(((W - f_footer.getlength(FOOTER)) / 2, wy + win_h + 26),
           FOOTER, font=f_footer, fill=COL["footer"])

    out = os.path.join(HERE, "cover.png")
    img.save(out)
    print(f"saved {out}  ({W}x{H}, {os.path.getsize(out) / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
