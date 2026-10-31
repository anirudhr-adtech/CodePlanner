#!/usr/bin/env python3
"""Compare two agent runs example by example.

    python3 scripts/compare_runs.py runs/<old> runs/<new> [--old-judge judge_v2.json]

Both runs are scored from their judge files; use --old-judge/--new-judge to pick
which file (for example a re-scored judge_v2.json) to read in each run.
"""

import argparse
import json
from pathlib import Path


def load(run, judge_name):
    rows = {}
    for d in sorted(Path(run).iterdir()):
        if not (d / "summary.json").is_file() or not (d / judge_name).is_file():
            continue
        s = json.loads((d / "summary.json").read_text())
        plan = json.loads((d / "plan.json").read_text())
        j = json.loads((d / judge_name).read_text())["score"]
        rows[d.name] = {
            "status": s["status"],
            "asked": s["questions_asked"],
            "steps": len(plan["steps"]),
            "decisions": sum(len(st["decisions"]) for st in plan["steps"]),
            "calls": s["llm_calls"],
            "retries": s["retries"],
            "out_tok": s["output_tokens"],
            "in_tok": s["input_tokens"],
            **{k: j[k] for k in ("key_decisions", "matches", "differs", "missing",
                                 "material_differs", "needless_questions")},
        }
    return rows


def total(rows, key):
    return sum(r[key] for r in rows.values())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("old")
    ap.add_argument("new")
    ap.add_argument("--old-judge", default="judge.json")
    ap.add_argument("--new-judge", default="judge.json")
    args = ap.parse_args()
    old, new = load(args.old, args.old_judge), load(args.new, args.new_judge)
    names = sorted(set(old) & set(new))
    old = {n: old[n] for n in names}
    new = {n: new[n] for n in names}

    print(f"{'example':26s} | {'asked':>9s} | {'decisions':>9s} | {'match/KD':>11s} | {'material':>9s} | {'missing':>9s} | {'out tokens':>13s}")
    for n in names:
        o, w = old[n], new[n]
        print(f"{n:26s} | {o['asked']:3d} -> {w['asked']:2d} | {o['decisions']:3d} -> {w['decisions']:2d} | "
              f"{o['matches']:2d}/{o['key_decisions']:2d}->{w['matches']:2d}/{w['key_decisions']:2d} | "
              f"{o['material_differs']:3d} -> {w['material_differs']:2d} | {o['missing']:3d} -> {w['missing']:2d} | "
              f"{o['out_tok']:6d}->{w['out_tok']:6d}")

    def agg(rows):
        kd = total(rows, "key_decisions")
        return {
            "examples": len(rows),
            "ready": sum(r["status"] == "ready" for r in rows.values()),
            "questions_asked": total(rows, "asked"),
            "needless_questions": total(rows, "needless_questions"),
            "decisions_median": sorted(r["decisions"] for r in rows.values())[len(rows) // 2],
            "steps_median": sorted(r["steps"] for r in rows.values())[len(rows) // 2],
            "key_decisions": kd,
            "agreement": round(total(rows, "matches") / kd, 3),
            "material_differs": total(rows, "material_differs"),
            "missing": total(rows, "missing"),
            "sound": round((kd - total(rows, "missing") - total(rows, "material_differs")) / kd, 3),
            "llm_calls": total(rows, "calls"),
            "retries": total(rows, "retries"),
            "output_tokens": total(rows, "out_tok"),
            "input_tokens": total(rows, "in_tok"),
        }

    a, b = agg(old), agg(new)
    print()
    print(f"{'metric':22s} {'old':>10s} {'new':>10s}")
    for k in a:
        print(f"{k:22s} {a[k]:>10} {b[k]:>10}")


if __name__ == "__main__":
    main()
