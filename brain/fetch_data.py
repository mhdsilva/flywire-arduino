#!/usr/bin/env python3
"""Downloads the FlyWire connectome data (FAFB v783) used by the brain.

The files are large (~50 MB for the connections file), so they are NOT versioned.
Run this once and then `python build_circuit.py`.

Usage:
    python fetch_data.py
"""

from __future__ import annotations

import os
import sys
import urllib.request

BASE = "https://storage.googleapis.com/flywire-data/codex/data/fafb/783"
FILES = [
    "consolidated_cell_types.csv.gz",  # root_id -> cell type
    "classification.csv.gz",           # class/superclass/hemilineage
    "connections.csv.gz",              # the synapses (pre, post, neuropil, syn, nt)
]
DEST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


def main() -> int:
    os.makedirs(DEST, exist_ok=True)
    for name in FILES:
        path = os.path.join(DEST, name)
        if os.path.exists(path):
            print(f"already exists: {name}")
            continue
        url = f"{BASE}/{name}"
        print(f"downloading {name} ...")
        try:
            urllib.request.urlretrieve(url, path)
        except Exception as exc:  # noqa: BLE001
            print(f"  failed: {exc}")
            return 1
        print(f"  ok ({os.path.getsize(path) / 1e6:.1f} MB)")
    print("\nnow run:  python build_circuit.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
