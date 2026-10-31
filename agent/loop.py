"""The agent loop: draft -> check -> (retry) -> ask-or-assume -> repeat."""

import json
import time
from pathlib import Path

from .checker import check_plan

RANK = {"high": 2, "medium": 1, "low": 0}
MAX_QUESTIONS_PER_ROUND = 4


def should_ask(d):
    """Ask-or-assume rule, owned by the agent: ask about a defaulted decision when
    getting it wrong is costly and the planner is not sure of its default."""
    if d.get("status") != "defaulted":
        return False
    impact, conf = d.get("impact"), d.get("confidence")
    return (impact == "high" and conf in ("low", "medium")) or (impact == "medium" and conf == "low")


def priority(d):
    return (RANK.get(d.get("impact"), 0), -RANK.get(d.get("confidence"), 0))


class RunLog:
    def __init__(self, run_dir):
        self.dir = Path(run_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path = self.dir / "log.jsonl"

    def event(self, kind, **data):
        with self.path.open("a") as f:
            f.write(json.dumps({"t": round(time.time(), 2), "event": kind, **data}) + "\n")

    def write_json(self, name, obj):
        (self.dir / name).write_text(json.dumps(obj, indent=2) + "\n")


def run_agent(spec, planner, user, log, max_rounds=5, max_retries=2, echo=print):
    qa_history = []          # [{id, decision_id, question, answer, in_doc}]
    answered = set()         # decision ids already put to the user
    plan, metrics, status = None, {}, "cap_reached"
    totals = {"llm_calls": 0, "retries": 0, "input_tokens": 0, "output_tokens": 0}

    for rnd in range(1, max_rounds + 1):
        feedback = []
        for attempt in range(max_retries + 1):
            draft, record = planner.plan_turn(spec, qa_history, plan, feedback)
            totals["llm_calls"] += 1
            totals["input_tokens"] += record["usage"]["input"]
            totals["output_tokens"] += record["usage"]["output"]
            errors, metrics = check_plan(draft, spec)
            log.event("llm_turn", round=rnd, attempt=attempt, record=record,
                      errors=errors, metrics=metrics)
            echo(f"round {rnd} attempt {attempt}: {metrics.get('steps', 0)} steps, "
                 f"{metrics.get('decisions', 0)} decisions ({metrics.get('defaulted', 0)} defaulted), "
                 f"{len(errors)} check errors")
            if not errors:
                break
            feedback = errors
            totals["retries"] += 1
        plan = draft
        if errors:
            status = "invalid"
            log.event("stop", reason="checks still failing after retries", errors=errors)
            break

        decisions = [d for s in plan["steps"] for d in s["decisions"]]
        candidates = [d for d in decisions if should_ask(d) and d["id"] not in answered]
        to_ask = sorted(candidates, key=priority, reverse=True)[:MAX_QUESTIONS_PER_ROUND]
        log.event("gate", round=rnd, ask=[d["id"] for d in to_ask],
                  assumed=[d["id"] for d in decisions
                           if d["status"] == "defaulted" and not should_ask(d)],
                  repeats_skipped=[d["id"] for d in decisions if should_ask(d) and d["id"] in answered])
        if not to_ask:
            status = "ready"
            break
        for d in to_ask:
            q = {"id": d["id"], "question": d["question"], "why_it_matters": d["rationale"],
                 "default": d["choice"]}
            ans = user.ask(q)
            answered.add(d["id"])
            qa_history.append({"id": f"Q{len(qa_history) + 1}", "decision_id": d["id"],
                               "question": d["question"], **ans})
            log.event("answer", round=rnd, decision=d, **ans)
            echo(f"  asked {d['id']} ({d['impact']} impact, {d['confidence']} conf): {d['question'][:80]}")
            echo(f"    -> {ans['answer'][:90]}")

    # Defaulted decisions that were never asked are the plan's assumptions.
    if plan:
        plan["assumptions"] = [
            {"decision_id": d["id"], "topic": d["topic"], "assumed": d["choice"],
             "impact": d["impact"], "confidence": d["confidence"], "question": d["question"]}
            for s in plan["steps"] for d in s["decisions"] if d["status"] == "defaulted"]

    summary = {
        "status": status,
        "rounds": rnd,
        "questions_asked": len(qa_history),
        "questions_not_in_doc": sum(1 for q in qa_history if q.get("in_doc") is False),
        "final_metrics": metrics,
        **totals,
    }
    log.write_json("plan.json", plan)
    log.write_json("qa.json", qa_history)
    log.write_json("summary.json", summary)
    log.event("summary", **summary)
    return plan, summary
