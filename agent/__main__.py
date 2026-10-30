"""Run the MA planner agent.

Examples:
    python3 -m agent --example 04_sync_fifo              # simulated user from the MA doc
    python3 -m agent --example 04_sync_fifo --interactive
    python3 -m agent --spec path/to/spec.md --interactive
    python3 -m agent --all                               # every example, simulated user
"""

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .judge import judge_plan
from .loop import RunLog, run_agent
from .planner_llm import ClaudePlanner
from .render import plan_to_markdown
from .user import InteractiveUser, SimulatedUser

ROOT = Path(__file__).resolve().parent.parent


def run_one(name, spec, user, args, stamp, ma_doc=None):
    log = RunLog(ROOT / "runs" / stamp / name)
    planner = ClaudePlanner(model=args.model)
    print(f"=== {name} ===")
    echo = lambda msg: print(f"[{name}] {msg}")
    plan, summary = run_agent(spec, planner, user, log, max_rounds=args.max_rounds, echo=echo)
    if plan:
        (log.dir / "plan.md").write_text(plan_to_markdown(plan, f"MA plan: {name}"))
    if plan and ma_doc and not args.no_judge:
        qa = json.loads((log.dir / "qa.json").read_text())
        detail, score, _ = judge_plan(spec, plan, qa, ma_doc)
        log.write_json("judge.json", {"score": score, **detail})
        summary["judge"] = score
        log.write_json("summary.json", summary)
    print(f"-> {summary['status']} in {summary['rounds']} round(s), "
          f"{summary['questions_asked']} question(s) asked; log in {log.dir.relative_to(ROOT)}\n")
    return summary


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--example", help="example folder name under examples/")
    src.add_argument("--spec", help="path to a spec file")
    src.add_argument("--all", action="store_true", help="run every example")
    ap.add_argument("--interactive", action="store_true", help="answer questions yourself")
    ap.add_argument("--model", default="claude-opus-5-5", help="planner model")
    ap.add_argument("--sim-model", default="claude-opus-5-5", help="simulated-user model")
    ap.add_argument("--no-judge", action="store_true", help="skip scoring against the MA doc")
    ap.add_argument("--jobs", type=int, default=1, help="examples to run in parallel")
    ap.add_argument("--max-rounds", type=int, default=5)
    args = ap.parse_args()
    stamp = time.strftime("%Y%m%d-%H%M%S")

    if args.spec:
        if not args.interactive:
            ap.error("--spec needs --interactive (no MA doc to simulate the user from)")
        run_one(Path(args.spec).stem, Path(args.spec).read_text(), InteractiveUser(), args, stamp)
        return

    names = ([p.name for p in sorted((ROOT / "examples").iterdir()) if p.is_dir()]
             if args.all else [args.example])

    def job(name):
        ex = ROOT / "examples" / name
        ma_doc = (ex / "microarch.md").read_text()
        user = InteractiveUser() if args.interactive else SimulatedUser(ma_doc, model=args.sim_model)
        try:
            return name, run_one(name, (ex / "spec.md").read_text(), user, args, stamp, ma_doc)
        except Exception as e:  # keep the batch going; the error is in the summary
            print(f"[{name}] FAILED: {type(e).__name__}: {e}")
            return name, {"status": "error", "error": f"{type(e).__name__}: {e}"}

    jobs = 1 if args.interactive else args.jobs
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        results = dict(pool.map(job, names))
    if len(results) > 1:
        (ROOT / "runs" / stamp / "all_summaries.json").write_text(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
