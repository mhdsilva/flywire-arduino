# Findings

What the experiments in this directory actually produced, on the saved circuit
(2026-09-12), and what each one is — and is not — worth claiming.

The protocol, metrics and interpretation rules live in
[`docs/EXPERIMENTS.md`](../docs/EXPERIMENTS.md); the implementation and commands in
[`README.md`](README.md). This file is the result digest.

Reproduce:

```bash
.venv/bin/python experiments/ablation.py                # ~14 s
.venv/bin/python experiments/null_model.py --n 50       # ~105 s
.venv/bin/python experiments/dose_response.py --trials 5 # ~33 s
```

---

## 1. The specific wiring matters

The real 583-neuron subcircuit, versus nulls with the **same in- and out-degree
sequences** (directed double-edge swaps; the code verifies the degree sequences
match exactly) and an Erdős–Rényi graph of the same edge count:

| | motor spikes | percentile vs. degree-preserving null |
|---|---:|---:|
| **real circuit** | **6** | — |
| degree-preserving null (n=20) | 1.70 ± 1.82 | **100th** |
| Erdős–Rényi (n=20) | 0.00 | **100th** (0/20 fired) |
| degree check | max abs diff = **0** | |

At the default `--n 50`: real at the **99th percentile** (null mean 1.74, sd 1.78),
and the Erdős–Rényi null still never fires (0/50).

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

## 4. A sharp threshold, a graded latency

```
   amp  trigger_p  mean_spikes  mean_first_ms
 0.000       0.00         0.00              -
 0.125       1.00         1.00          76.40
 0.500       1.00        20.00          11.60
 1.000       1.00        32.00           7.30
```

The LIF model here is **deterministic**, so the trigger is a step and repeats are
identical. No noise was invented to manufacture a curve. The graded information is
the spike count and the **latency**, which falls from ~76 ms just above threshold to
~7 ms at saturation.

---

## What this does and does not show

**Does:** quantify this specific subcircuit's response, test its topology against a
degree-preserving null, and expose how stimulus level changes what an ablation
appears to prove.

**Does not:** demonstrate biology. LIF neurons, static synapses, a sign-collapsed
view of neurotransmitters, one subcircuit out of a brain, and an engineered
servo/flight readout outside these experiments. The experiments are in-silico; no
hardware was involved in producing any number above.

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
   threshold experiment when the model has no noise — and why real brains being
   noisy is a feature, not a nuisance.
4. **"The neurons in the middle were holding it back."** A net-inhibitory aggregate
   in a 583-neuron circuit, consistent across stimulus levels.
5. **"Write the design before the code."** The methodology story: the design document
   named the trap before any result existed, which is the only reason the false
   claim in (1) never got written.

## Open questions

- The null-percentile estimate rests on n=20–50 samples; does it hold at n=200?
- What about the **other cell types** in the subcircuit (the `node_types` array has
  every FlyWire type, not just LC4/LPLC2)?
- Would an **injected-noise** version turn the step into a real psychometric curve,
  and at what noise level does the threshold stop being reliable?
- **Hardware latency** (§4 of the design): the in-silico numbers above say nothing
  about the physical loop, which adds serial and servo time.
