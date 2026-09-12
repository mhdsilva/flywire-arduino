#!/usr/bin/env python3
"""Builds the escape-reflex subcircuit (looming -> Giant Fiber) from FlyWire FAFB.

Nodes: {LC4} U {LPLC2} U {DNp01}
    U {DNp01 presynaptic neurons with total syn_count >= 5}
    U {LC4/LPLC2 postsynaptic neurons AND DNp01 presynaptic neurons}

Edges: for each pair (pre j -> post i), W = sum of syn_count over the connections.
Sign: GABA -> inhibitory (negative weight), everything else -> excitatory (positive).
  * This is a rough simplification: in the fly brain acetylcholine (ACH)
    is the main excitatory transmitter and GLUT is also mostly
    excitatory; only GABA is treated as inhibitory here. DA/SER/OCT are
    left as excitatory for lack of a better model in this v0.
  * If the same (pre,post) pair has connections with mixed transmitters, we sum
    excitatory and inhibitory separately: W = sum(syn | nt != GABA)
    - sum(syn | nt == GABA).

Output: brain/data/circuit.npz
  node_ids (int64)      : root_id of each neuron (index = position)
  roles    (<U8)        : "sensory" | "motor" | "inter"
  rows (int32)          : postsynaptic index (row)
  cols (int32)          : presynaptic index (column)
  data (float32)        : weight W
"""

from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")

# confirmed DNp01 root_ids (Giant Fiber). The cell types also point to these.
DNp01_IDS = [720575940622838154, 720575940632499757]
SENSORY_TYPES = ("LC4", "LPLC2")
MIN_SYN_TO_DN = 5
MAX_NEURONS = 3000


def load_data():
    ct = pd.read_csv(os.path.join(DATA, "consolidated_cell_types.csv.gz"))
    ct["primary_type"] = ct["primary_type"].astype(str).str.strip()
    conn = pd.read_csv(os.path.join(DATA, "connections.csv.gz"))
    return ct, conn


def main() -> int:
    print("loading data...")
    ct, conn = load_data()
    type_of = dict(zip(ct["root_id"], ct["primary_type"]))

    # DNp01 confirmed; check against the cell types.
    dn = set(DNp01_IDS)
    derived_dn = set(ct.loc[ct["primary_type"] == "DNp01", "root_id"])
    if derived_dn and derived_dn != dn:
        print(f"  warning: cell types DNp01={sorted(derived_dn)} != confirmed ids")
    if not dn <= set(ct["root_id"]):
        print("  warning: DNp01 not found in cell types")

    lc = set(ct.loc[ct["primary_type"].isin(SENSORY_TYPES), "root_id"])
    n_lc4 = int((ct["primary_type"] == "LC4").sum())
    n_lplc2 = int((ct["primary_type"] == "LPLC2").sum())
    print(f"  DNp01={len(dn)}  LC4={n_lc4}  LPLC2={n_lplc2}")

    # Direct inputs to DNp01.
    to_dn = conn[conn["post_root_id"].isin(dn)]
    pre_syn = to_dn.groupby("pre_root_id")["syn_count"].sum()
    strong_inputs = set(pre_syn[pre_syn >= MIN_SYN_TO_DN].index)
    print(f"  DNp01 presynaptic neurons with syn>= {MIN_SYN_TO_DN}: {len(strong_inputs)}")

    # Interneurons: LC4/LPLC2 postsynaptic AND DNp01 presynaptic.
    post_lc = set(conn.loc[conn["pre_root_id"].isin(lc), "post_root_id"])
    relay = post_lc & set(to_dn["pre_root_id"])
    print(f"  relay LC4/LPLC2 -> ... -> DNp01: {len(relay)}")

    nodes = lc | dn | strong_inputs | relay

    # Cap: keep the strongest by total weight (sum of incident syn_count).
    if len(nodes) > MAX_NEURONS:
        incident = conn[conn["pre_root_id"].isin(nodes) | conn["post_root_id"].isin(nodes)]
        w_in = incident.groupby("post_root_id")["syn_count"].sum()
        w_out = incident.groupby("pre_root_id")["syn_count"].sum()
        strength = (
            w_in.reindex(sorted(nodes), fill_value=0)
            + w_out.reindex(sorted(nodes), fill_value=0)
        )
        keep = set(strength.sort_values(ascending=False).head(MAX_NEURONS).index)
        keep |= dn  # never cut the motor
        print(f"  cap {MAX_NEURONS}: {len(nodes)} -> {len(keep)}")
        nodes = keep

    node_ids = np.array(sorted(nodes), dtype=np.int64)
    index = {int(r): i for i, r in enumerate(node_ids)}
    print(f"  final circuit: {len(node_ids)} neurons")

    # Edges internal to the circuit.
    sub = conn[
        conn["pre_root_id"].isin(nodes) & conn["post_root_id"].isin(nodes)
    ].copy()
    sub["is_gaba"] = sub["nt_type"] == "GABA"
    grp = sub.groupby(["pre_root_id", "post_root_id", "is_gaba"], sort=False)[
        "syn_count"
    ].sum().reset_index()
    grp["signed"] = np.where(grp["is_gaba"], -grp["syn_count"], grp["syn_count"])
    edges = grp.groupby(["pre_root_id", "post_root_id"], sort=False)["signed"].sum().reset_index()
    edges = edges[edges["signed"] != 0]

    rows = edges["post_root_id"].map(index).to_numpy(dtype=np.int32)
    cols = edges["pre_root_id"].map(index).to_numpy(dtype=np.int32)
    data = edges["signed"].to_numpy(dtype=np.float32)
    print(f"  edges (pre/post pairs): {len(data)}  "
          f"(positive={int((data > 0).sum())}, negative={int((data < 0).sum())})")

    # Roles.
    sensory_idx = {index[int(r)] for r in lc if int(r) in index}
    motor_idx = {index[int(r)] for r in dn if int(r) in index}
    roles = np.array(
        [
            "sensory" if i in sensory_idx
            else "motor" if i in motor_idx
            else "inter"
            for i in range(len(node_ids))
        ],
        dtype="<U8",
    )

    n_sensory = int((roles == "sensory").sum())
    n_motor = int((roles == "motor").sum())
    n_inter = int((roles == "inter").sum())
    n_direct = int(
        ((roles[cols] == "sensory") & (roles[rows] == "motor")).sum()
    )
    print(f"  roles: sensory={n_sensory}  inter={n_inter}  motor={n_motor}")
    print(f"  direct edges sensory->motor: {n_direct}")

    out = os.path.join(DATA, "circuit.npz")
    np.savez_compressed(
        out, node_ids=node_ids, roles=roles, rows=rows, cols=cols, data=data
    )
    print(f"saved to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
