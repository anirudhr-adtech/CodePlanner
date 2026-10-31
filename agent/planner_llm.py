"""The planner LLM: one planning turn, no memory.

This is the only module that calls a model for planning. Replace `ClaudePlanner`
with a class exposing the same `plan_turn` method to swap in a trained model.
"""

import json
from pathlib import Path

from .llm import json_call, make_client
from .schema import PLAN_SCHEMA
from .spec_reader import numbered

SYSTEM_PROMPT = (Path(__file__).resolve().parent.parent / "prompts" / "planner_system.md").read_text()


def build_user_message(spec, qa_history, prev_plan, feedback):
    parts = ["# Specification\n\n" + numbered(spec)]
    if qa_history:
        lines = [f"- Q ({q['id']}, about {q['decision_id']}): {q['question']}\n  A: {q['answer']}" for q in qa_history]
        parts.append("# Questions already asked and answers\n\n" + "\n".join(lines))
    if prev_plan:
        parts.append("# Previous plan\n\n```json\n" + json.dumps({"steps": prev_plan["steps"]}, indent=1) + "\n```")
    if feedback:
        parts.append("# Your previous output failed these checks; fix them\n\n"
                     + "\n".join(f"- {f}" for f in feedback))
    parts.append("Produce the plan now.")
    return "\n\n".join(parts)


class ClaudePlanner:
    def __init__(self, model="claude-opus-5-5", effort="high"):
        self.client = make_client()
        self.model = model
        self.effort = effort

    def plan_turn(self, spec, qa_history=(), prev_plan=None, feedback=()):
        """Return (plan_dict, record) where record holds the raw exchange for logging."""
        user = build_user_message(spec, qa_history, prev_plan, feedback)
        plan, usage, stop = json_call(self.client, self.model, SYSTEM_PROMPT, user,
                                      PLAN_SCHEMA, effort=self.effort)
        record = {"model": self.model, "effort": self.effort, "user_message": user,
                  "plan": plan, "stop_reason": stop, "usage": usage}
        return plan, record
