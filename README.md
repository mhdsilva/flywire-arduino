# FlyWire on Arduino 🪰 — a fly brain driving an Arduino

**A real *Drosophila melanogaster* brain circuit running on a laptop CPU and
controlling physical hardware.**

I took the public [FlyWire](https://flywire.ai) connectome — the synapse-by-synapse map of the
fly brain — extracted the subcircuit that detects "something approaching" and triggers escape, and
wired it into an Arduino. When you startle the fly, it takes off and flies for a while
**decided by the connections themselves**, then lands and stops. The servo only moves when the
*Giant Fiber* (DNp01) actually fires — the behaviour **emerges from the wiring**, not from `if`s.

> **TL;DR:** A real fruit-fly connectome (FlyWire FAFB v783) reduced to a 583-neuron
> looming→escape subcircuit, simulated with a sparse LIF model on a laptop CPU (~0.9× real
> time) and closed into a physical loop via an Arduino: potentiometer = looming sense, three
> LEDs = the three neural stages, servo = flapping wings. Escape/flight behaviour emerges from
> the actual wiring, not from scripted logic.

---

## How it works

```
   [Arduino UNO]                          [Laptop]                        [Arduino UNO]
   potentiometer  ─── serial 115200 ───►  connectome FlyWire ─── serial ───►  3 LEDs
   (the "looming")    "S <ldr> <ntc>      LC4/LPLC2 → inter → DNp01           (stages)
                       <pot> <btn>"       (583 neurons, LIF, CPU)            servo
                                          ▲                                     (wings)
                                          └──────────── "L <s> <i> <m> <ang>" ─┘
```

- The **Arduino is the body**: it reads sensors, moves the servo, lights LEDs. Deliberately dumb.
- The **laptop is the brain**: it runs the connectome and decides. The neurons are the ones deciding.
- The loop closes at ~50 Hz over USB serial.

The potentiometer lets you "startle" the fly: a slow ramp is ignored, a sharp turn
becomes a strong *looming* that sweeps through the circuit and makes DNp01 fire.

## The brain (real data)

The data comes from Codex/FlyWire, snapshot **FAFB v783** (the complete adult brain of
`Drosophila`, ~139,255 neurons).

The subcircuit is extracted by `brain/build_circuit.py`:

| Role | Neurons | What it is |
|---|---|---|
| **Sensory** | 314 | LC4 + LPLC2 — visual *looming* detectors |
| **Interneurons** | 267 | what connects the two |
| **Motor** | 2 | DNp01 — the *Giant Fiber*, escape command |
| **Total** | **583** | 4,799 synapses |

Simulation: sparse LIF in numpy/scipy (`brain/lif.py`), `dt = 0.1 ms`, `tau_m = 20 ms`,
`tau_syn = 5 ms`. Weights = synapse count, with sign by neurotransmitter
(GABA = inhibitory). Runs at **~0.9 s of CPU per 1 s of brain** on an i5-1135G7 — that is,
practically real time, with no GPU.

> The reflex threshold **is not chosen**: it is a consequence of the wiring. In `--dry-run`,
> `stim = 0` → the motor stays quiet; `stim = 0.2` → it fires.

## The behaviour

The servo does not blink: it **flies**. `brain/run_brain.py` has a state machine:

1. **Landed** — servo at rest, it ignores the pot.
2. **Startle** (DNp01 fires) → **takes off**: the servo flaps its wings (oscillates 40°–140°).
3. The flight duration is decided *at the moment of the startle*:
   `base + spike_weight × spikes + looming_weight × intensity`, with a bit of random
   variation. A stronger startle ⇒ a longer flight.
4. **Lands** and stops. Only a **new** startle makes it fly again.

### Two ways to startle it

`--sensor` picks what drives the looming stimulus:

- **`--sensor pot`** (default) — the potentiometer on **A2**. *Approaching* = a sharp
  counter-clockwise turn.
- **`--sensor ldr`** — the light sensor on **A0**. *Approaching* = a sudden rise in light:
  keep the room dark (LDR ≈ 50) and arrive with a flashlight. The light is the "predator" and
  the fly bolts. (You can invert the staging — lit at rest, a hand casts a shadow — by flipping
  the LDR `direction` to `-1` in `SENSORS`.)

Both share the same filtering: a median filter to kill spikes, a dead band so that noise and
slow changes are ignored, and a refractory period after each escape.

## Hardware

Eletrogate "Kit Start" kit (Arduino UNO R3):

| Component | Pin | Role in the project |
|---|---|---|
| Micro servo SG90 | 9 | wings (flies) |
| Red LED | 5 | **sensory** stage (LC4/LPLC2) |
| Yellow LED | 6 | **interneuron** |
| Green LED | 7 | **motor** (Giant Fiber) |
| Potentiometer 10 kΩ | A2 | *looming* — the startle (`--sensor pot`) |
| LDR (light) | A0 | *looming* — a flashlight arriving (`--sensor ldr`) |
| NTC 10 kΩ | A1 | *(optional)* temperature |
| Button | 2 | *(optional)* |
| Buzzer | 8 | *(optional)* |

Assembly and wiring details are in the header of `board/flywire/flywire.ino`.

### Noise protection (bench learning)

The servo injects noise into the rails when it moves, and that shows up in the pot reading. Two
capacitors help:

- **100 nF** (ceramic) between the analog input (**A2** for the pot, or **A0** for the LDR) and
  **GND** — filters high-frequency noise at the input.
- **100 µF** (electrolytic, mind the polarity) between **5 V and GND** near the servo — current
  reserve for the peaks.

In addition, the *software* has a median filter, a dead band and a refractory period after each
escape, which break the noise → firing → servo → noise cycle.

## How to run

### 1. Tools

```bash
# arduino-cli (no sudo, inside the project)
mkdir -p bin && curl -fL https://downloads.arduino.cc/arduino-cli/arduino-cli_latest_Linux_64bit.tar.gz \
  | tar -xz -C bin arduino-cli
export PATH="$PWD/bin:$PATH"
arduino-cli core install arduino:avr
arduino-cli lib install Servo

# python
python3 -m venv .venv
.venv/bin/pip install pyserial numpy scipy pandas

# serial port access (once; requires re-login)
sudo usermod -a -G dialout "$USER"
```

### 2. Data and circuits

```bash
.venv/bin/python brain/fetch_data.py      # downloads the FlyWire data (~50 MB)
.venv/bin/python brain/build_circuit.py   # generates brain/data/circuit.npz
```

> If you cloned the repo, `circuit.npz` already comes ready — you can skip this step and just run.

### 3. Flash the Arduino

```bash
arduino-cli compile --fqbn arduino:avr:uno --upload -p /dev/ttyACM0 board/flywire
```

On boot it runs a self-test: sweeps the servo, lights the LEDs in sequence, beeps the buzzer
(if connected). If you see this, the hardware is alive.

### 4. Run the brain

```bash
# without hardware (simulation only)
.venv/bin/python brain/run_brain.py --dry-run --stim 0.2 --seconds 1
.venv/bin/python brain/run_brain.py --fake --seconds 14

# real loop, potentiometer: a sharp twist startles it
cd brain && sg dialout -c '../.venv/bin/python -u run_brain.py --port /dev/ttyACM0 --seconds 0'

# real loop, light sensor: keep the room dark, arrive with a flashlight
cd brain && sg dialout -c '../.venv/bin/python -u run_brain.py --port /dev/ttyACM0 --sensor ldr --seconds 0'
```

`--seconds 0` runs until you press Ctrl-C.

## Engineering notes (what broke along the way)

Worth recording, because it was the most interesting part:

- **Serial buffer**: the Uno transmits sensors at 50 Hz. If the host does not drain the reading, the
  board's TX buffer fills up, its loop blocks and the PC's `write()` hangs forever. Solution:
  always drain and `write_timeout=1`.
- **`dt ≈ 0` with a full buffer**: processing several delayed samples with the same clock made
  `d(pot)/dt` explode and the noise turn into "looming". Solution: process only the most recent sample
  and use the nominal `dt` (20 ms).
- **Renewable flinch**: each spike renewed the flinch, so any jitter turned into the servo
  throbbing. Solution: one event = one behaviour.
- **Noise cycle**: noise fires → servo moves → servo injects noise → fires again.
  Solution: refractory period + capacitors.
- **The SG90 is positional**: it does not spin 360°, it only goes from 0 to 180° and holds. That is not a bug.

## What is real and what is simplified

**Real:** the topology of the connections (who connects to whom, with how many synapses) and the
identity of the neurons (LC4, LPLC2, DNp01) come from the connectome. The firing threshold emerges from that wiring.

**Simplified:** the neuron model is LIF (not biophysical); synapses are static; the
neurotransmitters are treated as excitatory (GABA inhibitory); no plasticity; the body
is a servo, not real biomechanics. It is a serious *toy*, not a paper.

## License and attribution

Code: **MIT** (see `LICENSE`).
Connectome data and derived artefacts (`brain/data/circuit.npz`): **CC BY-NC 4.0**
(non-commercial), from the FlyWire consortium.

References:

- Dorkenwald, S. et al. *Neuronal wiring diagram of an adult brain.* Nature (2024).
- Schlegel, P. et al. *Whole-brain annotation and multi-connectome cell typing of Drosophila.* Nature (2024).
- Shiu, P. K. et al. *A leaky integrate-and-fire computational model based on the connectome of the entire adult Drosophila brain.* Nature (2024).
- FlyWire / Codex — https://codex.flywire.ai
