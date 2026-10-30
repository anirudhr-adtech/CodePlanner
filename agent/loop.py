"""The agent loop: draft -> check -> (retry) -> ask blocking questions -> repeat."""

import json
import time
from pathlib import Path

from .checker import check_plan
from .spec_reader import normalize


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
    qa_history = []          # [{id, question, answer, in_doc, decision_id}]
    asked = set()            # normalized question texts already asked
    answered_decisions = set()
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
                 f"{metrics.get('blocking_questions', 0)} blocking q, {len(errors)} check errors")
            if not errors:
                break
            feedback = errors
            totals["retries"] += 1
        plan = draft
        if errors:
            status = "invalid"
            log.event("stop", reason="checks still failing after retries", errors=errors)
            break

        # Question gate: blocking, not already asked, decision not already settled.
        to_ask = [q for q in plan.get("questions", [])
                  if q.get("blocking")
                  and normalize(q["question"]) not in asked
                  and q.get("decision_id") not in answered_decisions]
        dropped = [q["id"] for q in plan.get("questions", []) if q.get("blocking") and q not in to_ask]
        log.event("gate", round=rnd, ask=[q["id"] for q in to_ask], dropped_repeats=dropped)
        if not to_ask:
            status = "ready"
            break
        for q in to_ask:
            ans = user.ask(q)
            asked.add(normalize(q["question"]))
            answered_decisions.add(q.get("decision_id"))
            qa_history.append({"id": q["id"], "question": q["question"],
                               "decision_id": q.get("decision_id"), **ans})
            log.event("answer", round=rnd, question=q, **ans)
            echo(f"  asked {q['id']}: {q['question'][:90]}")
            echo(f"    -> {ans['answer'][:90]}")

    # Non-blocking questions were never asked; keep them apart so the MA writer
    # sees which defaults a user could still override.
    if plan:
        plan["deferred_questions"] = [q for q in plan.get("questions", []) if not q.get("blocking")]
        plan["questions"] = [q for q in plan.get("questions", []) if q.get("blocking")]

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
