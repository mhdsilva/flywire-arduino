#!/usr/bin/env python3
"""Generate the FlyWire-on-Arduino wiring schematic.

This script draws the bench wiring for the project and writes:

    docs/schematic.svg   (primary, drawn with the native schemdraw SVG backend)
    docs/schematic.png   (bonus, drawn with the schemdraw matplotlib backend)

It is deterministic and self-contained.  Install the drawing library once:

    .venv/bin/pip install schemdraw        # + matplotlib for the PNG

then run:

    .venv/bin/python docs/make_schematic.py

The pin assignment is the source of truth from board/flywire/flywire.ino:

    D9  servo signal          A0  LDR divider   (--sensor ldr)
    D5  red LED  (sensory)    A1  NTC divider   (optional)
    D6  yellow LED (inter)    A2  pot wiper     (--sensor pot)
    D7  green LED (motor)     D8  active buzzer (optional)
    D2  push-button to GND    (optional, uses the internal pull-up)

Signals that cannot be drawn as one continuous wire use matching net labels
("A0", "A1", "A2"); power nets use +5V / GND symbols.  Equal labels are the
same electrical node.
"""

from __future__ import annotations

import os
import sys
import xml.etree.ElementTree as ET

import schemdraw
import schemdraw.elements as elm

# ---------------------------------------------------------------------------
# Layout constants (schemdraw units, y grows upwards)
# ---------------------------------------------------------------------------

UNO_X1, UNO_Y1 = -1.0, -4.0
UNO_X2, UNO_Y2 = 15.0, 24.0

# Right-hand pin rows.  Names and functions match the firmware pin constants.
PIN_RIGHT = [
    ("D9", 22.0, "servo signal"),
    ("D5", 19.5, "red LED"),
    ("D6", 17.0, "yellow LED"),
    ("D7", 14.5, "green LED"),
    ("D8", 12.0, "buzzer"),
    ("D2", 9.5, "button"),
    ("A0", 6.0, "LDR / --sensor ldr"),
    ("A1", 3.5, "NTC (optional)"),
    ("A2", 1.0, "pot / --sensor pot"),
]
STUB = 5.0          # length of the labelled pin stub leaving the Uno
LABEL_GAP = 0.6

# Colours used for the three neural stages.
RED = "#c0392b"
YELLOW = "#9a7d0a"
GREEN = "#1e8449"

# Analog sensor band, drawn below the Uno to keep the digital rows uncluttered.
SENSOR_TOP = -6.0
SENSOR_MID = -12.0
SENSOR_BOT = -18.0

# X coordinate where the A0 / A2 nets end so the decoupling caps can tap them.
A0_NET_END = 16.0
A2_NET_END = 52.0


# ---------------------------------------------------------------------------
# Small drawing helpers
# ---------------------------------------------------------------------------

def wire(dwg: schemdraw.Drawing, *points) -> None:
    """Draw a polyline through `points` (each an (x, y) tuple)."""
    for a, b in zip(points, points[1:]):
        dwg += elm.Line().at(a).to(b)


def box(dwg: schemdraw.Drawing, x1: float, y1: float, x2: float, y2: float) -> None:
    """Draw an axis-aligned rectangle from absolute drawing coordinates."""
    wire(dwg, (x1, y1), (x2, y1), (x2, y2), (x1, y2), (x1, y1))


def dot(dwg: schemdraw.Drawing, point) -> None:
    """Draw a filled junction dot."""
    dwg += elm.Dot().at(point)


def text(dwg: schemdraw.Drawing, point, s: str, size: float = 9.0,
         color: str = "black", halign: str = "center") -> None:
    """Place a standalone text label."""
    dwg += elm.Label().at(point).label(s, fontsize=size, color=color, halign=halign)


def pin_stub(dwg: schemdraw.Drawing, x: float, y: float, name: str, note: str = "") -> None:
    """A short line leaving the right edge of the Uno, with a net name."""
    dwg += elm.Line().at((x, y)).to((x + STUB, y))
    text(dwg, (x + STUB + LABEL_GAP, y + 0.1), name, size=9.0, halign="left")
    if note:
        text(dwg, (x + STUB + LABEL_GAP, y - 1.2), note, size=5.8,
             color="#666666", halign="left")


# ---------------------------------------------------------------------------
# Subsystems
# ---------------------------------------------------------------------------

def draw_uno(dwg: schemdraw.Drawing) -> None:
    box(dwg, UNO_X1, UNO_Y1, UNO_X2, UNO_Y2)
    cx = (UNO_X1 + UNO_X2) / 2
    text(dwg, (cx, 15.5), "ARDUINO", size=12.0)
    text(dwg, (cx, 13.0), "UNO R3 (DIP)", size=9.0)
    text(dwg, (cx, 10.5), "Eletrogate Kit Start", size=6.5, color="#555555")
    text(dwg, (cx, 8.5), "USB -> laptop", size=6.5, color="#555555")

    for name, y, note in PIN_RIGHT:
        pin_stub(dwg, UNO_X2, y, name, note)

    # Power pins of the Uno itself.  The board is USB powered, so these are the
    # rails everything else taps into.
    dwg += elm.Line().at((UNO_X1, 20.0)).to((UNO_X1 - 5.0, 20.0))
    text(dwg, (UNO_X1 - 5.6, 20.0), "+5V", size=9.0, halign="right")
    dwg += elm.Line().at((UNO_X1, -2.0)).to((UNO_X1 - 5.0, -2.0))
    text(dwg, (UNO_X1 - 5.6, -2.0), "GND", size=9.0, halign="right")


def draw_servo(dwg: schemdraw.Drawing) -> None:
    x1, y1, x2, y2 = 32.0, 21.0, 46.0, 29.0
    box(dwg, x1, y1, x2, y2)
    text(dwg, ((x1 + x2) / 2, 25.6), "SG90", size=10.0)
    text(dwg, ((x1 + x2) / 2, 23.9), "micro servo", size=6.5, color="#555555")

    # signal -> D9 ; the firmware attaches the servo on pin 9.
    wire(dwg, (UNO_X2 + STUB, 22.0), (25.0, 22.0), (25.0, 27.0), (x1, 27.0))
    text(dwg, (27.0, 27.7), "signal (orange) -> D9", size=6.0, halign="left")

    # VCC / GND into their own labelled rails.
    dwg += elm.Line().at((x1, 25.0)).to((28.0, 25.0))
    text(dwg, (27.5, 25.6), "+5V", size=7.5, halign="right")
    dwg += elm.Line().at((x1, 23.0)).to((28.0, 23.0))
    text(dwg, (27.5, 23.6), "GND", size=7.5, halign="right")


def draw_led(dwg: schemdraw.Drawing, y: float, color: str, name: str, stage: str) -> None:
    """One LED branch: pin -> 330 ohm -> LED anode -> cathode -> GND."""
    x0 = UNO_X2 + STUB
    wire(dwg, (x0, y), (23.0, y))
    dwg += elm.Resistor().at((23.0, y)).right().length(6.0).label(
        "330 Ω", loc="top", fontsize=6.5)
    wire(dwg, (29.0, y), (31.0, y))
    dwg += elm.LED().at((31.0, y)).right().length(4.0).color(color).label(
        name, loc="top", fontsize=6.5, color=color)
    # The cathode joins the shared ground bus at x=37 (bus drawn once below).
    wire(dwg, (35.0, y), (37.0, y))
    dot(dwg, (37.0, y))
    text(dwg, (39.5, y - 1.0), stage, size=6.0, color=color, halign="left")


def draw_led_ground_bus(dwg: schemdraw.Drawing) -> None:
    """Single ground rail shared by the three LED cathodes."""
    wire(dwg, (37.0, 19.5), (37.0, 13.0))
    dwg += elm.Ground().at((37.0, 13.0))


def draw_buzzer(dwg: schemdraw.Drawing) -> None:
    y = 12.0
    x0 = UNO_X2 + STUB
    wire(dwg, (x0, y), (22.0, y))
    box(dwg, 22.0, y - 1.6, 28.0, y + 1.6)
    text(dwg, (25.0, y + 0.2), "BUZ", size=7.0)
    text(dwg, (23.3, y - 1.0), "+", size=7.0)
    wire(dwg, (28.0, y), (31.0, y), (31.0, y - 1.5))
    dwg += elm.Ground().at((31.0, y - 1.5))
    text(dwg, (33.0, y), "(optional) active buzzer D8", size=6.0,
         color="#666666", halign="left")


def draw_button(dwg: schemdraw.Drawing) -> None:
    y = 9.5
    x0 = UNO_X2 + STUB
    wire(dwg, (x0, y), (22.0, y))
    dwg += elm.Button().at((22.0, y)).right().length(4.0).label(
        "button", loc="top", fontsize=6.5)
    wire(dwg, (26.0, y), (29.0, y), (29.0, y - 1.5))
    dwg += elm.Ground().at((29.0, y - 1.5))
    text(dwg, (31.5, y + 0.4), "(optional) D2 -> GND", size=6.0,
         color="#666666", halign="left")
    text(dwg, (31.5, y - 1.0), "INPUT_PULLUP", size=5.8, color="#666666",
         halign="left")


def draw_ldr(dwg: schemdraw.Drawing) -> None:
    x = 6.0
    dwg += elm.Vdd().at((x, SENSOR_TOP)).label("+5V", loc="top", fontsize=6.5)
    dwg += elm.Photoresistor().at((x, SENSOR_TOP)).down().length(6.0)
    text(dwg, (x - 3.8, SENSOR_TOP - 3.2), "LDR", size=6.5, halign="right")
    dot(dwg, (x, SENSOR_MID))
    # The A0 net runs right to the labelled stub and the 100 nF decoupling cap.
    wire(dwg, (x, SENSOR_MID), (A0_NET_END, SENSOR_MID))
    text(dwg, (11.0, SENSOR_MID + 1.0), "A0", size=8.0, halign="left")
    dwg += elm.Resistor().at((x, SENSOR_MID)).down().length(6.0)
    text(dwg, (x - 1.2, SENSOR_MID - 3.2), "10 kΩ", size=6.5, halign="right")
    dwg += elm.Ground().at((x, SENSOR_BOT))
    text(dwg, (11.0, SENSOR_MID - 1.4), "--sensor ldr", size=6.0,
         color="#555555", halign="left")
    text(dwg, (x - 1.0, SENSOR_TOP + 1.6), "LDR divider", size=7.5, halign="left")


def draw_ntc(dwg: schemdraw.Drawing) -> None:
    x = 24.0
    dwg += elm.Vdd().at((x, SENSOR_TOP)).label("+5V", loc="top", fontsize=6.5)
    dwg += elm.Thermistor().at((x, SENSOR_TOP)).down().length(6.0)
    text(dwg, (x - 3.8, SENSOR_TOP - 3.2), "NTC 10 kΩ", size=6.5, halign="right")
    dot(dwg, (x, SENSOR_MID))
    wire(dwg, (x, SENSOR_MID), (x + 6.0, SENSOR_MID))
    text(dwg, (x + 5.0, SENSOR_MID + 1.0), "A1", size=8.0, halign="left")
    dwg += elm.Resistor().at((x, SENSOR_MID)).down().length(6.0)
    text(dwg, (x - 1.2, SENSOR_MID - 3.2), "10 kΩ", size=6.5, halign="right")
    dwg += elm.Ground().at((x, SENSOR_BOT))
    text(dwg, (x + 5.0, SENSOR_MID - 1.4), "(optional)", size=6.0,
         color="#555555", halign="left")


def draw_pot(dwg: schemdraw.Drawing) -> None:
    x = 42.0
    dwg += elm.Vdd().at((x, SENSOR_TOP)).label("+5V", loc="top", fontsize=6.5)
    dwg += elm.Potentiometer().at((x, SENSOR_TOP)).down().length(12.0)
    text(dwg, (x - 3.8, SENSOR_MID), "10 kΩ pot", size=6.5, halign="right")
    # The wiper (third terminal) taps the body at its midpoint.
    wire(dwg, (x + 1.2, SENSOR_MID), (A2_NET_END, SENSOR_MID))
    text(dwg, (x + 5.0, SENSOR_MID + 1.0), "A2", size=8.0, halign="left")
    dwg += elm.Ground().at((x, SENSOR_BOT))
    text(dwg, (x + 5.0, SENSOR_MID - 1.4), "--sensor pot", size=6.0,
         color="#555555", halign="left")
    text(dwg, (x - 2.0, SENSOR_TOP + 1.6), "10 kΩ potentiometer", size=7.5,
         halign="left")


def draw_decoupling(dwg: schemdraw.Drawing) -> None:
    # 100 nF ceramic from each analog input to GND.
    for x in (A0_NET_END, A2_NET_END):
        text(dwg, (x + 1.2, SENSOR_MID - 3.0), "100 nF", size=6.0, halign="left")
        dwg += elm.Capacitor().at((x, SENSOR_MID)).down().length(6.0)
        dwg += elm.Ground().at((x, SENSOR_BOT))

    # 100 uF electrolytic across 5V/GND, next to the servo (polarity marked).
    x = 52.0
    dwg += elm.Vdd().at((x, 31.0)).label("+5V", loc="top", fontsize=6.5)
    dwg += elm.Capacitor(polar=True).at((x, 31.0)).down().length(7.0).label(
        "100 µF", loc="right", fontsize=6.5)
    dwg += elm.Ground().at((x, 24.0))
    text(dwg, (x, 22.8), "bulk cap near servo", size=6.0, color="#555555")


def draw_notes(dwg: schemdraw.Drawing) -> None:
    text(dwg, (26.0, 33.0), "FlyWire on Arduino - bench wiring", size=13.0)
    text(dwg, (26.0, 31.0),
         "Serial 115200:  Uno->host  S <ldr> <ntc> <pot> <btn>   host->Uno  L <s> <i> <m> <angle> / B <freq>",
         size=6.5, color="#555555")
    text(dwg, (26.0, 29.8),
         "Pins match board/flywire/flywire.ino   |   matching A0/A1/A2 labels and all GND / +5V flags are the same net",
         size=6.5, color="#555555")


# ---------------------------------------------------------------------------
# Build / save
# ---------------------------------------------------------------------------

def build(canvas: str) -> schemdraw.Drawing:
    """Build the whole schematic on the requested schemdraw canvas."""
    dwg = schemdraw.Drawing(canvas=canvas, unit=2.4)
    draw_notes(dwg)
    draw_uno(dwg)
    draw_servo(dwg)
    draw_led(dwg, 19.5, RED, "RED", "sensory")
    draw_led(dwg, 17.0, YELLOW, "YELLOW", "interneuron")
    draw_led(dwg, 14.5, GREEN, "GREEN", "motor (Giant Fiber)")
    draw_led_ground_bus(dwg)
    draw_buzzer(dwg)
    draw_button(dwg)
    draw_ldr(dwg)
    draw_ntc(dwg)
    draw_pot(dwg)
    draw_decoupling(dwg)
    return dwg


def main() -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    svg_path = os.path.join(here, "schematic.svg")
    png_path = os.path.join(here, "schematic.png")

    build("svg").save(svg_path)

    # Fail loudly if the generated SVG is not well-formed XML.
    ET.parse(svg_path)
    print("SVG parses as well-formed XML")

    try:  # PNG is a bonus; only attempted when the matplotlib backend is present.
        build("matplotlib").save(png_path, dpi=150)
    except Exception as exc:  # pragma: no cover - environment dependent
        print(f"PNG rendering skipped: {exc}", file=sys.stderr)
        png_path = None

    for path in (svg_path, png_path):
        if path and os.path.exists(path):
            print(f"wrote {path} ({os.path.getsize(path)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
