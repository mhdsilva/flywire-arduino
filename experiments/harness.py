#!/usr/bin/env python3
"""Shared experimental harness: one stimulus protocol, one set of metrics.

This module is the single implementation of the protocol fixed in
``docs/EXPERIMENTS.md``. Every runner imports it so the experiments are
comparable and cannot quietly diverge.

Protocol (per trial)
--------------------
1. Reset the network (``LIF.reset()``).
2. Warm-up: 200 ms with no stimulus.
3. Pulse: rectangular stimulus of amplitude ``amp`` (in ``STIM_GAIN`` units)
   for ``pulse_ms``, applied to the sensory neurons only:
   ``ext[sensory] = amp * STIM_GAIN``.
4. Readout: 500 ms with no stimulus.

Integration step is ``DT = 0.1 ms`` (the repo default), driven through
``run_brain.step_ms``. Motor spikes are counted over the pulse + readout window;
the warm-up is never part of any metric.

Determinism
-----------
The LIF model contains no stochastic term. ``seed`` is accepted by every runner
for protocol/reproducibility compliance, but it does not change a trial: the
same ``amp`` gives bit-identical metrics for every seed. This is documented
rather than patched over -- no noise is invented to manufacture variance.
"""

from __future__ import annotations

import argparse
import os
import sys

import numpy as np
import scipy.sparse as sp

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
BRAIN = os.path.join(REPO, "brain")
if BRAIN not in sys.path:
    sys.path.insert(0, BRAIN)

from lif import LIF  # noqa: E402
from run_brain import DT, STIM_GAIN, WEIGHT_SCALE, step_ms  # noqa: E402

CIRCUIT_PATH = os.path.join(BRAIN, "data", "circuit.npz")
RESULTS_DIR = os.path.join(HERE, "results")

WARMUP_MS = 200.0
READOUT_MS = 500.0
BIN_MS = 20.0

# Chosen by calibration against the existing repo measurement: continuous
# stim 0.2 fires DNp01, stim 0.1 does not. Under this pulsed protocol 0.2 also
# fires (6 spikes, first at ~32 ms) while 0.1 produces none, so 0.2 is a
# baseline that clearly responds without saturating.
DEFAULT_AMP = 0.2

_CIRCUIT = None


def load_circuit():
    """Return ``(W, roles, node_types, node_ids)`` for the saved subcircuit.

    ``node_types`` is the FlyWire ``primary_type`` per node. Three nodes carry
    an empty type string; they are kept as ``""`` and simply match no cell-type
    condition.
    """
    global _CIRCUIT
    if _CIRCUIT is None:
        d = np.load(CIRCUIT_PATH)
        n = len(d["node_ids"])
        W = sp.csr_matrix(
            (d["data"].astype(np.float64), (d["rows"], d["cols"])),
            shape=(n, n),
        )
        _CIRCUIT = (W, d["roles"], d["node_types"].astype(str), d["node_ids"])
    return _CIRCUIT


def run_trial(amp, pulse_ms=100.0, ablate=None, weights=None, seed=0):
    """Run one protocol trial and return the metric dict.

    Parameters
    ----------
    amp : float
        Pulse amplitude in ``STIM_GAIN`` units (the ``stim`` value in
        ``run_brain.py``).
    pulse_ms : float
        Pulse duration in milliseconds.
    ablate : set[int] | None
        Node indices to remove (see ablation semantics below).
    weights : scipy.sparse matrix | None
        Custom raw-weight matrix (used by the null model). ``None`` = the real
        circuit. It is scaled by ``WEIGHT_SCALE`` exactly like the real one.
    seed : int
        Protocol seed. Present for reproducibility; the model is deterministic,
        so it does not alter the result.

    Ablation semantics -- remove, not silence
    -----------------------------------------
    A removed neuron is taken out of the network: its incoming *and* outgoing
    edges are zeroed, it is excluded from the sensory stimulus, and it is
    excluded from the motor readout. This is a full lesion, not a membrane
    clamp (which would leave the synapses in place). Edges are zeroed by
    multiplying the weight matrix by a 0/1 diagonal on both sides
    (``D @ W @ D``), which kills every row and column of the ablated set.

    Returns
    -------
    dict with ``motor_spikes``, ``first_spike_ms``, ``peak_rate_hz``,
    ``triggered``, ``bins_with_spikes``.
    """
    W, roles, _node_types, _node_ids = load_circuit()
    base = W if weights is None else sp.csr_matrix(weights, dtype=np.float64)
    ablate = set() if ablate is None else {int(a) for a in ablate}
    n = base.shape[0]

    if ablate:
        keep = np.ones(n, dtype=np.float64)
        keep[np.fromiter(ablate, dtype=np.int64)] = 0.0
        D = sp.diags(keep)
        base = (D @ base @ D).tocsr()

    # The LIF model has no stochastic term, so no RNG is drawn here. ``seed`` is
    # accepted for protocol compliance but leaves the dynamics bit-identical;
    # we deliberately do not invent noise to manufacture trial variance.
    _ = seed

    net = LIF(base, roles, weight_scale=WEIGHT_SCALE, dt=DT)
    net.reset()

    sensory = roles == "sensory"
    motor = roles == "motor"
    if ablate:
        idx = np.fromiter(ablate, dtype=np.int64)
        sensory = sensory.copy()
        motor = motor.copy()
        sensory[idx] = False
        motor[idx] = False
    n_motor = int(motor.sum())

    # 1) warm-up, no stimulus. step_ms with ext=None is the repo convention.
    step_ms(net, None, WARMUP_MS)

    # 2) pulse + 3) readout. Stepped one DT at a time so motor spikes can be
    # timestamped for latency and binned for the rate metrics.
    stim = np.zeros(n, dtype=np.float64)
    stim[sensory] = amp * STIM_GAIN
    total_steps = int(round((pulse_ms + READOUT_MS) / DT))
    pulse_steps = int(round(pulse_ms / DT))
    motor_counts = np.zeros(total_steps, dtype=np.int64)
    for k in range(total_steps):
        ext = stim if k < pulse_steps else None
        counts = step_ms(net, ext, DT)
        if n_motor:
            motor_counts[k] = counts[motor].sum()

    motor_spikes = int(motor_counts.sum())

    first_spike_ms = None
    fired = np.flatnonzero(motor_counts)
    if fired.size:
        # A spike detected by the step covering [t, t+DT) is stamped at t+DT.
        first_spike_ms = float((int(fired[0]) + 1) * DT)

    bin_steps = int(round(BIN_MS / DT))
    n_bins = total_steps // bin_steps
    if n_bins:
        bins = motor_counts[: n_bins * bin_steps].reshape(n_bins, bin_steps).sum(axis=1)
    else:
        bins = np.zeros(0, dtype=np.int64)
    bins_with_spikes = int((bins > 0).sum())

    peak_rate_hz = 0.0
    if n_motor and bins.size:
        bin_s = bin_steps * DT / 1000.0
        peak_rate_hz = float(bins.max() / bin_s / n_motor)

    return {
        "motor_spikes": motor_spikes,
        "first_spike_ms": first_spike_ms,
        "peak_rate_hz": peak_rate_hz,
        "triggered": bool(motor_spikes > 0),
        "bins_with_spikes": bins_with_spikes,
    }


def ensure_results_dir():
    os.makedirs(RESULTS_DIR, exist_ok=True)
    return RESULTS_DIR


def main(argv=None):
    ap = argparse.ArgumentParser(description="Run one protocol trial (self-test)")
    ap.add_argument("--amp", type=float, default=DEFAULT_AMP,
                    help=f"pulse amplitude in STIM_GAIN units (default {DEFAULT_AMP})")
    ap.add_argument("--pulse-ms", type=float, default=100.0)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args(argv)

    m = run_trial(args.amp, pulse_ms=args.pulse_ms, seed=args.seed)
    print(f"amp={args.amp}  pulse_ms={args.pulse_ms}  seed={args.seed}")
    print(f"  motor_spikes     {m['motor_spikes']}")
    print(f"  first_spike_ms   {m['first_spike_ms']}")
    print(f"  peak_rate_hz     {m['peak_rate_hz']:.2f}")
    print(f"  triggered        {m['triggered']}")
    print(f"  bins_with_spikes {m['bins_with_spikes']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
