#!/usr/bin/env python3
"""Aggregate P0 scores over one or more run directories.

    python3 scripts/score_runs.py runs/<stamp>/r1 runs/<stamp>/r2 ... [--split dev] [--judge judge.json]

Reports, per run and pooled: P0 sound (delegation counts), strict sound, agreement,
questions asked and the needless share, plus the per-example mean so weak specs stand out.
"""

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def score_run(run, names, judge):
    t = dict(kd=0, matches=0, material=0, missing=0, delegated=0, asked=0, needless=0, n=0)
    per = {}
    for name in names:
        d = Path(run) / name
        if not (d / judge).is_file():
            continue
        s = json.loads((d / judge).read_text())["score"]
        asked = len(json.loads((d / "qa.json").read_text()))
        t["n"] += 1
        t["kd"] += s["key_decisions"]
        t["matches"] += s["matches"]
        t["material"] += s["material_differs"]
        t["missing"] += s["missing"]
        t["delegated"] += s.get("delegated", 0)
        t["asked"] += asked
        t["needless"] += s["needless_questions"]
        per[name] = s["sound"]
    return t, per


def ratios(t):
    kd = t["kd"] or 1
    bad = t["missing"] + t["material"]
    return {
        "examples": t["n"],
        "sound": round((t["kd"] - bad) / kd, 3),
        "sound_strict": round((t["kd"] - bad - t["delegated"]) / kd, 3),
        "agreement": round(t["matches"] / kd, 3),
        "material": t["material"],
        "missing": t["missing"],
        "delegated": t["delegated"],
        "asked": t["asked"],
        "needless_share": round(t["needless"] / t["asked"], 3) if t["asked"] else 0.0,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="+")
    ap.add_argument("--split", choices=["dev", "test"])
    ap.add_argument("--judge", default="judge.json")
    args = ap.parse_args()
    if args.split:
        names = json.loads((ROOT / "agent" / "splits.json").read_text())[args.split]
    else:
        names = sorted({p.name for r in args.runs for p in Path(r).iterdir() if p.is_dir()})

    pooled = dict(kd=0, matches=0, material=0, missing=0, delegated=0, asked=0, needless=0, n=0)
    per_example = {}
    for run in args.runs:
        t, per = score_run(run, names, args.judge)
        print(f"{run}: {ratios(t)}")
        for k in pooled:
            pooled[k] += t[k]
        for n, v in per.items():
            per_example.setdefault(n, []).append(v)
    print(f"\nPOOLED: {ratios(pooled)}\n")
    for n in sorted(per_example, key=lambda n: sum(per_example[n]) / len(per_example[n])):
        v = per_example[n]
        print(f"  {n:26s} mean sound {sum(v) / len(v):.2f}  runs {v}")


if __name__ == "__main__":
    main()
