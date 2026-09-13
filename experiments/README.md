# Experiments

Implementation of the experimental design in [`docs/EXPERIMENTS.md`](../docs/EXPERIMENTS.md).
The design document is the spec: it fixes the protocol, metrics and interpretation.
This file documents how the code implements them and what the results mean.

All runners import `experiments/harness.py`, which is the single implementation of
the shared protocol. If the protocol changes, it changes there once.

## Shared protocol

`harness.run_trial(amp, pulse_ms=100.0, ablate=None, weights=None, seed=0)`:

1. **Reset** (`LIF.reset()`).
2. **Warm-up:** 200 ms, no stimulus.
3. **Pulse:** rectangular stimulus of amplitude `amp` for `pulse_ms`, applied to
   the sensory neurons only: `ext[sensory] = amp * STIM_GAIN`.
4. **Readout:** 500 ms, no stimulus.

Integration uses the repo constants `DT = 0.1 ms`, `WEIGHT_SCALE = 3e-4`,
`STIM_GAIN = 0.5` and `run_brain.step_ms`. Motor spikes are counted over the
pulse + readout window (600 ms); the warm-up never enters a metric. `ablate` and
`weights` are the modification hooks (see below).

### Baseline amplitude

Default `amp = 0.2`. This was calibrated against the protocol, not assumed:
a 100 ms pulse gives 0 spikes at 0.10 and 0.12, 1 at 0.15, 4 at 0.18, 6 at 0.20
(first spike 32.4 ms), up to 32 at 1.0. So 0.2 clearly triggers the escape
without saturating — there is headroom toward `amp = 1`. The repo's earlier
continuous-stimulus measurement (0.2 fires, 0.1 does not) is consistent with
this.

### Determinism and seeds — read this

The LIF model in `brain/lif.py` has **no stochastic term**. `seed` is accepted by
every runner for protocol compliance, but it does not change a trial: the same
`amp` gives bit-identical metrics for every seed. No noise has been invented to
manufacture trial-to-trial variance.

Consequence: in the dose–response, all `--trials` repeats at one amplitude are
identical, so `trigger_probability` is exactly 0 or 1 and the reported threshold
is a sharp step. That is the honest result for this model, not a missing feature.
The meaningful curve is the spike count / latency vs amplitude, which is graded.

## Metrics

| Metric | Definition |
|---|---|
| `motor_spikes` | total DNp01 spikes over pulse + readout |
| `first_spike_ms` | pulse onset → first DNp01 spike, or `None` |
| `peak_rate_hz` | max DNp01 spikes in a 20 ms bin / 0.02 / `n_motor` |
| `triggered` | `motor_spikes > 0` |
| `bins_with_spikes` | number of 20 ms bins containing a DNp01 spike |

## Ablation semantics — remove, not silence

An ablated neuron is taken out of the network: its incoming **and** outgoing
edges are zeroed (`D @ W @ D`), it receives no stimulus, and (for motor) it is
excluded from the readout. This is a full lesion. It is deliberately *not* a
membrane clamp, which would leave the synapses in place. Cell types come from the
`sensory`/`inter`/`motor` roles or the FlyWire `primary_type` in `node_types`.

## Experiments

### 1. Ablation — `ablation.py`

Conditions: `baseline`, `LC4`, `LPLC2`, `sensory`, `inter`, `motor`.

**The amplitude sweep is the point.** Every condition runs across several stimulus
amplitudes (`--amps`, default `0.2 0.35 0.5 0.75 1.0`) and each cell is
`motor_spikes (% of baseline)`. At a near-threshold amplitude, losing any drive can
abolish the response and look "necessary"; only at suprathreshold amplitudes does
the group's real contribution appear. A single amplitude would hide that — and
would have supported a false claim.

```
.venv/bin/python experiments/ablation.py             # sweep, ~14 s on i5-1135G7
.venv/bin/python experiments/ablation.py --amp 0.5   # a single amplitude
```

Writes `results/ablation.csv` (one row per amplitude x condition).

### 2. Null model — `null_model.py`

Two nulls, run through the identical protocol:

1. **Degree-preserving directed rewiring (primary).** Repeated directed
   double-edge swaps. A swap takes edges `a→b`, `c→d` and makes `a→d`, `c→b`,
   which preserves every node's in- and out-degree exactly. Weights stay with
   their edge index, so the weight multiset is unchanged. Swaps that would make a
   self-loop or a duplicate edge are rejected. For every sample the code verifies
   the in/out degree sequences against the real circuit and prints the maximum
   absolute difference (must be 0).
2. **Erdős–Rényi (secondary).** The same number of edges placed uniformly at
   random over the same 583 nodes (no self-loops), with the real weight multiset
   permuted onto those edges. No degree constraint — the "any sparse graph"
   baseline.

```
.venv/bin/python experiments/null_model.py --n 20     # ~42 s
.venv/bin/python experiments/null_model.py            # default --n 50, ~104 s
```

Writes `results/null_model.csv` (one row per sample plus a tagged `real` row) and
prints, for `motor_spikes` and `first_spike_ms`, the null mean, sd and the
percentile of the real value. For latency a *low* percentile is the fast/strong
outcome; non-firing nulls are ranked as `+inf`, and the number that fired is
printed.

### 3. Dose–response — `dose_response.py`

Sweeps `amp` over `0 .. 1` in `--points` steps with `--trials` repeats (new seed
per trial). Prints trigger probability, mean `motor_spikes` and mean
`first_spike_ms`; writes `results/dose_response.csv`.

```
.venv/bin/python experiments/dose_response.py --trials 5   # ~33 s
```

### Harness self-test

```
.venv/bin/python experiments/harness.py --amp 0.2   # ~1.4 s
```

## Results

The results, their interpretation, the caveats and the article angles live in
[`FINDINGS.md`](FINDINGS.md), so this file stays about *how* to run the
experiments. Headline: across the amplitude sweep, LC4 and LPLC2 each carry about
half the drive (neither is individually necessary), the interneurons are
net-inhibitory, and the real circuit sits at the 99th–100th percentile of a
degree-preserving null.

## What this does and does not show

**Does:** quantify the response of this specific 583-neuron subcircuit (sensory
314, inter 267, motor 2; LC4 104, LPLC2 210, DNp01 2) to controlled in-silico
stimuli, and test whether the specific topology carries information beyond its
degree sequence.

**Does not:** demonstrate biological realism. The neuron model is LIF, synapses
are static, transmitters are collapsed to a sign, this is a small subcircuit and
not the whole brain, and the servo/flight readout is an engineered mapping. These
are honest toys with real wiring.

## Pointer

The questions, protocol, metric definitions and reading instructions are fixed in
[`docs/EXPERIMENTS.md`](../docs/EXPERIMENTS.md). This file only documents the
implementation; when the two disagree, the design document wins.
