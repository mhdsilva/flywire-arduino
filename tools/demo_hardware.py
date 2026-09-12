#!/usr/bin/env python3
"""Bench demo for the "Visible Reflex" project.

Lights each LED several times (to confirm colour and position) and then sweeps
the servo from end to end with all three LEDs on.

Usage:
    python tools/demo_hardware.py /dev/ttyACM0

Requires pyserial. Needs serial port access (dialout group).

NOTE: the firmware transmits "S ..." at 50 Hz continuously. If the host does not
read, the Uno's TX buffer fills and its loop blocks -- so here we drain the
reading at every step and use write_timeout so it never hangs.
"""

import argparse
import time

import serial

STAGES = [
    (1, 0, 0, "RED       -> pin 5 (sensory)"),
    (0, 1, 0, "YELLOW    -> pin 6 (interneuron)"),
    (0, 0, 1, "GREEN     -> pin 7 (motor)"),
]


def drain(ser: serial.Serial) -> None:
    """Discards what the Uno is transmitting (sensors) so the buffer does not clog."""
    n = ser.in_waiting
    if n:
        ser.read(n)


def send(ser: serial.Serial, sensory: int, inter: int, motor: int, angle: int) -> None:
    try:
        ser.write(f"L {sensory} {inter} {motor} {int(angle)}\n".encode())
    except serial.SerialTimeoutException:
        print("  !! write hung (did the board reset?)")
    drain(ser)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("port", help="serial port, e.g. /dev/ttyACM0")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--reps", type=int, default=3, help="how many times to blink each LED")
    args = ap.parse_args()

    ser = serial.Serial(args.port, args.baud, timeout=1, write_timeout=1)
    time.sleep(2.5)  # wait for the reset + self-test of the sketch

    try:
        print("1) each LED, one colour at a time...")
        for s, i, m, name in STAGES:
            print(f"     {name}")
            for _ in range(args.reps):
                send(ser, 0, 0, 0, 90)
                time.sleep(0.12)
                send(ser, s, i, m, 90)
                time.sleep(0.40)

        print("2) servo sweeping (3 LEDs on)...")
        angles = (
            list(range(90, 181, 10))
            + list(range(170, 9, -10))
            + list(range(20, 91, 10))
        )
        for a in angles:
            send(ser, 1, 1, 1, a)
            time.sleep(0.10)

        print("3) LEDs off, servo at 90.")
        send(ser, 0, 0, 0, 90)
        time.sleep(0.3)
        print("done.")
    finally:
        ser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
