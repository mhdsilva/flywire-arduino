#!/usr/bin/env python3
"""Experiment 2 -- null model: does the specific wiring matter?

Two nulls, both run through the identical shared protocol:

1. Degree-preserving directed rewiring (primary). Repeated directed
   double-edge swaps preserve the in-degree and out-degree sequences exactly.
   Each accepted swap moves two edges' synaptic weights with them, so the
   weight multiset is unchanged. Swaps that would create a self-loop or a
   duplicate edge are skipped. The degree sequences are verified against the
   real circuit (max absolute difference must be 0).
2. Erdos-Renyi (secondary). The same number of edges placed uniformly at
   random over the same node set, with the real weight multiset permuted onto
   the random edges. No degree constraint.

The real circuit is run once as well. For ``motor_spikes`` and
``first_spike_ms`` we report the mean, sd and the percentile of the real value
within each null distribution.

Output: ``experiments/results/null_model.csv`` (one tagged row per sample plus
the real circuit) and a printed summary.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys

import numpy as np
import scipy.sparse as sp

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from harness import DEFAULT_AMP, ensure_results_dir, load_circuit, run_trial

# Attempted swaps per edge. 10x is enough to mix the edges well while keeping
# the default 50-sample run in the tens of seconds on a laptop CPU.
SWAP_ATTEMPTS_PER_EDGE = 10


def rewire_degree_preserving(rows, cols, weights, seed, n_attempts):
    """Directed double-edge swaps preserving in/out degrees exactly.

    Weights travel with their edge (edge i keeps ``weights[i]``). Returns the
    rewired ``(rows, cols, weights)`` plus the number of accepted swaps.
    """
    rng = np.random.default_rng(seed)
    er, ec, ew = rows.copy(), cols.copy(), weights.copy()
    m = len(er)
    edge_set = set(zip(er.tolist(), ec.tolist()))
    accepted = 0
    for _ in range(n_attempts):
        i = int(rng.integers(0, m))
        j = int(rng.integers(0, m))
        if i == j:
            continue
        a, b = int(er[i]), int(ec[i])
        c, d = int(er[j]), int(ec[j])
        if a == c or b == d:          # same partner: swap would be a no-op
            continue
        if a == d or c == b:          # would create a self-loop
            continue
        if (a, d) in edge_set or (c, b) in edge_set:   # duplicate edge
            continue
        er[i], ec[i] = a, d
        er[j], ec[j] = c, b
        edge_set.discard((a, b))
        edge_set.discard((c, d))
        edge_set.add((a, d))
        edge_set.add((c, b))
        accepted += 1
    return er, ec, ew, accepted


def erdos_renyi(rows, cols, weights, seed):
    """Same edge count over the same nodes, no self-loops, weights permuted."""
    rng = np.random.default_rng(seed)
    n = int(max(rows.max(), cols.max()) + 1)
    m = len(rows)
    n_pairs = n * (n - 1)
    idx = rng.choice(n_pairs, size=m, replace=False)
    pre = idx // (n - 1)
    rem = idx % (n - 1)
    post = rem + (rem >= pre)          # skip the self-pair for each pre
    return pre.astype(np.int64), post.astype(np.int64), rng.permutation(weights)


def degree_vectors(rows, cols, n):
    return (np.bincount(rows, minlength=n).astype(np.int64),
            np.bincount(cols, minlength=n).astype(np.int64))


def percentile_of_real(null_values, real_value):
    """Fraction (%) of null samples <= the real value (mid-rank on ties)."""
    null_values = np.asarray(null_values, dtype=np.float64)
    if null_values.size == 0 or not np.isfinite(real_value):
        return float("nan")
    less = np.sum(null_values < real_value)
    equal = np.sum(null_values == real_value)
    return 100.0 * (less + 0.5 * equal) / null_values.size


def describe(kind, samples, real):
    """Print the null distribution summary for one null kind."""
    print(f"\n{kind} null: n={len(samples)}")
    for metric in ("motor_spikes", "first_spike_ms"):
        vals = [s[metric] for s in samples]
        if metric == "first_spike_ms":
            # Non-firing nulls never reach the readout; rank them as +inf so a
            # real latency is only "fast" relative to nulls that actually fired.
            arr = np.array([np.inf if v is None else v for v in vals], dtype=np.float64)
            fired = int(np.isfinite(arr).sum())
            finite = arr[np.isfinite(arr)]
            mean = float(finite.mean()) if finite.size else float("nan")
            sd = float(finite.std()) if finite.size else float("nan")
            extra = f"  (nulls that fired: {fired}/{len(vals)})"
        else:
            arr = np.array(vals, dtype=np.float64)
            mean = float(arr.mean())
            sd = float(arr.std())
            extra = ""
        real_v = real[metric]
        # Direction matters when reading a percentile: more spikes is a stronger
        # response, while a *smaller* first_spike_ms is the exceptional outcome.
        direction = "high = strong" if metric == "motor_spikes" else "low = fast"
        if metric == "first_spike_ms" and real_v is None:
            pct_s = "n/a (real did not fire)"
        else:
            rv = np.inf if real_v is None else real_v
            pct = percentile_of_real(arr, rv)
            pct_s = f"{pct:.1f}th percentile ({direction})"
        print(f"  {metric:<15} null mean={mean:8.3f}  sd={sd:8.3f}  "
              f"real={real_v}  -> {pct_s}{extra}")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Null-model experiment")
    ap.add_argument("--n", type=int, default=50, help="null samples per null kind")
    ap.add_argument("--amp", type=float, default=DEFAULT_AMP)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--swap-factor", type=int, default=SWAP_ATTEMPTS_PER_EDGE,
                    help="swap attempts per edge for the degree-preserving null")
    args = ap.parse_args(argv)

    W, _roles, _node_types, _ids = load_circuit()
    n = W.shape[0]
    coo = W.tocoo()
    rows, cols, weights = coo.row.astype(np.int64), coo.col.astype(np.int64), coo.data.astype(np.float64)
    m = len(rows)
    real_out, real_in = degree_vectors(rows, cols, n)

    real = run_trial(args.amp, seed=args.seed)
    samples = {"degree": [], "er": []}
    max_out_diff = 0
    max_in_diff = 0

    for i in range(args.n):
        ss = np.random.SeedSequence([args.seed, 0, i])
        er, ec, ew, _accepted = rewire_degree_preserving(
            rows, cols, weights, ss, args.swap_factor * m)
        no, ni = degree_vectors(er, ec, n)
        max_out_diff = max(max_out_diff, int(np.max(np.abs(no - real_out))))
        max_in_diff = max(max_in_diff, int(np.max(np.abs(ni - real_in))))
        null_W = sp.csr_matrix((ew, (er, ec)), shape=(n, n))
        result = run_trial(args.amp, weights=null_W, seed=args.seed + i)
        result["sample"] = i
        samples["degree"].append(result)

    for i in range(args.n):
        ss = np.random.SeedSequence([args.seed, 1, i])
        er, ec, ew = erdos_renyi(rows, cols, weights, ss)
        null_W = sp.csr_matrix((ew, (er, ec)), shape=(n, n))
        result = run_trial(args.amp, weights=null_W, seed=args.seed + i)
        result["sample"] = i
        samples["er"].append(result)

    print(f"circuit: n={n}  edges={m}  amp={args.amp}  seed={args.seed}")
    print(f"degree preservation: max |out-deg diff|={max_out_diff}  "
          f"max |in-deg diff|={max_in_diff}")
    print("real circuit:", {k: real[k] for k in
                            ("motor_spikes", "first_spike_ms", "peak_rate_hz",
                             "triggered", "bins_with_spikes")})

    describe("degree-preserving", samples["degree"], real)
    describe("Erdos-Renyi", samples["er"], real)

    out_dir = ensure_results_dir()
    path = os.path.join(out_dir, "null_model.csv")
    fields = ["kind", "sample", "motor_spikes", "first_spike_ms", "peak_rate_hz",
              "triggered", "bins_with_spikes", "seed"]
    with open(path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerow({"kind": "real", "sample": -1, "seed": args.seed, **real})
        for kind in ("degree", "er"):
            for r in samples[kind]:
                writer.writerow({"kind": kind, "seed": args.seed, **r})
    print(f"\nsaved {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
