"""List every difference between two snapshots of scripts/snapshot.py.

    uv run python scripts/compare_snapshots.py before.json after.json [--show 20]

Exits with status 1 when they differ.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter


def walk(x, y, path: list, out: list) -> None:
    if isinstance(x, dict) and isinstance(y, dict):
        for k in sorted(set(x) | set(y)):
            if k not in x or k not in y:
                out.append(([*path, k], x.get(k, "<missing>"), y.get(k, "<missing>")))
            else:
                walk(x[k], y[k], [*path, k], out)
    elif isinstance(x, list) and isinstance(y, list):
        if len(x) != len(y):
            out.append(([*path, f"length {len(x)} -> {len(y)}"], None, None))
        for i, (u, v) in enumerate(zip(x, y, strict=False)):
            key = u.get("id", i) if isinstance(u, dict) else i
            walk(u, v, [*path, key], out)
    elif x != y:
        out.append((path, x, y))


def main() -> None:
    ap = argparse.ArgumentParser(description="Compare two snapshots of scripts/snapshot.py.")
    ap.add_argument("before")
    ap.add_argument("after")
    ap.add_argument("--show", type=int, default=20, help="differences listed per drawing (default 20)")
    args = ap.parse_args()
    with open(args.before) as fa, open(args.after) as fb:
        a, b = json.load(fa), json.load(fb)
    diffs: dict[str, list] = {}
    for d in sorted(set(a) | set(b)):
        out = []
        walk(a.get(d, {"error": "<missing>"}), b.get(d, {"error": "<missing>"}), [], out)
        if out:
            diffs[d] = out
    if not diffs:
        print(f"no differences ({len(a)} drawings)")
        return
    kinds = Counter(str(p[0]) for ds in diffs.values() for p, _, _ in ds)
    print(f"{len(diffs)} of {len(a)} drawings differ; by section: {dict(kinds)}")
    for d, ds in diffs.items():
        print(f"== {d} ({len(ds)} differences)")
        for p, x, y in ds[: args.show]:
            print(f"   {' / '.join(map(str, p))[:120]}: {str(x)[:80]} -> {str(y)[:80]}")
    sys.exit(1)


if __name__ == "__main__":
    main()
