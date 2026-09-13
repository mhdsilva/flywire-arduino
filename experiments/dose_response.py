#!/usr/bin/env python3
"""Experiment 3 -- dose-response: how sensitive is the reflex?

Sweeps the pulse amplitude ``amp`` over ``0 .. 1`` in ``--points`` steps and
repeats each point ``--trials`` times with a new seed per trial. Reports, per
amplitude, the trigger probability, the mean +/- sd ``motor_spikes`` and the
mean ``first_spike_ms``.

With the default ``--noise-sigma 0.0`` the LIF model is deterministic (no noise
term), so every seed at a given amplitude yields the same metrics, the sd is
zero and the trigger probability is 0 or 1 -- a perfectly sharp threshold. This
is reported honestly rather than masked.

With ``--noise-sigma > 0`` an explicitly injected Gaussian drive is added to the
sensory neurons (see ``harness.run_trial``), which turns the step into a graded
psychometric curve. The noise is an injected stimulus, not a claim that the
brain is noisy, and the threshold location depends on its size.

Output: ``experiments/results/dose_response.csv`` for noise = 0 (unchanged
format) and ``experiments/results/dose_response_noise.csv`` (with added
``sd_motor_spikes`` and ``noise_sigma`` columns) when noise > 0.
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
    ap.add_argument("--noise-sigma", type=float, default=0.0,
                    help="sd of injected Gaussian sensory drive; 0 = deterministic "
                         "(default). noise > 0 gives a graded psychometric curve.")
    args = ap.parse_args(argv)

    amps = np.linspace(0.0, args.amp_max, args.points)
    rows = []
    for amp in amps:
        results = [run_trial(float(amp), pulse_ms=args.pulse_ms, seed=args.seed + t,
                             noise_sigma=args.noise_sigma)
                   for t in range(args.trials)]
        triggered = [r for r in results if r["triggered"]]
        latencies = [r["first_spike_ms"] for r in triggered]
        spikes = [r["motor_spikes"] for r in results]
        rows.append({
            "amp": float(amp),
            "n_trials": args.trials,
            "n_triggered": len(triggered),
            "trigger_probability": len(triggered) / args.trials,
            "mean_motor_spikes": float(np.mean(spikes)),
            "sd_motor_spikes": float(np.std(spikes)),
            "mean_first_spike_ms": float(np.mean(latencies)) if latencies else None,
            "noise_sigma": float(args.noise_sigma),
        })

    print(f"pulse_ms={args.pulse_ms}  trials/point={args.trials}  "
          f"points={args.points}  seed={args.seed}  "
          f"noise_sigma={args.noise_sigma}")
    header = (f"{'amp':>6} {'trigger_p':>10} {'mean_spikes':>12} "
              f"{'sd_spikes':>10} {'mean_first_ms':>14} {'n_triggered':>12}")
    print(header)
    print("-" * len(header))
    for r in rows:
        first = "-" if r["mean_first_spike_ms"] is None else f"{r['mean_first_spike_ms']:.2f}"
        print(f"{r['amp']:>6.3f} {r['trigger_probability']:>10.2f} "
              f"{r['mean_motor_spikes']:>12.2f} {r['sd_motor_spikes']:>10.2f} "
              f"{first:>14} {r['n_triggered']:>12}")

    out_dir = ensure_results_dir()
    if args.noise_sigma > 0.0:
        path = os.path.join(out_dir, "dose_response_noise.csv")
        fields = ["amp", "n_trials", "n_triggered", "trigger_probability",
                  "mean_motor_spikes", "sd_motor_spikes", "mean_first_spike_ms",
                  "noise_sigma"]
    else:
        path = os.path.join(out_dir, "dose_response.csv")
        fields = ["amp", "n_trials", "n_triggered", "trigger_probability",
                  "mean_motor_spikes", "mean_first_spike_ms"]
    with open(path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for r in rows:
            writer.writerow(r)
    print(f"\nsaved {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
