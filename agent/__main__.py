"""Run the MA planner agent.

Examples:
    python3 -m agent --example 04_sync_fifo              # simulated user from the MA doc
    python3 -m agent --example 04_sync_fifo --interactive
    python3 -m agent --spec path/to/spec.md --interactive
    python3 -m agent --all                               # every example, simulated user
"""

import argparse
import json
import shutil
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
    src.add_argument("--split", choices=["dev", "test"], help="run the examples in agent/splits.json")
    ap.add_argument("--interactive", action="store_true", help="answer questions yourself")
    ap.add_argument("--model", default="claude-opus-5-5", help="planner model")
    ap.add_argument("--sim-model", default="claude-opus-5-5", help="simulated-user model")
    ap.add_argument("--no-judge", action="store_true", help="skip scoring against the MA doc")
    ap.add_argument("--jobs", type=int, default=1, help="examples to run in parallel")
    ap.add_argument("--max-rounds", type=int, default=5)
    ap.add_argument("--repeat", type=int, default=1, help="independent runs per example")
    ap.add_argument("--tag", default="", help="label appended to the run directory name")
    ap.add_argument("--resume", help="existing run directory name under runs/; redo only examples without a judge.json")
    args = ap.parse_args()
    stamp = args.resume or time.strftime("%Y%m%d-%H%M%S") + (f"-{args.tag}" if args.tag else "")

    if args.spec:
        if not args.interactive:
            ap.error("--spec needs --interactive (no MA doc to simulate the user from)")
        run_one(Path(args.spec).stem, Path(args.spec).read_text(), InteractiveUser(), args, stamp)
        return

    if args.split:
        names = json.loads((ROOT / "agent" / "splits.json").read_text())[args.split]
    elif args.all:
        names = [p.name for p in sorted((ROOT / "examples").iterdir()) if p.is_dir()]
    else:
        names = [args.example]
    runs = [f"{stamp}/r{r}" if args.repeat > 1 else stamp for r in range(1, args.repeat + 1)]

    def done(run, name):
        return (ROOT / "runs" / run / name / "judge.json").is_file()

    def job(item):
        run, name = item
        shutil.rmtree(ROOT / "runs" / run / name, ignore_errors=True)  # drop a failed partial run
        ex = ROOT / "examples" / name
        ma_doc = (ex / "microarch.md").read_text()
        user = InteractiveUser() if args.interactive else SimulatedUser(ma_doc, model=args.sim_model)
        try:
            return (run, name), run_one(name, (ex / "spec.md").read_text(), user, args, run, ma_doc)
        except Exception as e:  # keep the batch going; the error is in the summary
            print(f"[{name}] FAILED: {type(e).__name__}: {e}")
            return (run, name), {"status": "error", "error": f"{type(e).__name__}: {e}"}

    jobs = 1 if args.interactive else args.jobs
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        todo = [(run, n) for run in runs for n in names if not (args.resume and done(run, n))]
        results = dict(pool.map(job, todo))
    for run in runs:
        own = {n: v for (r, n), v in results.items() if r == run}
        if len(own) > 1:
            (ROOT / "runs" / run / "all_summaries.json").write_text(json.dumps(own, indent=2))


if __name__ == "__main__":
    main()
