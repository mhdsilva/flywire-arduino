#!/usr/bin/env python3
"""Experiment 1 -- ablation: which neurons are necessary for the response?

Removes one group at a time and runs the shared protocol for each condition:

    baseline  nothing removed
    LC4       every neuron whose FlyWire primary_type is LC4
    LPLC2     every neuron whose FlyWire primary_type is LPLC2
    sensory   all sensory neurons (LC4 + LPLC2)
    inter     all interneurons
    motor     both DNp01 Giant Fibre neurons (expected: no output)

The result is reported **across stimulus amplitudes on purpose**. The circuit sits
close to threshold, so at a near-threshold stimulus losing any drive can abolish
the response and look "necessary", while at a suprathreshold stimulus the same
group clearly only contributes a share. A single amplitude would hide that.

Ablation follows the remove-not-silence semantics documented in
``harness.run_trial``: incoming and outgoing edges are zeroed, the group is
excluded from the stimulus and from the readout.

With ``--types`` the runner instead ablates **every** FlyWire ``primary_type``
with at least ``--min-cells`` neurons (default 10), plus the baseline, so the
whole cell-type inventory is covered rather than the two named conditions.

Output: ``experiments/results/ablation.csv`` (or ``ablation_types.csv`` in
``--types`` mode; one row per amplitude x condition) and a printed matrix.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from harness import ensure_results_dir, load_circuit, run_trial

CONDITIONS = ["baseline", "LC4", "LPLC2", "sensory", "inter", "motor"]

# A near-threshold point (0.2 is the baseline amplitude elsewhere) plus clearly
# suprathreshold points, so "contributes" and "is necessary" are distinguishable.
DEFAULT_AMPS = [0.2, 0.35, 0.5, 0.75, 1.0]


def condition_nodes(condition):
    """Indices removed by a named condition. Empty type strings match nothing."""
    _W, roles, node_types, _ids = load_circuit()
    if condition == "baseline":
        return np.array([], dtype=np.int64)
    if condition in ("LC4", "LPLC2"):
        return np.flatnonzero(node_types == condition)
    if condition == "sensory":
        return np.flatnonzero(roles == "sensory")
    if condition == "inter":
        return np.flatnonzero(roles == "inter")
    if condition == "motor":
        return np.flatnonzero(roles == "motor")
    raise ValueError(f"unknown condition: {condition}")


def type_conditions(min_cells):
    """``baseline`` plus every non-empty FlyWire type with >= ``min_cells``.

    Types are the ``primary_type`` in ``node_types``; empty strings (3 nodes)
    match nothing and are skipped. At the default ``min_cells=10`` only LC4 and
    LPLC2 qualify, but every other type is an interneuron of 1-8 cells, so
    lowering ``--min-cells`` is how the long tail is examined.
    """
    _W, _roles, node_types, _ids = load_circuit()
    conds = {"baseline": np.array([], dtype=np.int64)}
    for t in sorted(set(node_types.tolist())):
        if t == "":
            continue
        idx = np.flatnonzero(node_types == t)
        if idx.size >= min_cells:
            conds[t] = idx
    return conds


def main(argv=None):
    ap = argparse.ArgumentParser(description="Ablation experiment")
    ap.add_argument("--amps", type=float, nargs="+", default=DEFAULT_AMPS,
                    help=f"amplitudes to sweep (default: {DEFAULT_AMPS})")
    ap.add_argument("--amp", type=float, default=None,
                    help="run a single amplitude instead of the sweep")
    ap.add_argument("--pulse-ms", type=float, default=100.0)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--types", action="store_true",
                    help="ablate every FlyWire cell type with at least "
                         "--min-cells neurons, plus baseline")
    ap.add_argument("--min-cells", type=int, default=10,
                    help="minimum neuron count for a type in --types mode "
                         "(default 10)")
    args = ap.parse_args(argv)
    amps = [args.amp] if args.amp is not None else list(args.amps)

    if args.types:
        nodes_by_cond = type_conditions(args.min_cells)
        conditions = list(nodes_by_cond)
        out_name = "ablation_types.csv"
    else:
        nodes_by_cond = {c: condition_nodes(c) for c in CONDITIONS}
        conditions = list(CONDITIONS)
        out_name = "ablation.csv"

    results = {}
    for amp in amps:
        for c in conditions:
            results[(c, amp)] = run_trial(
                amp, pulse_ms=args.pulse_ms,
                ablate=set(nodes_by_cond[c].tolist()), seed=args.seed)

    print(f"pulse_ms={args.pulse_ms}  seed={args.seed}  "
          f"(shared protocol: 200 ms warm-up, pulse, 500 ms readout)")
    if args.types:
        print(f"--types: {len(conditions) - 1} cell types with >= {args.min_cells} "
              f"neurons, plus baseline")
    print("cells are 'motor_spikes (% of baseline)'. The sweep matters: at a "
          "near-threshold amplitude a lost group can look necessary.")
    name_w = max(9, max(len(c) for c in conditions))
    head = f"{'condition':<{name_w}}{'removed':>8}  " + "".join(f"{a:>14.2f}" for a in amps)
    print(head)
    print("-" * len(head))
    for c in conditions:
        line = f"{c:<{name_w}}{len(nodes_by_cond[c]):>8}  "
        for a in amps:
            s = results[(c, a)]["motor_spikes"]
            b = results[("baseline", a)]["motor_spikes"]
            pct = 100.0 if c == "baseline" else (100.0 * s / b if b else float("nan"))
            pct_s = "-" if pct != pct else f"{pct:3.0f}%"
            line += f"{f'{s} ({pct_s})':>14}"
        print(line)

    out_dir = ensure_results_dir()
    path = os.path.join(out_dir, out_name)
    fields = ["amp", "condition", "neurons_removed", "motor_spikes",
              "first_spike_ms", "peak_rate_hz", "triggered", "bins_with_spikes",
              "pct_of_baseline"]
    with open(path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for a in amps:
            b = results[("baseline", a)]["motor_spikes"]
            for c in conditions:
                m = results[(c, a)]
                pct = 100.0 if c == "baseline" else (
                    100.0 * m["motor_spikes"] / b if b else float("nan"))
                writer.writerow({"amp": a, "condition": c,
                                 "neurons_removed": int(len(nodes_by_cond[c])),
                                 "pct_of_baseline": pct, **m})
    print(f"\nsaved {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
