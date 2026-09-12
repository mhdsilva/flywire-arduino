#!/usr/bin/env python3
"""Reconnaissance of the escape circuit (looming -> Giant Fiber) in FlyWire FAFB v783.

Reads the Codex data in brain/data/ and reports:
  - DNp01 (Giant Fiber), LC4 and LPLC2 root_ids;
  - direct LC4/LPLC2 -> DNp01 connections;
  - the strongest inputs to DNp01 (with cell type).
"""

import os

import pandas as pd

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


def main() -> None:
    print("loading cell types...")
    ct = pd.read_csv(f"{DATA}/consolidated_cell_types.csv.gz")
    ct["primary_type"] = ct["primary_type"].astype(str).str.strip()
    print(f"  typed neurons: {len(ct)}")

    for t in ("DNp01", "LC4", "LPLC2"):
        print(f"  {t}: {(ct['primary_type'] == t).sum()}")

    tmap = dict(zip(ct["root_id"], ct["primary_type"]))
    dn = set(ct.loc[ct["primary_type"] == "DNp01", "root_id"])
    lc = set(ct.loc[ct["primary_type"].isin(["LC4", "LPLC2"]), "root_id"])
    print(f"  DNp01 ids: {sorted(dn)}")

    print("loading connections...")
    conn = pd.read_csv(f"{DATA}/connections.csv.gz")
    print(f"  connections: {len(conn)}")

    to_dn = conn[conn["post_root_id"].isin(dn)]
    from_lc = to_dn[to_dn["pre_root_id"].isin(lc)]
    print(
        f"  LC4/LPLC2 -> DNp01 connections: {len(from_lc)} "
        f"(syn sum={int(from_lc['syn_count'].sum()) if len(from_lc) else 0})"
    )

    print("top 20 inputs to DNp01:")
    if len(to_dn):
        top = (
            to_dn.groupby("pre_root_id")["syn_count"]
            .sum()
            .sort_values(ascending=False)
            .head(20)
        )
        for rid, w in top.items():
            print(f"   {rid}  syn={int(w):5d}  type={tmap.get(rid, '?')}")


if __name__ == "__main__":
    main()
