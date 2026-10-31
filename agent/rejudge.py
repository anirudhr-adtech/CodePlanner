"""Re-score an existing run directory with the current judge.

    python3 -m agent.rejudge runs/<stamp> [--jobs 5]
"""

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .judge import judge_plan

ROOT = Path(__file__).resolve().parent.parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    ap.add_argument("--jobs", type=int, default=5)
    args = ap.parse_args()
    run = Path(args.run_dir)

    def job(d):
        ex = ROOT / "examples" / d.name
        plan = json.loads((d / "plan.json").read_text())
        qa = json.loads((d / "qa.json").read_text())
        detail, score, _ = judge_plan((ex / "spec.md").read_text(), plan, qa,
                                      (ex / "microarch.md").read_text())
        (d / "judge_v2.json").write_text(json.dumps({"score": score, **detail}, indent=2) + "\n")
        print(f"{d.name}: {score}")
        return d.name, score

    dirs = sorted(p for p in run.iterdir() if (p / "plan.json").is_file())
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        scores = dict(pool.map(job, dirs))
    (run / "rejudge_v2.json").write_text(json.dumps(scores, indent=2) + "\n")


if __name__ == "__main__":
    main()
