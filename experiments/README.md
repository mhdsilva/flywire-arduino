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

## Results (2026-09-12, saved circuit, seed 0)

Reproduced with the commands above. These are the values in `results/*.csv`.

### Ablation — across amplitudes

```
condition  removed      0.20        0.35        0.50        0.75        1.00
baseline         0    6 (100%)   14 (100%)   20 (100%)   27 (100%)   32 (100%)
LC4            104    0 (  0%)    4 ( 29%)    8 ( 40%)   13 ( 48%)   17 ( 53%)
LPLC2          210    0 (  0%)    4 ( 29%)    8 ( 40%)   12 ( 44%)   16 ( 50%)
sensory        314    0 (  0%)    0 (  0%)    0 (  0%)    0 (  0%)    0 (  0%)
inter          267    7 (117%)   16 (114%)   23 (115%)   29 (107%)   33 (103%)
motor            2    0 (  0%)    0 (  0%)    0 (  0%)    0 (  0%)    0 (  0%)
```

- **LC4 and LPLC2 are symmetric: each carries roughly half the drive.** Neither is
  individually necessary — but at `amp = 0.2`, just above threshold, losing either
  one abolishes the response entirely. **That is exactly why the sweep exists:** a
  single near-threshold run would have read as "both are individually necessary".
- **The interneurons are net-inhibitory here.** Removing all 267 raises the output
  by 3-17% at every amplitude — consistent across the sweep, not a threshold effect.
- `sensory` (removing the whole input) and `motor` (removing the readout) give zero
  by construction — the two sanity checks.

### Null model

```
real circuit: motor_spikes 6, first_spike_ms 32.4 ms
degree preservation: max |out-deg diff| = 0   max |in-deg diff| = 0

degree-preserving null (n=20): motor_spikes mean 1.70 sd 1.82 -> real 6 = 100th percentile
                               first_spike_ms mean 35.9 ms -> real 32.4 = 20th percentile (10/20 fired)

Erdos-Renyi null (n=20):       motor_spikes mean 0.00 -> real 6 = 100th percentile (0/20 fired)
```

At the default `--n 50` the real circuit sits at the **99th percentile** of the
degree-preserving null (mean 1.74, sd 1.78), latency at the 16th (29/50 fired), and
the Erdős–Rényi null still never fires (0/50).

- **The specific topology matters.** The real circuit emits several times more motor
  spikes than degree-matched random wiring, and a random same-density graph never
  fires at all. The wiring carries information beyond its degree sequence.
- The latency effect is smaller and noisier than the spike-count effect (many nulls
  never fire, so their latency is undefined), so the spike count is the honest
  headline.
- `n = 20` is a small sample; the percentile has wide error bars. The default is 50.

### Dose–response

```
   amp  trigger_p  mean_spikes  mean_first_ms
 0.000       0.00         0.00              -
 0.125       1.00         1.00          76.40
 0.250       1.00         9.00          23.70
 0.375       1.00        16.00          15.10
 0.500       1.00        20.00          11.60
 0.625       1.00        25.00           9.70
 0.750       1.00        27.00           8.60
 0.875       1.00        30.00           7.80
 1.000       1.00        32.00           7.30
```

The trigger is a **sharp step** (see the determinism note above): the graded
information is in the spike count and the latency, which falls from ~76 ms just
above threshold to ~7 ms at saturation.

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
