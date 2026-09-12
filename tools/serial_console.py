#!/usr/bin/env python3
"""Serial console for the FlyWire-on-Arduino bench test.

Reads the sensors the Uno transmits and (optionally) commands servo/LEDs.

Usage:
    python tools/serial_console.py /dev/ttyACM0
    python tools/serial_console.py /dev/ttyACM0 --sweep

Requires pyserial:  pip install pyserial
"""

import argparse
import math
import sys
import time

import serial


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("port", help="serial port, e.g. /dev/ttyACM0")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument(
        "--sweep",
        action="store_true",
        help="ignores the sensors and sends the servo sweeping via the L command",
    )
    args = ap.parse_args()

    ser = serial.Serial(args.port, args.baud, timeout=1)
    time.sleep(2)  # the Uno resets when the port opens; wait for it to come back

    if args.sweep:
        print("sweeping servo + LEDs... Ctrl-C to quit")
        t0 = time.time()
        try:
            while True:
                t = time.time() - t0
                ang = int(90 + 80 * math.sin(t * 2.0))
                sensory = 1 if math.sin(t * 2.0) > 0 else 0
                motors = 1 if math.sin(t * 2.0) < 0 else 0
                ser.write(f"L {sensory} 0 {motors} {ang}\n".encode())
                time.sleep(0.05)
        except KeyboardInterrupt:
            pass
        finally:
            ser.write(b"L 0 0 0 90\n")
            ser.close()
        return 0

    print(f"reading {args.port} @ {args.baud}... Ctrl-C to quit")
    try:
        for raw in ser:
            line = raw.decode(errors="replace").strip()
            if not line:
                continue
            if line.startswith("S "):
                parts = line.split()
                if len(parts) == 5:
                    _, ldr, ntc, pot, btn = parts
                    print(f"LDR={ldr:>4}  NTC={ntc:>4}  POT={pot:>4}  BTN={btn}")
            else:
                print(line)
    except KeyboardInterrupt:
        pass
    finally:
        ser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
