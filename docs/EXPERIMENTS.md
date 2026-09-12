# Experiments

A design for turning the bench demo into measurable experiments.

> **Status: design document.** The runners under `experiments/` are not implemented
> yet. This file fixes the questions, the shared protocol, the metrics and the
> interpretation *before* any code is written, so the experiments cannot be tuned
> into telling a nicer story afterwards.

The circuit is real — a 583-neuron FlyWire subcircuit (LC4/LPLC2 → interneurons →
DNp01). The model is a leaky integrate-and-fire network with static synapses. So
these experiments ask what the **wiring** does, not what a biophysical brain does.

---

## Shared protocol

Every experiment uses the same stimulus protocol, so results are comparable:

1. **Reset** the network (`LIF.reset()`), fixed `seed`.
2. **Warm-up:** 200 ms with no stimulus (let the state settle from rest).
3. **Pulse:** a rectangular stimulus of amplitude `amp` (in `STIM_GAIN` units) and
   duration `pulse_ms`, applied to the **sensory** neurons only:
   `ext[sensory] = amp * STIM_GAIN`.
4. **Readout:** 500 ms with no stimulus.

Integration step `DT = 0.1 ms` (as everywhere else in the repo). Motor spikes are
counted over the pulse + readout window.

## Metrics

| Metric | Definition | Why it matters |
|---|---|---|
| `motor_spikes` | total DNp01 spikes in the window | the strength of the escape response |
| `first_spike_ms` | time from the pulse onset to the first DNp01 spike | the reaction latency; the real animal is ~4 ms |
| `peak_rate_hz` | max DNp01 spikes in a 20 ms bin / 0.02 / n_motor | the burst intensity |
| `triggered` | `motor_spikes > 0` | the binary decision used by the dose–response |
| `bins_with_spikes` | number of 20 ms bins containing a DNp01 spike | how sustained, not just how loud |

All metrics are reported per condition, never averaged across conditions.

---

## 1. Ablation — which neurons are actually necessary?

**Question.** If you remove a cell type, does the escape survive? Which pathway
carries it — LC4, LPLC2, or both?

**Method.** Run the shared protocol once per condition:

- `baseline` — nothing removed
- `LC4` — remove every neuron whose cell type is `LC4`
- `LPLC2` — same for `LPLC2`
- `sensory` — remove all sensory neurons
- `inter` — remove all interneurons
- `motor` — remove both DNp01 (expected: no output — a sanity check)

**Ablation semantics — remove, not silence.** The ablated neurons are taken out of
the network: their incoming **and** outgoing edges are zeroed, they receive no
stimulus, and they are excluded from the readout. This models a full lesion. It is
deliberately *not* a "clamp the membrane" silencing, which would leave their
synapses in place.

**Output.** Table: condition, neurons removed, `motor_spikes`, `first_spike_ms`,
and the percentage of the baseline. Saved to `experiments/results/ablation.csv`.

**How to read it.** A large drop when a group is removed means that group is on the
critical path *for this stimulus*. It says nothing about other stimuli or behaviours.

---

## 2. Null model — does the specific wiring matter?

**Question.** Would *any* graph with the same degree sequence produce the same
response? This is the only question here that does not already have a settled
answer at this scale.

**Method.** Build two nulls and run the identical protocol on each:

1. **Degree-preserving (primary null).** Randomly rewire the edges with repeated
   directed double-edge swaps so the **in-degree and out-degree sequences are
   preserved exactly**, carrying the synaptic weights with the edges. Verify and
   print that the degree sequences match the real ones (max absolute difference 0).
2. **Erdős–Rényi (secondary null).** Random edges over the same node set with the
   same total edge count, no degree constraint. This is the "any sparse graph"
   baseline.

Run `--n` null samples (default 50). Report the real value against the null
distribution: mean, standard deviation, and **the percentile of the real value**
(for `motor_spikes` and `first_spike_ms`).

**Output.** `experiments/results/null_model.csv`, one row per sample plus the real
circuit, and a printed summary.

**How to read it — and how not to.** The real circuit sitting at, say, the 97th
percentile of the degree-preserving null is evidence that the *specific topology*
contributes something beyond the degree sequence. It is **not** proof of "design"
or "function": a percentile is a rank within a chosen null, and a different null or
metric could move it. A null result (real ≈ null mean) is also a result, and must be
reported as plainly as a positive one.

---

## 3. Dose–response — how sensitive is the reflex?

**Question.** How does the response depend on stimulus intensity, and how sharp is
the threshold?

**Method.** Sweep the pulse amplitude (`amp`) over e.g. 0.0 → 1.0 in ~8–10 points,
with `--trials` repeats each (a new seed per trial). Report, per amplitude:
the **trigger probability** (`triggered` fraction), the mean `motor_spikes`, and the
mean `first_spike_ms`.

**Output.** `experiments/results/dose_response.csv` and a printed table. This is the
in-silico analogue of a psychometric curve.

**How to read it.** A sharp step means the response is close to all-or-none for this
circuit; a gradual slope means a graded, noisy threshold. Either is informative — the
*shape* is the result.

---

## 4. Latency — how fast is the loop?

**Question.** Two different latencies, which are easy to conflate:

- **In-silico latency:** pulse onset → first DNp01 spike (from §1/§3, in simulated
  milliseconds). Compare with the ~4 ms Giant Fiber latency of the real animal.
- **Hardware loop latency:** sensor sample → serial round trip → servo command, in
  wall-clock milliseconds, including the 20 ms Uno cadence.

**Method.** The first comes free from the metrics above. The second is a separate
bench measurement: timestamp the `L` command that follows a stimulus-triggering
sample. Report both, and say explicitly which is which — they are not the same number.

---

## Reproducibility

- Every run takes a `--seed`; the same seed gives bit-identical metrics.
- The null model samples are seeded from a fixed base so the whole experiment is
  replayable.
- `experiments/results/*.csv` are the primary output; the printed tables are a view
  of them. Reported numbers must always quote the CSV they came from.

## What this does and does not show

**Does:** quantify the response of this specific 583-neuron subcircuit to controlled
in-silico stimuli, and test whether the specific topology carries information beyond
its degree sequence.

**Does not:** demonstrate biological realism. The neuron model is LIF, synapses are
static (no plasticity, no short-term depression), transmitters are collapsed to a
sign, the circuit is a small subcircuit and not the whole brain, and the servo/flight
readout is an engineered mapping rather than a simulation of the motor system. These
are honest toys with real wiring — useful for intuition and for teaching, not for
claims about *Drosophila*.

## Planned layout

```
experiments/
  harness.py         # shared protocol + metrics + modification hooks
  ablation.py        # §1
  null_model.py      # §2
  dose_response.py   # §3
  README.md          # this file (or a pointer to it)
  results/           # generated CSVs (gitignored)
```

The only change needed outside `experiments/` is storing the per-node cell type in
`brain/data/circuit.npz`, so ablation can target LC4 vs LPLC2 without the
gitignored source CSV.
