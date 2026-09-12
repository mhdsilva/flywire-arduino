#!/usr/bin/env python3
"""Visible Reflex -- brain v0.

Closes the loop between the FlyWire connectome (LC4/LPLC2 -> inter -> DNp01) and the Uno:
  - --dry-run: synthetic stimulus, no hardware.
  - --fake:    same control loop, synthetic potentiometer, no serial.
  - --port:    real loop, reads "S ..." at 50 Hz and writes "L s i m ang".

Potentiometer -> looming stimulus map
------------------------------------------
The pot is noisy: isolated spikes of up to ~27 counts (measured). So the signal
goes through four stages:
  1. MEDIAN filter of 5 samples    -- kills isolated spikes;
  2. speed v = d(pot)/dt in counts/s;
  3. dead band: v_eff = max(0, v - V_DEAD)  -- ignores noise and slow turning;
  4. stim = clip( LEVEL_W*(pot/1023) + V_TO_STIM * v_eff, 0, 1 ).

A FAST turn (>= ~1000 counts/s) saturates stim and fires DNp01; a slow turn
(< V_DEAD) does nothing. Since we use max(0, ...), only the RISE counts:
looming = the thing approaching. On your pot, rising = turning counter-clockwise.
Constants: POT_MEDIAN=5, LEVEL_W=0.05, V_DEAD=300 (counts/s),
V_TO_STIM=1/700. The circuit threshold (dry-run) sits at stim ~0.12.

Behaviour (flight)
------------------
The recent DNp01 firing rate continuously sets servo amplitude and frequency.
Silence lets the rate estimate decay and the servo return to rest. There is no
predetermined flight duration. Sensing continues during motion, with a brief
input guard after activity ends. See FlightBehavior and docs/NEURAL-CONTROL.md.
"""

from __future__ import annotations

import argparse
import math
import os
import sys
import time

import numpy as np
import scipy.sparse as sp

try:
    import serial  # pyserial
except ImportError:  # allows running --dry-run/--fake without pyserial
    serial = None

from lif import LIF

HERE = os.path.dirname(os.path.abspath(__file__))
CIRCUIT = os.path.join(HERE, "data", "circuit.npz")

DT = 0.1                 # ms
WEIGHT_SCALE = 3e-4      # see lif.py: raw weights are syn_count
STIM_GAIN = 0.5          # tonic current = stim * STIM_GAIN
CHUNK_MS = 20.0          # loop step with hardware (~period of S at 50 Hz)

POT_MAX = 1023.0
POT_MEDIAN = 5            # median filter size
LEVEL_W = 0.05            # weight of the knob level (position)
V_DEAD = 300.0            # counts/s below this = noise / slow turn
V_TO_STIM = 1.0 / 700.0   # v_eff = 700 counts/s saturates the stimulus

REST_ANGLE = 90

# --- neural activity -> servo readout --------------------------------------
# These are actuator/readout choices, not biological parameters. The circuit
# and its neuron parameters are unchanged. There is no flight-duration timer.
RATE_TAU_S = 0.8            # exponential smoothing of motor spikes (flight memory)
RATE_FULL_HZ = 60.0        # per motor neuron: full amplitude/frequency
RATE_ON_HZ = 2.0            # trigger as soon as a real burst appears
RATE_OFF_HZ = 0.8           # hysteresis avoids toggling near silence
CAPTURE_S = 0.25            # sensor stays live for this long after take-off:
                            # the servo is still near rest, so the network's
                            # whole response is captured before the input is
                            # gated against the flap noise
LAND_REFRACTORY = 0.5       # ignore sensor noise briefly AFTER activity ends
FLAP_MIN_HZ = 0.6
FLAP_MAX_HZ = 1.2
FLAP_LO = 40
FLAP_HI = 140
SERVO_SPEED_DPS = 450.0     # command slew limit, including return to rest

# --- sensor selection -----------------------------------------------------
# The looming stimulus can come from the potentiometer or the LDR (light).
# Each entry: which field of the "S <ldr> <ntc> <pot> <btn>" line to read,
# which direction means "approaching", and the weight of the absolute level.
LDR_DEAD = 250.0  # counts/s: smaller than the pot's, the LDR step is gentler
SENSORS = {
    "pot": {"field": 3, "direction": 1.0, "level_w": LEVEL_W, "dead": V_DEAD},
    "ldr": {"field": 1, "direction": 1.0, "level_w": 0.0, "dead": LDR_DEAD},
}


def load_circuit():
    d = np.load(CIRCUIT)
    n = len(d["node_ids"])
    W = sp.csr_matrix(
        (d["data"].astype(np.float64), (d["rows"], d["cols"])), shape=(n, n)
    )
    return W, d["roles"], d["node_ids"]


class LoomingFilter:
    """raw sensor (0..1023) -> looming stimulus (0..1), robust to noise.

    Median filter + dead band on the speed. `direction` says which way the
    reading moves when something approaches:
      +1 = rising  (LDR: the flashlight arrives; pot: the knob turns up)
      -1 = falling (LDR: a hand casts a shadow)
    `dead` is the dead band in counts/s (sensor-specific). Noise and slow
    changes are ignored.
    """

    def __init__(self, direction: float = 1.0, level_w: float = LEVEL_W,
                 dead: float = V_DEAD) -> None:
        self.direction = direction
        self.level_w = level_w
        self.dead = dead
        self.buf: list = []
        self.prev = None
        self.v = 0.0

    def update(self, value: float, dt_s: float) -> float:
        # 1) median of the last POT_MEDIAN samples (kills isolated spikes)
        self.buf.append(value)
        if len(self.buf) > POT_MEDIAN:
            self.buf.pop(0)
        p = sorted(self.buf)[len(self.buf) // 2]

        # 2) speed in counts/s, over the already filtered value
        v = (p - self.prev) / dt_s if (self.prev is not None and dt_s > 0) else 0.0
        self.prev = p

        # 3) keep only the "approach" direction, then apply the dead band
        self.v = max(0.0, self.direction * v - self.dead)

        # 4) stimulus
        level = self.level_w * (p / POT_MAX)
        return float(np.clip(level + V_TO_STIM * self.v, 0.0, 1.0))


class FlightBehavior:
    """Continuously decode motor activity into a bounded servo oscillation.

    A 100 ms exponential rate estimate sets amplitude and frequency. Silence
    lets that estimate decay and the servo return to rest; ongoing spikes can
    sustain motion indefinitely. The sinusoid and readout thresholds are an
    engineered actuator mapping, not oscillations generated by the connectome.
    """

    def __init__(self, motor_neurons: int = 2) -> None:
        self.motor_neurons = motor_neurons
        self.rate_hz = 0.0
        self.drive = 0.0
        self.frequency_hz = 0.0
        self.flying = False
        self.phase = 0.0
        self.angle = float(REST_ANGLE)
        self.capture_until = -1.0
        self.refractory_until = -1.0
        self.episodes = 0

    def input_blocked(self, now: float) -> bool:
        """Ignore the sensor once the wings are moving (and just after landing).

        On the bench the moving SG90 injects electrical noise into the analog
        input, and those per-sample jumps are LARGER than the real light signal,
        so no velocity filter can separate them. The input therefore stays live
        only for CAPTURE_S after take-off -- while the servo is still near rest
        -- so the network's whole response is measured before the gate closes.
        Flight duration is still decided by the network: it is how long the
        captured spike rate takes to decay below the off-threshold.
        """
        return (self.flying and now >= self.capture_until) or now < self.refractory_until

    def update(self, now: float, dt: float, mspikes: int) -> int:
        rate = mspikes / (self.motor_neurons * dt)
        alpha = -math.expm1(-dt / RATE_TAU_S)
        self.rate_hz += alpha * (rate - self.rate_hz)

        if self.flying and self.rate_hz < RATE_OFF_HZ:
            self.flying = False
            self.refractory_until = now + LAND_REFRACTORY
        elif (not self.flying and not self.input_blocked(now)
              and mspikes and self.rate_hz >= RATE_ON_HZ):
            self.flying = True
            self.phase = 0.0
            self.drive = 0.0
            self.capture_until = now + CAPTURE_S
            self.episodes += 1

        target = float(REST_ANGLE)
        self.frequency_hz = 0.0
        if self.flying:
            # The PEAK of the captured response latches the flap strength for the
            # whole episode; the rate's decay sets how long the fly stays
            # airborne. A bigger burst => bigger wings AND a longer flight.
            self.drive = max(self.drive, min(self.rate_hz / RATE_FULL_HZ, 1.0))
            self.frequency_hz = FLAP_MIN_HZ + (FLAP_MAX_HZ - FLAP_MIN_HZ) * self.drive
            self.phase = (self.phase + 2.0 * math.pi * self.frequency_hz * dt) % (2.0 * math.pi)
            amplitude = 0.5 * (FLAP_HI - FLAP_LO) * self.drive
            target += amplitude * math.sin(self.phase)

        travel = SERVO_SPEED_DPS * dt
        self.angle += max(-travel, min(target - self.angle, travel))
        return int(round(self.angle))


def step_ms(net, ext, ms, dt=DT):
    steps = max(1, int(round(ms / dt)))
    counts = np.zeros(net.n, dtype=np.int64)
    for _ in range(steps):
        counts += net.step(ext)
    return counts


# --------------------------------------------------------------------------
# dry run
# --------------------------------------------------------------------------
def dry_run(stim: float, seconds: float) -> int:
    W, roles, _ = load_circuit()
    net = LIF(W, roles, weight_scale=WEIGHT_SCALE, dt=DT)
    ext = np.zeros(net.n)
    ext[roles == "sensory"] = stim * STIM_GAIN

    steps = int(round(seconds * 1000.0 / DT))
    bin_steps = max(1, int(round(0.2 * 1000.0 / DT)))
    sens = roles == "sensory"
    inter = roles == "inter"
    motor = roles == "motor"

    print(f"dry-run: stim={stim}  {seconds}s  dt={DT}ms  "
          f"neurons={net.n}  edges={W.nnz}")
    done = 0
    motor_total = 0
    t0 = time.time()
    while done < steps:
        k = min(bin_steps, steps - done)
        counts = np.zeros(net.n, dtype=np.int64)
        for _ in range(k):
            counts += net.step(ext)
        done += k
        window_s = k * DT / 1000.0
        hz = counts / window_s
        mfired = counts[motor].sum()
        motor_total += mfired
        print(
            f"  t={done * DT / 1000.0:5.2f}s  "
            f"sensory={hz[sens].mean():7.1f}Hz  "
            f"inter={hz[inter].mean():6.1f}Hz  "
            f"motor={hz[motor].mean():6.1f}Hz  "
            f"motor_fired={'YES' if mfired else 'no'}"
        )
    elapsed = time.time() - t0
    print(f"summary: did the motor (DNp01) fire? "
          f"{'YES' if motor_total else 'no'}  ({motor_total} spikes)")
    print(f"time: {elapsed:.2f}s wall for {seconds}s simulated "
          f"({elapsed / seconds:.2f}s per simulated second)")
    return 0


# --------------------------------------------------------------------------
# fake: same loop, synthetic pot, no serial
# --------------------------------------------------------------------------
def fake_pot(t: float) -> float:
    """Synthetic knob trajectory: idle, slow ramp, flick, return, flick again."""
    if t < 1.0:
        return 0.0
    if t < 2.5:                      # slow ramp 0 -> 120 (should not fire)
        return 120.0 * (t - 1.0) / 1.5
    if t < 2.7:                      # flick 1: 120 -> 900 (startles -> flies)
        return 120.0 + (900.0 - 120.0) * (t - 2.5) / 0.2
    if t < 5.0:                      # holds high (level only, does not fire)
        return 900.0
    if t < 5.4:                      # return (a descent does not count as looming)
        return 900.0 * (1.0 - (t - 5.0) / 0.4)
    if t < 9.0:                      # idle, landed
        return 0.0
    if t < 9.2:                      # flick 2: 0 -> 900 (startles again -> flies)
        return 900.0 * (t - 9.0) / 0.2
    return 900.0


def fake(seconds: float) -> int:
    W, roles, _ = load_circuit()
    net = LIF(W, roles, weight_scale=WEIGHT_SCALE, dt=DT)
    ext = np.zeros(net.n)
    sens = roles == "sensory"
    inter = roles == "inter"
    motor = roles == "motor"

    print(f"fake: {seconds}s  dt={DT}ms  neurons={net.n}  edges={W.nnz}  (no serial)")
    steps = int(round(seconds * 1000.0 / DT))
    chunk_steps = max(1, int(round(CHUNK_MS / DT)))
    log_every = max(1, int(round(0.2 * 1000.0 / CHUNK_MS)))

    filt = LoomingFilter()
    fly = FlightBehavior(motor_neurons=int(motor.sum()))
    done = 0
    chunk_i = 0
    motor_total = 0
    try:
        while done < steps:
            k = min(chunk_steps, steps - done)
            t = done * DT / 1000.0
            pot = fake_pot(t)
            dt_s = k * DT / 1000.0
            # Sensor samples remain 20 ms apart even for a partial final chunk.
            stim = filt.update(pot, CHUNK_MS / 1000.0)
            if fly.input_blocked(t):
                stim = 0.0
            ext[sens] = stim * STIM_GAIN
            counts = np.zeros(net.n, dtype=np.int64)
            for _ in range(k):
                counts += net.step(ext)
            done += k
            chunk_i += 1

            mspikes = int(counts[motor].sum())
            motor_total += mspikes
            angle = fly.update(t, dt_s, mspikes)

            if chunk_i % log_every == 0 or done >= steps:
                print(
                    f"  t={t:4.2f}s pot={int(pot):4d} stim={stim:4.2f} "
                    f"sens={'1' if counts[sens].any() else '0'} "
                    f"inter={'1' if counts[inter].any() else '0'} "
                    f"motor={'1' if mspikes else '0'} flight={'1' if fly.flying else '0'} "
                    f"ang={angle:3d} rate={fly.rate_hz:5.1f}Hz flap={fly.frequency_hz:3.1f}Hz"
                )
    except KeyboardInterrupt:
        print("\ninterrupted.")
    print(f"summary: did the motor fire? {'YES' if motor_total else 'no'} "
          f"({motor_total} spikes) -- {fly.episodes} flights")
    return 0


# --------------------------------------------------------------------------
# loop with hardware
# --------------------------------------------------------------------------
def open_serial(port: str, baud: int):
    ser = serial.Serial(port, baud, timeout=0.2, write_timeout=1)
    time.sleep(2.5)  # Uno resets when the port opens; wait for the self-test
    return ser


def send(ser, sensory: int, inter: int, motor: int, angle: int) -> None:
    try:
        ser.write(f"L {sensory} {inter} {motor} {int(angle)}\n".encode())
    except serial.SerialTimeoutException:
        print("  !! write hung (did the board reset?)")


def port_loop(port: str, baud: int, seconds: float, sensor: str = "pot") -> int:
    if serial is None:
        print("error: pyserial not installed (pip install pyserial)")
        return 1
    W, roles, _ = load_circuit()
    net = LIF(W, roles, weight_scale=WEIGHT_SCALE, dt=DT)
    ext = np.zeros(net.n)
    sens = roles == "sensory"
    inter = roles == "inter"
    motor = roles == "motor"
    sensor_cfg = SENSORS[sensor]
    field = sensor_cfg["field"]

    print(f"opening {port} @ {baud} ...")
    try:
        ser = open_serial(port, baud)
    except (OSError, serial.SerialException) as exc:
        print(f"error: could not open {port}: {exc}")
        return 1
    buf = b""
    filt = LoomingFilter(direction=sensor_cfg["direction"],
                         level_w=sensor_cfg["level_w"], dead=sensor_cfg["dead"])
    fly = FlightBehavior(motor_neurons=int(motor.sum()))
    motor_total = 0
    last_status = 0.0
    t0 = time.time()
    sim_s = 0.0
    print("closed loop -- Ctrl-C to quit")
    try:
        while seconds <= 0 or time.time() - t0 < seconds:
            try:
                n = ser.in_waiting
                if n:
                    buf += ser.read(n)
            except (OSError, serial.SerialException):
                print("  !! read failed; reopening the port...")
                try:
                    ser.close()
                except Exception:
                    pass
                while True:
                    try:
                        time.sleep(1.0)
                        ser = open_serial(port, baud)
                        break
                    except (OSError, serial.SerialException) as exc:
                        print(f"  ... still no board: {exc}")
                buf = b""
                # Opening the Uno resets its body to rest. Discard pre-outage
                # sensor history and neural/readout state too: none of them
                # advanced while disconnected. Preserve only episode telemetry.
                episodes = fly.episodes
                net.reset()
                ext.fill(0.0)
                filt = LoomingFilter(direction=sensor_cfg["direction"],
                                     level_w=sensor_cfg["level_w"], dead=sensor_cfg["dead"])
                fly = FlightBehavior(motor_neurons=int(motor.sum()))
                fly.episodes = episodes
                send(ser, 0, 0, 0, REST_ANGLE)
                continue

            # use ONLY the last S sample of the batch (discard the late ones):
            # keeps the loop in real time and avoids dt ~ 0 between samples.
            raw = None
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                line = line.strip()
                if line.startswith(b"S "):
                    parts = line.split()
                    if len(parts) == 5:
                        try:
                            raw = float(parts[field])
                        except ValueError:
                            pass

            if raw is None:
                time.sleep(0.005)
                continue

            now = time.time()
            # NOMINAL dt from the Uno (50 Hz). Do NOT use wall time here: if the
            # batch has several lines, dt becomes ~0 and the pot noise becomes a
            # giant false looming (a bug that made the servo throb in series).
            # Keep sensing while active; only suppress input briefly after the
            # readout settles. Physical filtering still matters during motion.
            stim = filt.update(raw, CHUNK_MS / 1000.0)
            if fly.input_blocked(now):
                stim = 0.0  # brief post-activity guard against landing noise

            ext[sens] = stim * STIM_GAIN
            counts = step_ms(net, ext, CHUNK_MS)
            sim_s += CHUNK_MS / 1000.0
            mspikes = int(counts[motor].sum())
            motor_total += mspikes
            angle = fly.update(now, CHUNK_MS / 1000.0, mspikes)

            send(
                ser,
                1 if counts[sens].any() else 0,
                1 if counts[inter].any() else 0,
                1 if (mspikes or fly.flying) else 0,
                angle,
            )

            if now - last_status >= 0.5:
                last_status = now
                print(
                    f"  {sensor}={int(raw):4d} stim={stim:4.2f} "
                    f"motor={'1' if mspikes else '0'} "
                    f"flight={'1' if fly.flying else '0'} ang={angle:3d} "
                    f"rate={fly.rate_hz:5.1f}Hz flap={fly.frequency_hz:3.1f}Hz "
                    f"flight#{fly.episodes} sim={sim_s:5.1f}s wall={now - t0:5.1f}s"
                )
    except KeyboardInterrupt:
        print("\ninterrupted.")
    finally:
        try:
            send(ser, 0, 0, 0, REST_ANGLE)
        except Exception:
            pass
        try:
            ser.close()
        except Exception:
            pass
    print(f"summary: did the motor fire? {'YES' if motor_total else 'no'} "
          f"({motor_total} spikes) -- {fly.episodes} flights")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Visible Reflex -- brain v0")
    ap.add_argument("--dry-run", action="store_true", help="synthetic stimulus, no hardware")
    ap.add_argument("--fake", action="store_true", help="control loop without serial")
    ap.add_argument("--port", help="serial port, e.g. /dev/ttyACM0")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--sensor", choices=["pot", "ldr"], default="pot",
                    help="what drives the looming stimulus (default: pot)")
    ap.add_argument("--stim", type=float, default=0.2, help="0..1 (dry-run)")
    ap.add_argument("--seconds", type=float, default=3.0,
                    help="duration; <=0 on --port runs until Ctrl-C")
    args = ap.parse_args()

    if args.dry_run:
        return dry_run(float(np.clip(args.stim, 0.0, 1.0)), args.seconds)
    if args.fake:
        return fake(args.seconds)
    if args.port:
        return port_loop(args.port, args.baud, args.seconds, args.sensor)
    ap.error("choose --dry-run, --fake or --port")


if __name__ == "__main__":
    sys.exit(main())
