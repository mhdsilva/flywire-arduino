# Findings

What the experiments in this directory actually produced, on the saved circuit
(2026-09-12), and what each one is — and is not — worth claiming.

The protocol, metrics and interpretation rules live in
[`docs/EXPERIMENTS.md`](../docs/EXPERIMENTS.md); the implementation and commands in
[`README.md`](README.md). This file is the result digest.

Reproduce (wall times measured on the i5-1135G7 laptop, 2026-09-12):

```bash
.venv/bin/python experiments/ablation.py                                  # ~20 s
.venv/bin/python experiments/ablation.py --types --min-cells 1            # ~432 s
.venv/bin/python experiments/null_model.py --n 100                        # ~207 s
.venv/bin/python experiments/dose_response.py --trials 20 --noise-sigma 0.0    # ~128 s
.venv/bin/python experiments/dose_response.py --trials 20 --noise-sigma 0.05   # ~162 s
.venv/bin/python experiments/dose_response.py --points 16 --amp-max 0.3 \
    --trials 20 --noise-sigma 0.5                                         # ~304 s
```

---

## 1. The specific wiring matters

The real 583-neuron subcircuit, versus nulls with the **same in- and out-degree
sequences** (directed double-edge swaps; the code verifies the degree sequences
match exactly) and an Erdős–Rényi graph of the same edge count:

| | motor spikes | percentile vs. degree-preserving null |
|---|---:|---:|
| **real circuit** | **6** | — |
| degree-preserving null (n=100) | 1.700 ± 1.676 | **99.0th** |
| Erdős–Rényi (n=100) | 0.00 ± 0.00 | **100th** (0/100 fired) |
| degree check | max abs diff = **0** | |

The result is stable against sample size: real at the 100th percentile at n=20,
the 99th at n=50 (null mean 1.74 ± 1.78) and the 99.0th at n=100. Randomising
who talks to whom, while keeping how many partners each neuron has, removes most
of the response; an Erdős–Rényi graph of the same density does not fire at all.

On the latency metric the real circuit's first spike is 32.4 ms, at the **15th
percentile** of the degree-preserving null (low = fast), among the 66/100 nulls
that fired at all. So the topology also makes the response faster than most
degree-matched random graphs, though the margin is smaller than for spike count.
The Erdős–Rényi latency percentile (0.0th) is degenerate — no ER null fired, so
there is nothing to be faster than — and should be read as "not measurable", not
as "infinitely fast".

**Claim that is supported:** this topology carries information beyond its degree
sequence. Randomising who talks to whom, while keeping how many partners each
neuron has, removes most of the response.

**Claim that is not supported:** anything about biological function or "design". A
percentile is a rank inside a chosen null. A different null, metric or stimulus
level could move it.

## 2. The near-threshold trap (the methodological finding)

At a stimulus amplitude just above threshold, removing **LC4** *or* **LPLC2**
abolished the response entirely. Run only there, the honest-looking conclusion
would have been:

> "Both cell types are individually necessary for the escape."

It is false. Sweeping the amplitude:

```
condition  removed      0.20        0.35        0.50        0.75        1.00
baseline         0    6 (100%)   14 (100%)   20 (100%)   27 (100%)   32 (100%)
LC4            104    0 (  0%)    4 ( 29%)    8 ( 40%)   13 ( 48%)   17 ( 53%)
LPLC2          210    0 (  0%)    4 ( 29%)    8 ( 40%)   12 ( 44%)   16 ( 50%)
sensory        314    0 (  0%)    0 (  0%)    0 (  0%)    0 (  0%)    0 (  0%)
inter          267    7 (117%)   16 (114%)   23 (115%)   29 (107%)   33 (103%)
motor            2    0 (  0%)    0 (  0%)    0 (  0%)    0 (  0%)    0 (  0%)
```

The two are **symmetric and each carries roughly half the drive**. Neither is
necessary. The "necessity" was an artefact of a circuit sitting close to threshold:
at 0.2 the total drive is barely enough, so removing a third of it crosses back
under.

**This is the result about method, not about flies:** a single stimulus level
produced a confident false claim, and the sweep caught it. It is why the ablation
runner reports across amplitudes by design.

## 3. The interneurons are net-inhibitory here

Removing all 267 interneurons **raises** the output by 3–17%, at every amplitude in
the sweep — so it is not a threshold artefact. The 267 neurons between the sensory
and motor layers are, in aggregate, suppressing.

Consistent across the sweep, which is the interesting part: it survives exactly the
check that killed the LC4/LPLC2 claim.

## 4. A sharp deterministic threshold, a graded latency

```
   amp  trigger_p  mean_spikes  sd_spikes  mean_first_ms
 0.000       0.00         0.00       0.00              -
 0.125       1.00         1.00       0.00          76.40
 0.250       1.00         9.00       0.00          23.70
 0.375       1.00        16.00       0.00          15.10
 0.500       1.00        20.00       0.00          11.60
 0.625       1.00        25.00       0.00           9.70
 0.750       1.00        27.00       0.00           8.60
 0.875       1.00        30.00       0.00           7.80
 1.000       1.00        32.00       0.00           7.30
```

(`--trials 20 --noise-sigma 0.0`, `results/dose_response.csv`.)

With no injected noise the LIF model is **deterministic**, so the trigger is a
step, the sd is exactly zero and repeats are identical. No noise was invented to
manufacture a curve. The graded information is the spike count and the
**latency**, which falls from ~76 ms just above threshold to ~7 ms at
saturation. Section 5 adds an explicitly injected noise source and reports what
it does — and does not — change.

## 5. An injected-noise psychometric curve

This section is about an **injected stimulus**, not a claim that the brain is
noisy. `harness.run_trial(..., noise_sigma=)` adds seeded Gaussian noise to the
external current of the sensory neurons at every integration step of the pulse
and readout (never the warm-up). The LIF model, synapses and readout are
unchanged; this injected drive is the only source of stochasticity, and the same
seed reproduces a trial exactly. Noise units are the same as `STIM_GAIN`: the
external-current units of the LIF update, where the threshold is 1.0 and R_m=1.

At the small levels suggested for the experiment (0.02, 0.05, 0.1), the default
0..1 / 9-point grid still shows a **step**, not a curve:

| amp | p(σ=0.0) | p(σ=0.02) | p(σ=0.05) | p(σ=0.1) |
|---:|---:|---:|---:|---:|
| 0.000 | 0.00 | 0.00 | 0.00 | 0.00 |
| 0.125 | 1.00 | **0.00** | **0.00** | **0.00** |
| 0.250 | 1.00 | 1.00 | 1.00 | 1.00 |
| 0.375 | 1.00 | 1.00 | 1.00 | 1.00 |
| 0.500 | 1.00 | 1.00 | 1.00 | 1.00 |
| 0.625 | 1.00 | 1.00 | 1.00 | 1.00 |
| 0.750 | 1.00 | 1.00 | 1.00 | 1.00 |
| 0.875 | 1.00 | 1.00 | 1.00 | 1.00 |
| 1.000 | 1.00 | 1.00 | 1.00 | 1.00 |

(20 trials per point; full CSVs in `results/dose_response.csv` and
`results/dose_response_noise_sigma0.02.csv`, `_0.05.csv`, `_0.1.csv`.)

Two honest observations:

- Injected noise **removes** the fragile deterministic response at amp=0.125
  (1 spike at 76.4 ms without noise; 0/20 trials at σ=0.02, 0.05 and 0.1). The
  knife-edge single-spike state is destroyed by any perturbation, so the
  apparent threshold moves *up*, not down.
- Above threshold the response is robust: noise adds only a little spike-count
  variance (e.g. at amp=0.5 the sd rises from 0.00 to 0.43 as σ goes 0→0.1).

The graded window exists but is narrower than that grid. A finer sweep
(`--points 16 --amp-max 0.3`, step 0.02) resolves it:

| amp | p(σ=0.05) | p(σ=0.1) | p(σ=0.5) |
|---:|---:|---:|---:|
| 0.00–0.10 | 0.00 | 0.00 | 0.00 |
| 0.12 | 0.00 | 0.00 | **0.60** |
| 0.14 | **0.75** | 0.00 | 1.00 |
| 0.16 | 1.00 | **1.00** | 1.00 |
| 0.18–0.30 | 1.00 | 1.00 | 1.00 |

(`results/dose_response_fine_sigma0.05.csv`, `_0.1.csv`, `_0.5.csv`.)

At σ=0.5 the curve is a resolved sigmoid: p=0 at amp=0.10, 0.60 at 0.12, 1.00 at
0.14. As σ grows the 50%-crossing moves to *lower* amplitude (roughly amp≈0.13–0.14
at σ=0.05, ≈0.15 at σ=0.1, ≈0.115–0.12 at σ=0.5), which is what an injected-drive
model predicts. The latency at the graded points is long (≈61 ms at σ=0.05,
amp=0.14; ≈73 ms at σ=0.5, amp=0.12), consistent with §4's near-threshold
latency.

Why does small noise barely bend the curve? The injected noise is white
(independent at every 0.1 ms step) and is low-pass filtered by the membrane
(τ_m=20 ms) and synapse (τ_syn=5 ms), so at σ≤0.1 the effective membrane-potential
fluctuation is small relative to the threshold of 1.0. Larger injected noise is
needed to move the decision. This is a property of the injected stimulus, not a
biological finding.

**Does not show:** that the brain is noisy, that σ has a biological value, or
what the fly's true psychometric curve is. σ is arbitrary and was not fitted; the
threshold location is a function of it. The exercise shows that a graded curve is
generated by stochastic drive and that its location tracks that drive, and it
shows how much (little) a given amount of membrane-filtered white noise matters.

## 6. Per-cell-type ablation: only LC4 and LPLC2 carry the response

`ablation.py --types` ablates every FlyWire `primary_type` with at least
`--min-cells` neurons, plus baseline. At the default `--min-cells 10` only LC4
(104) and LPLC2 (210) qualify, because every other type in the subcircuit is a
1–8-cell interneuron (plus the 2 DNp01 motor neurons), so the default `--types`
run reproduces the two named conditions below.

Running the whole inventory (`--types --min-cells 1`, 123 types + baseline,
`results/ablation_types_min1.csv`) confirms this:

```
condition  removed      0.20        0.35        0.50        0.75        1.00
baseline         0    6 (100%)   14 (100%)   20 (100%)   27 (100%)   32 (100%)
LC4            104    0 (  0%)    4 ( 29%)    8 ( 40%)   13 ( 48%)   17 ( 53%)
LPLC2          210    0 (  0%)    4 ( 29%)    8 ( 40%)   12 ( 44%)   16 ( 50%)
DNp01            2    0 (  0%)    0 (  0%)    0 (  0%)    0 (  0%)    0 (  0%)
DNp103           2    6 (100%)   14 (100%)   19 ( 95%)   27 (100%)   31 ( 97%)
PVLP122b         4    6 (100%)   14 (100%)   20 (100%)   26 ( 96%)   31 ( 97%)
PVLP151          4    6 (100%)   14 (100%)   19 ( 95%)   25 ( 93%)   30 ( 94%)

all other 118 types: exactly 100% at every amplitude (6, 14, 20, 27, 32)
```

- **DNp01** (2 motor neurons) removes the readout entirely — the sanity check.
- **LC4 / LPLC2** are the only substantial contributors, each carrying about
  half the drive (the §2 result, now confirmed across the full inventory).
- **DNp103, PVLP122b, PVLP151** show small suprathreshold drops (3–7%). They are
  consistent across several amplitudes for PVLP151, so likely a minor real
  contribution, but nothing like a necessary pathway, and the integer spike
  counts at this scale mean a difference of 1–2 spikes is at the edge of what a
  single seed can distinguish.
- **All 118 other types** are exactly neutral at every amplitude.

So nothing outside LC4/LPLC2 carries a meaningful share of the response. This is
consistent with §3 — removing *all* 267 interneurons raises the output, yet
removing any *individual* interneuron type does nothing (or very slightly lowers
it). The aggregate inhibition is distributed across many small types, not
concentrated in one.

---

## What this does and does not show

**Does:** quantify this specific subcircuit's response, test its topology against a
degree-preserving null, expose how stimulus level changes what an ablation
appears to prove, and show what an explicitly *injected* stochastic drive does to
the threshold.

**Does not:** demonstrate biology. LIF neurons, static synapses, a sign-collapsed
view of neurotransmitters, one subcircuit out of a brain, and an engineered
servo/flight readout outside these experiments. The experiments are in-silico; no
hardware was involved in producing any number above.

**New caveats for the injected noise (§5).** The noise is an external stimulus we
chose, not a property of the model: the neuron model is deterministic and was not
modified, and no noise is drawn when `noise_sigma=0.0`. `σ` is white,
uncorrelated, added only to the sensory external current, and its value is
arbitrary — it was not fitted to the animal. The psychometric threshold location
is a function of that choice, so the curves are conditional on `σ`, not
estimates of the fly's noise. Real neural variability is structured (correlated
synaptic and channel noise), so this exercise can show *that* stochastic drive
produces a graded curve, not *what* the biological curve is.

**New caveats for the per-type ablation (§6).** "Exactly 100%" means the motor
spike count is identical to baseline for that seed; it is not a formal test of
zero effect, and only one seed was used per condition. The small effects on
DNp103/PVLP122b/PVLP151 are 1–2 spikes and sit at the resolution limit of the
readout. The full inventory covers every `primary_type` with ≥1 neuron (three
nodes with an empty type string match nothing and were not ablated
individually).

## Article angles

Each of these is a separate, self-contained story:

1. **"The experiment that stopped me from publishing something wrong."** The
   strongest one. A confident, publishable-looking claim ("both cell types are
   necessary") that was purely an artefact of testing at one stimulus level — caught
   by designing the amplitude sweep in advance.
2. **"Does the connectome's specific wiring matter? A null model on my laptop."** The
   narrow, honest version of the result: real ≫ degree-matched random, and random
   never fires at all. With the caveats up front.
3. **"A deterministic brain has no psychometric curve."** What happens to a
   threshold experiment when the model has no noise — and how the curve you get
   back depends entirely on the noise you inject. The honest punchline: you can
   manufacture the curve, but the threshold is then a property of your injected
   `σ`, not of the brain.
4. **"The neurons in the middle were holding it back."** A net-inhibitory aggregate
   in a 583-neuron circuit, consistent across stimulus levels — and distributed
   so that no single interneuron type carries it.
5. **"Write the design before the code."** The methodology story: the design document
   named the trap before any result existed, which is the only reason the false
   claim in (1) never got written.

## Open questions

- The null-percentile estimate is stable from n=20 to n=100 (100th → 99th →
  99.0th); does it hold at n=200?
- Individual interneuron types are inert, but removing all of them raises the
  output: is the inhibition redundant by design, or just spread thinly enough
  that no small lesion is visible?
- The injected-noise threshold moves with `σ` as expected. Is there a principled
  way to choose `σ` (e.g. fit it to a measured trigger-variance), or is any such
  fit circular because the model's only variability is the one we added?
- **Hardware latency** (§4 of the design): the in-silico numbers above say nothing
  about the physical loop, which adds serial and servo time.
