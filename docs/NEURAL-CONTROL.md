# Continuous neural control of the servo

The FlyWire subcircuit and LIF parameters are unchanged. The former flight-duration
formula and random jitter have been replaced by a continuous readout of the two
DNp01 neurons. Both `--fake` and `--port` use this readout; `--dry-run` continues
to measure neural firing under a constant stimulus without a servo controller.

## What the circuit actually sustained

Measured on 2026-09-12 with the versioned `brain/data/circuit.npz`, `DT = 0.1 ms`,
`WEIGHT_SCALE = 3e-4` and `STIM_GAIN = 0.5`. Each case starts from a reset network,
waits 200 ms, applies a rectangular stimulus directly to all sensory neurons,
and then removes it. No sensor filtering or flight controller is involved in
this measurement. Motor spikes are summed over both DNp01 neurons in 20 ms bins.

| Stimulus | Pulse length | Motor spikes | End of last nonempty motor bin, relative to stimulus onset |
|---:|---:|---:|---:|
| 0 | 100 ms | 0 | — |
| 0.2 | 20 ms | 0 | — |
| 0.2 | 100 ms | 6 | 100 ms |
| 1.0 | 20 ms | 6 | 40 ms |
| 1.0 | 100 ms | 32 | 120 ms |
| 1.0 | 200 ms | 65 | 220 ms |
| 0.2 | 1000 ms | 66 | 1020 ms |

These trials show brief responses, with motor activity ending within one
20 ms bin after stimulus removal. They do not establish that the circuit can
generate sustained flight or an alternating motor rhythm. A brief input now
produces a brief servo gesture rather than a flight extended by a timer.

Reproduce from the repository root:

```bash
.venv/bin/python -B - <<'PY'
import sys
sys.path.insert(0, 'brain')
import numpy as np
from lif import LIF
from run_brain import DT, WEIGHT_SCALE, STIM_GAIN, load_circuit, step_ms

W, roles, _ = load_circuit()
for stim, pulse_ms in [(0, 100), (.2, 20), (.2, 100), (1, 20),
                       (1, 100), (1, 200), (.2, 1000)]:
    net = LIF(W, roles, weight_scale=WEIGHT_SCALE, dt=DT)
    ext = np.zeros(net.n)
    total, last_ms = 0, None
    for i in range(100):
        active = 10 <= i < 10 + pulse_ms // 20
        ext[roles == 'sensory'] = stim * STIM_GAIN if active else 0.0
        counts = step_ms(net, ext, 20)
        motor = int(counts[roles == 'motor'].sum())
        total += motor
        if motor:
            last_ms = (i + 1) * 20 - 200
    print(stim, pulse_ms, total, last_ms)
PY
```

## Readout and limits

Every nominal 20 ms loop window, `FlightBehavior` computes:

```text
instantaneous_rate = motor_spikes / (motor_neurons × window_seconds)
alpha = 1 - exp(-window_seconds / 0.50)
rate = rate + alpha × (instantaneous_rate - rate)
drive = max(drive, min(rate / 100 Hz, 1))   # PEAK latched per episode
amplitude = 50° × drive
frequency = 0.6 Hz + 0.6 Hz × drive
```

Motion starts when a window contains spikes and the filtered rate reaches 5 Hz
per motor neuron. It remains active until the rate falls below 2 Hz. These two
thresholds prevent rapid toggling around silence. The oscillator phase advances
continuously while active; the flap strength is the episode's PEAK drive. Because
the rate then decays exponentially from that peak (time constant 0.50 s), a bigger
burst stays above the off-threshold for longer: the network's response sets both
the wing amplitude AND the flight duration, with no timer.

The servo target is `90° + amplitude × sin(phase)`. When activity subsides, the
target becomes 90°. Commands are constrained to 40°–140° and slew-limited to
450°/s in simulation time, including the return to rest. Serial angles are rounded
to whole degrees. The slew limit can reduce the achieved amplitude at high rates.
The printed `flap` value is the requested oscillator frequency, not a measurement
of physical servo motion.

The 0.50 s filter is an actuator readout choice. It leaves a movement tail after
the final spike (measured: one fast flick gives a ~1.8 s episode with ~2 wing
beats and about ±26° around rest); observed movement duration therefore depends on
both network activity and the readout parameters. No additional neural populations,
connections, adaptation mechanisms or biological claims were introduced. The
sinusoid still comes from code, not from oscillations in the connectome.

## Sensing and hardware

Sensor input stays live during movement so new activity can sustain or change it.
After the activity threshold is crossed downward, a 0.5 s input guard suppresses
landing noise. The sensor filter keeps updating during this guard so reopening
input does not accumulate a false derivative. The green LED reports actual motor
spikes in the current window, independently of the readout's decay.

After a serial reconnection, sensor history, neuron state and the servo readout
are reset together and a rest command is sent. Pre-outage activity cannot resume
an old movement; a new stimulus is required. The cumulative episode count is kept.

The median filter and dead band remain in place. Since input is no longer muted
throughout a flight, power decoupling matters during movement: electrical noise
can sustain activity. The LDR-to-servo path was exercised on the physical Arduino
on 2026-09-12, as recorded below. The command slew limit does not model the servo's
mechanics or change the firmware boot test; the bench trial was a functional
check, not a calibration of angle, speed or noise rejection.

## Physical bench trial — 2026-09-12

The existing Arduino UNO firmware was used without recompiling or flashing it.
The USB device was available at `/dev/ttyACM0` (VID:PID `2341:0043`) with no other
process holding the port. The current login had not picked up `dialout` membership,
so the controller was launched with `sg dialout`. Opening the serial port resets
the Uno and runs its existing servo/LED/buzzer self-test.

The preliminary serial check received the firmware banner
`# flywire ready -- S <ldr> <ntc> <pot> <btn>` and 291 valid sensor frames during
an eight-second window that included startup. A short initial potentiometer-mode
run was interrupted when the operator selected the LDR. That run recorded 114
motor spikes and seven controller episodes; it was a connectivity check, not a
controlled validation of potentiometer stimuli.

The main test used **LDR on A0**. The operator was instructed to keep light stable,
then rapidly bring a flashlight toward the sensor. Command, from the repository
root:

```bash
sg dialout -c '.venv/bin/python -B -u brain/run_brain.py --port /dev/ttyACM0 --sensor ldr --seconds 180'
```

`--seconds 180` limits the entire test session to three minutes. It does not set
the duration of an individual movement. Use `--seconds 0` for an interactive run
until Ctrl-C; normal shutdown sends LEDs off and servo rest at 90°.

| Observation | Result |
|---|---|
| Light change seen by the controller | Example: LDR 371, stimulus 1.00, motor firing present |
| Neural readout during that response | 99.1 Hz per motor neuron; requested oscillator frequency 2.0 Hz |
| Servo command during that response | 115°, followed by commands returning to 90° |
| Full LDR session summary | 2,810 motor spikes; 57 controller episodes |
| Session completion | Process exited normally with code 0; shutdown sent the rest command |
| Physical observation | Operator confirmed the hardware was working and described the movements as brief |

The numerical observations above are serial readings, simulated neural activity
and issued commands. There was no servo position feedback or wing-motion sensor,
so commanded angles and oscillator rates are not measured physical trajectories.
The 57 episodes are controller threshold crossings, not a count of independently
labelled flashlight events. The trial therefore confirms the functional path
from light input to visible movement, but does not quantify false triggers or
validate fly biomechanics. Reconnection recovery was tested with simulated serial
disconnection, not by unplugging the physical board during this trial.

## Decision after the bench trial

The operator initially expected a startled fly to move for longer. We considered
making the servo readout decay more slowly to extend motion for approximately
2–3 or 4–5 seconds, or investigating a circuit that sustains activity itself.
The final choice was to **keep the current network-driven brief response**.

No longer decay, artificial minimum flight duration, random duration or added
neural persistence was introduced. `RATE_TAU_S` remains 0.10 s; the circuit file,
its topology, synaptic weights and LIF parameters are unchanged. Future extensions
should distinguish newly demonstrated neural persistence from a longer actuator
envelope. Fidelity here means fidelity to this simplified circuit's activity,
not evidence that this subcircuit reproduces a complete real fly flight.

## Checks

```bash
.venv/bin/python -B -m unittest discover -s tests -v
.venv/bin/python -B brain/run_brain.py --fake --seconds 14
```

The final automated suite contains **12 passing tests**. `git diff --check` also
passes. Independent code review identified stale neural/readout state after a
serial outage; a regression test reproduced it before the reset-on-reconnect fix.
The follow-up review found no remaining material issues.

The synthetic potentiometer scenario produces two brief episodes and 130 motor
spikes with these parameters. Slow ramps and a held-high sensor do not sustain
movement. Unit tests exercise sustained activity beyond the old duration cap,
rate-dependent amplitude and frequency, return to rest, deterministic replay,
angle/speed limits, population/time normalization and the landing input guard.
Integration tests exercise the real saved circuit with both sensor filters, the
synthetic loop, and the serial loop through simulated Arduino readings. The
serial test also checks that the motor LED can turn off while the servo output
decays and that normal exit sends the rest command. A reconnect regression checks
that stable readings leave the servo at rest after an outage and a subsequent
new stimulus can still produce movement.
