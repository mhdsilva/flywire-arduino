#!/usr/bin/env python3
"""Experiment 4 -- latency: how fast is the physical loop, and where does the time go?

The design document ([`docs/EXPERIMENTS.md`](../docs/EXPERIMENTS.md) section 4)
insists on keeping two latencies apart:

* **in-silico neural latency** -- pulse onset to the first DNp01 spike, in
  *simulated* milliseconds (from ``harness.run_trial``);
* **hardware loop latency** -- sensor sample to serial round trip to servo
  command, in *wall-clock* milliseconds.

This runner measures the hardware side on the real board and reports the budget
honestly. Every number in the printed budget table is labelled ``measured`` or
``derived``:

1. **Serial round trip (ping).** Send ``P``; the firmware replies immediately
   with ``P <micros()>``. We time host write -> reply for ``--pings`` repeats.
   This is host -> Uno -> host over USB, *including* the Uno's loop latency.
2. **Sensor sampling period and jitter.** Timestamp the arrival of every ``S``
   line for a few seconds. The firmware samples at 50 Hz (~20 ms), so the
   interval *jitter* is the finding. This measures arrival at the host, so it
   also contains USB and host-scheduling jitter.
3. **Host processing per loop iteration.** ``read S -> filter -> one 20 ms
   network chunk -> write L``, the same work ``run_brain.port_loop`` does, using
   the real circuit and the real ``step_ms``.
4. **In-silico neural latency** (no hardware): ``run_trial(amp)["first_spike_ms"]``
   at the baseline amplitude, for comparison.
5. **Servo mechanical estimate** (derived, not measured): the time for a 50 deg
   move at ``run_brain.SERVO_SPEED_DPS``. This is derived from the *command slew
   limit*; the real SG90 has its own dynamics that are not measured here.

Output: ``experiments/results/latency.csv`` (raw ping round trips and S
intervals) and a printed budget table. If no board is present the runner exits
with a clear message instead of crashing; the in-silico number is still printed
first, because it needs no hardware.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
import time

import numpy as np

try:
    import serial  # pyserial
except ImportError:  # allows running / inspecting without pyserial
    serial = None

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from harness import (  # noqa: E402
    DEFAULT_AMP,
    DT,
    LIF,
    STIM_GAIN,
    WEIGHT_SCALE,
    ensure_results_dir,
    load_circuit,
    run_trial,
    step_ms,
)
from run_brain import (  # noqa: E402
    CHUNK_MS,
    SERVO_SPEED_DPS,
    SENSORS,
    FlightBehavior,
    LoomingFilter,
)

DEFAULT_PORT = "/dev/ttyACM0"
DEFAULT_BAUD = 115200
DEFAULT_PINGS = 100
DEFAULT_S_SAMPLES = 150          # ~3 s of S lines at 50 Hz
DEFAULT_LOOP_ITERS = 100         # ~2 s of 20 ms chunks
SERVO_MOVE_DEG = 50.0            # the commanded move used for the derived estimate
SENSOR_SAMPLE_MS = CHUNK_MS      # the Uno cadence the firmware targets: 20 ms


def describe(values):
    """min / mean / sd / p95 / max in one dict, or ``None`` if there are none."""
    a = np.asarray(values, dtype=np.float64)
    if a.size == 0:
        return None
    return {
        "n": int(a.size),
        "min": float(a.min()),
        "mean": float(a.mean()),
        "sd": float(a.std(ddof=0)),
        "p95": float(np.percentile(a, 95)),
        "max": float(a.max()),
    }


def fmt(stats, unit="ms"):
    if stats is None:
        return "not measured"
    return (f"n={stats['n']}  min={stats['min']:.3f}  mean={stats['mean']:.3f}  "
            f"sd={stats['sd']:.3f}  p95={stats['p95']:.3f}  max={stats['max']:.3f} {unit}")


def open_board(port, baud):
    """Open the Uno and wait out the reset + boot self-test.

    Opening the port resets the board, but the host can still read a stale ``S``
    line from the pre-reset session, so a ready-signal check is not reliable.
    We sleep out the self-test, then let ``wait_for_ping`` keep retrying until
    the board answers."""
    ser = serial.Serial(port, baud, timeout=0.2, write_timeout=1)
    time.sleep(2.5)
    ser.reset_input_buffer()
    return ser


def read_line(ser):
    try:
        return ser.readline()
    except (OSError, serial.SerialException):
        return b""


def ping_once(ser, max_lines=50):
    """One host -> Uno -> host round trip, in ms. Returns ``(ms, arduino_us)``."""
    ser.reset_input_buffer()
    t0 = time.perf_counter()
    try:
        ser.write(b"P\n")
    except (OSError, serial.SerialException):
        return None, None
    for _ in range(max_lines):
        line = read_line(ser)
        if line.startswith(b"P "):
            t1 = time.perf_counter()
            try:
                arduino_us = int(line.split()[1])
            except (IndexError, ValueError):
                arduino_us = None
            return (t1 - t0) * 1000.0, arduino_us
    return None, None


def wait_for_ping(ser, timeout_s):
    """Return the first successful round trip after boot, or ``None``.

    The board resets when the port opens and the first ``P`` can race the end
    of the self-test; retrying until one succeeds both warms the link and
    detects firmware that does not implement ``P`` at all."""
    deadline = time.perf_counter() + timeout_s
    while time.perf_counter() < deadline:
        ms, _us = ping_once(ser)
        if ms is not None:
            return ms
    return None


def measure_pings(ser, n, max_misses=5):
    """Round trips in ms. Stops early if the board never answers ``P`` (old
    firmware): a missing ``P`` must not turn into a long silent hang."""
    rtts = []
    misses = 0
    for _ in range(n):
        ms, _us = ping_once(ser)
        if ms is None:
            misses += 1
            if misses >= max_misses:
                break
            continue
        misses = 0
        rtts.append(ms)
    return rtts


def measure_s_intervals(ser, n_samples, timeout_s):
    """Arrival times of consecutive ``S`` lines at the host, as intervals in ms."""
    ser.reset_input_buffer()
    stamps = []
    deadline = time.perf_counter() + timeout_s
    while len(stamps) < n_samples and time.perf_counter() < deadline:
        line = read_line(ser)
        if line.startswith(b"S "):
            stamps.append(time.perf_counter())
    return (np.diff(np.asarray(stamps)) * 1000.0).tolist()


def measure_host_loop(ser, n_iters):
    """Time ``read S -> filter -> 20 ms chunk -> write L``, as ``port_loop`` does.

    The clock starts as soon as a complete ``S`` line is in hand and stops when
    the ``L`` write returns: it is the host's per-iteration work, not the wait
    for the next sensor sample.
    """
    W, roles, _node_types, _node_ids = load_circuit()
    net = LIF(W, roles, weight_scale=WEIGHT_SCALE, dt=DT)
    net.reset()
    sens = roles == "sensory"
    inter = roles == "inter"
    motor = roles == "motor"
    ext = np.zeros(net.n)

    cfg = SENSORS["pot"]
    field = cfg["field"]
    filt = LoomingFilter(direction=cfg["direction"],
                         level_w=cfg["level_w"], dead=cfg["dead"])
    fly = FlightBehavior(motor_neurons=int(motor.sum()))

    times = []
    ser.reset_input_buffer()
    deadline = time.perf_counter() + 5.0 + n_iters * (CHUNK_MS / 1000.0)
    while len(times) < n_iters and time.perf_counter() < deadline:
        line = read_line(ser)
        if not line.startswith(b"S "):
            continue
        parts = line.split()
        if len(parts) != 5:
            continue
        try:
            raw = float(parts[field])
        except ValueError:
            continue

        # --- timed region: the same work the real port loop does per sample ---
        t0 = time.perf_counter()
        now = time.time()
        stim = filt.update(raw, CHUNK_MS / 1000.0)
        if fly.input_blocked(now):
            stim = 0.0
        ext[sens] = stim * STIM_GAIN
        counts = step_ms(net, ext, CHUNK_MS)
        mspikes = int(counts[motor].sum())
        angle = fly.update(now, CHUNK_MS / 1000.0, mspikes)
        try:
            ser.write(f"L {1 if counts[sens].any() else 0} "
                      f"{1 if counts[inter].any() else 0} "
                      f"{1 if (mspikes or fly.flying) else 0} {int(angle)}\n".encode())
        except (OSError, serial.SerialException):
            pass
        t1 = time.perf_counter()
        # --- end timed region ---
        times.append((t1 - t0) * 1000.0)
    return times


def print_budget(ping, host, servo_ms):
    """Print the stage budget, labelling each number measured or derived."""
    rtt = ping["mean"] if ping is not None else None
    host_ms = host["mean"] if host is not None else None

    rows = []
    rows.append(("sensor sample wait",
                 "0.000 .. 20.000",
                 "derived (uniform; Uno cadence 50 Hz / 20 ms)"))
    if rtt is None:
        rows.append(("USB/serial each way", "not measured",
                     "measured ping unavailable"))
    else:
        rows.append(("USB/serial each way (x2)", f"{rtt / 2.0:.3f}",
                     f"derived from measured round trip {rtt:.3f} ms / 2"))
    if host_ms is None:
        rows.append(("host brain step (20 ms chunk)", "not measured",
                     "measured loop unavailable"))
    else:
        rows.append(("host brain step (20 ms chunk)", f"{host_ms:.3f}",
                     "measured (read S -> 20 ms chunk -> write L)"))
    rows.append(("Uno -> servo", "~0.000", "derived (negligible, same loop() turn)"))
    rows.append(("servo mechanical (%g deg)" % SERVO_MOVE_DEG, f"{servo_ms:.3f}",
                 f"derived from command slew limit {SERVO_SPEED_DPS:g} deg/s"))

    print("\n== Loop budget ==")
    print(f"{'stage':<34} {'value (ms)':<18} {'how'}")
    print("-" * 100)
    for stage, value, how in rows:
        print(f"{stage:<34} {value:<18} {how}")

    if rtt is not None and host_ms is not None:
        fixed = rtt + host_ms + servo_ms
        lo, hi = fixed, fixed + SENSOR_SAMPLE_MS
        print("-" * 100)
        print(f"{'TOTAL (incl. 0-20 ms sensor wait)':<34} "
              f"[{lo:.3f} .. {hi:.3f}]")
    else:
        print("-" * 100)
        print("TOTAL: not computed (a required measurement is missing)")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Latency experiment (design section 4)")
    ap.add_argument("--port", default=DEFAULT_PORT,
                    help=f"serial port (default {DEFAULT_PORT})")
    ap.add_argument("--baud", type=int, default=DEFAULT_BAUD)
    ap.add_argument("--pings", type=int, default=DEFAULT_PINGS,
                    help="serial round-trip repeats (default %(default)s)")
    ap.add_argument("--s-samples", type=int, default=DEFAULT_S_SAMPLES,
                    help="S lines to timestamp (default %(default)s, ~3 s)")
    ap.add_argument("--loop-iters", type=int, default=DEFAULT_LOOP_ITERS,
                    help="host loop iterations to time (default %(default)s)")
    ap.add_argument("--amp", type=float, default=DEFAULT_AMP,
                    help="in-silico baseline amplitude (default %(default)s)")
    args = ap.parse_args(argv)

    t_start = time.perf_counter()

    # --- 4. In-silico latency needs no hardware, so it always runs first. -----
    print("== In-silico neural latency (harness.run_trial) ==")
    trial = run_trial(args.amp)
    first = trial["first_spike_ms"]
    print(f"  amp={args.amp:g}  motor_spikes={trial['motor_spikes']}  "
          f"first_spike_ms={first}")
    print("  (simulated milliseconds; no hardware involved)")

    # --- Hardware guard: fail cleanly, never crash. --------------------------
    if serial is None:
        print("\nerror: pyserial is not installed; cannot measure hardware "
              "(pip install pyserial).")
        return 1
    if not os.path.exists(args.port):
        print(f"\nerror: no board at {args.port}. Expected an Arduino UNO "
              f"(VID:PID 2341:0043) with the flywire firmware.\n"
              f"Nothing was measured; no numbers were invented.")
        return 1
    try:
        ser = open_board(args.port, args.baud)
    except (OSError, serial.SerialException) as exc:
        print(f"\nerror: could not open {args.port}: {exc}\n"
              f"Nothing was measured; no numbers were invented.")
        return 1

    try:
        # --- 1. Serial round trip (ping). -----------------------------------
        print(f"\n== 1. Serial round trip (ping) ==")
        print(f"  sending 'P' and timing host write -> 'P <micros>' reply over USB")
        t_ping = time.perf_counter()
        # Discard the first reply after boot: it can be delayed while the Uno
        # finishes its post-reset self-test (observed ~250 ms).
        warm = wait_for_ping(ser, timeout_s=5.0)
        if warm is None:
            print("  WARNING: no 'P' reply -- firmware may predate the ping "
                  "command; skipping (no number invented).")
        rtts = measure_pings(ser, args.pings)
        ping = describe(rtts)
        print(f"  {fmt(ping)}")
        print(f"  ({time.perf_counter() - t_ping:.1f} s wall)")

        # --- 2. Sensor sampling period and jitter. --------------------------
        print(f"\n== 2. Sensor sampling period and jitter (S lines) ==")
        t_s = time.perf_counter()
        intervals = measure_s_intervals(ser, args.s_samples, timeout_s=10.0)
        s_stats = describe(intervals)
        print(f"  {fmt(s_stats)}")
        print(f"  measures arrival at the host (firmware targets 50 Hz -> ~20 ms); "
              f"the jitter is the finding")
        print(f"  ({time.perf_counter() - t_s:.1f} s wall)")

        # --- 3. Host processing per loop iteration. -------------------------
        print(f"\n== 3. Host processing per loop iteration ==")
        print(f"  read S -> filter -> one {CHUNK_MS:g} ms network chunk -> write L "
              f"(the run_brain.port_loop work)")
        t_loop = time.perf_counter()
        loop_times = measure_host_loop(ser, args.loop_iters)
        host = describe(loop_times)
        print(f"  {fmt(host)}")
        print(f"  (timed from an S line in hand to the L write returning; "
              f"{time.perf_counter() - t_loop:.1f} s wall)")
    finally:
        try:
            ser.close()
        except Exception:
            pass

    # --- 5. Servo mechanical estimate (derived). ----------------------------
    servo_ms = SERVO_MOVE_DEG / SERVO_SPEED_DPS * 1000.0
    print(f"\n== 5. Servo mechanical estimate (DERIVED, not measured) ==")
    print(f"  {SERVO_SPEED_DPS:g} deg/s command slew limit -> "
          f"{SERVO_MOVE_DEG:g} deg = {servo_ms:.3f} ms")
    print(f"  derived from run_brain.SERVO_SPEED_DPS; the real SG90 has its own "
          f"dynamics that this does not measure")

    # --- Budget table. ------------------------------------------------------
    print_budget(ping, host, servo_ms)
    print(f"\nreference: the real animal's Giant Fiber latency is ~4 ms "
          f"(from the literature; not measured here)")

    # --- Save raw samples. --------------------------------------------------
    out_dir = ensure_results_dir()
    path = os.path.join(out_dir, "latency.csv")
    with open(path, "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["kind", "index", "value_ms"])
        for i, v in enumerate(rtts):
            writer.writerow(["ping_rtt", i, f"{v:.6f}"])
        for i, v in enumerate(intervals):
            writer.writerow(["s_interval", i, f"{v:.6f}"])

    wall = time.perf_counter() - t_start
    print(f"\nsaved {path}  (ping_rtt: {len(rtts)}, s_interval: {len(intervals)})")
    print(f"total wall time: {wall:.1f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
