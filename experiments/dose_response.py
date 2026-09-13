#!/usr/bin/env python3
"""Experiment 3 -- dose-response: how sensitive is the reflex?

Sweeps the pulse amplitude ``amp`` over ``0 .. 1`` in ``--points`` steps and
repeats each point ``--trials`` times with a new seed per trial. Reports, per
amplitude, the trigger probability, the mean ``motor_spikes`` and the mean
``first_spike_ms``.

Because the LIF model is deterministic (no noise term), every seed at a given
amplitude yields the same metrics. Trial variance is therefore exactly zero
and the trigger probability is 0 or 1 -- a perfectly sharp threshold. This is
reported honestly rather than masked with injected noise.

Output: ``experiments/results/dose_response.csv`` and a printed table.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from harness import ensure_results_dir, run_trial


def main(argv=None):
    ap = argparse.ArgumentParser(description="Dose-response experiment")
    ap.add_argument("--trials", type=int, default=5, help="trials per amplitude")
    ap.add_argument("--points", type=int, default=9, help="amplitude points")
    ap.add_argument("--amp-max", type=float, default=1.0)
    ap.add_argument("--pulse-ms", type=float, default=100.0)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args(argv)

    amps = np.linspace(0.0, args.amp_max, args.points)
    rows = []
    for amp in amps:
        results = [run_trial(float(amp), pulse_ms=args.pulse_ms, seed=args.seed + t)
                   for t in range(args.trials)]
        triggered = [r for r in results if r["triggered"]]
        latencies = [r["first_spike_ms"] for r in triggered]
        rows.append({
            "amp": float(amp),
            "n_trials": args.trials,
            "n_triggered": len(triggered),
            "trigger_probability": len(triggered) / args.trials,
            "mean_motor_spikes": float(np.mean([r["motor_spikes"] for r in results])),
            "mean_first_spike_ms": float(np.mean(latencies)) if latencies else None,
        })

    print(f"pulse_ms={args.pulse_ms}  trials/point={args.trials}  "
          f"points={args.points}  seed={args.seed}")
    header = (f"{'amp':>6} {'trigger_p':>10} {'mean_spikes':>12} "
              f"{'mean_first_ms':>14} {'n_triggered':>12}")
    print(header)
    print("-" * len(header))
    for r in rows:
        first = "-" if r["mean_first_spike_ms"] is None else f"{r['mean_first_spike_ms']:.2f}"
        print(f"{r['amp']:>6.3f} {r['trigger_probability']:>10.2f} "
              f"{r['mean_motor_spikes']:>12.2f} {first:>14} {r['n_triggered']:>12}")

    out_dir = ensure_results_dir()
    path = os.path.join(out_dir, "dose_response.csv")
    fields = ["amp", "n_trials", "n_triggered", "trigger_probability",
              "mean_motor_spikes", "mean_first_spike_ms"]
    with open(path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)
    print(f"\nsaved {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
