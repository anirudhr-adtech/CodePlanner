"""Score a finished plan against the example's MA document (the answer key).

Used only for evaluation; the agent never sees the MA document.
"""

import json

from .llm import json_call, make_client

JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "key_decisions": {
            "type": "array",
            "description": "The important architecture decisions the MA document makes.",
            "items": {
                "type": "object",
                "properties": {
                    "decision": {"type": "string"},
                    "ma_choice": {"type": "string"},
                    "spec_settles_it": {"type": "boolean", "description": "True if the spec text alone determines this choice."},
                    "in_plan": {"type": "string", "enum": ["matches", "differs", "missing"]},
                    "plan_choice": {"type": "string", "description": "What the plan decided or defaulted, or empty if missing."},
                    "difference": {"type": "string", "enum": ["none", "equivalent", "material"],
                                   "description": "For 'differs': equivalent if both choices are sound and the rest of the architecture barely changes; material if it changes structure, interfaces or visible behaviour. 'none' otherwise."},
                    "note": {"type": "string"},
                },
            },
        },
        "needless_questions": {
            "type": "array",
            "description": "Ids (Q1, Q2, ...) of asked questions the spec already answered or that do not change the architecture.",
            "items": {"type": "string"},
        },
        "summary": {"type": "string"},
    },
}

JUDGE_SYSTEM = (
    "You are a principal hardware architect grading a planning model. You get a spec, "
    "the plan the model produced from it (with the questions it asked and the answers), "
    "and the reference micro-architecture (MA) document written for the same spec. "
    "List the 8-15 most important architecture decisions in the MA document. For each, "
    "say whether the plan reaches the same choice (matches), a different one (differs) or "
    "does not address it at all (missing). Defaults and assumptions in the plan count as "
    "choices. A different but defensible choice where the spec is silent is still 'differs'; "
    "rate each difference as equivalent or material. Only list decisions at architecture "
    "level, not naming or encoding details. Then list asked questions that were needless. "
    "Be strict and concrete."
)


def judge_plan(spec, plan, qa, ma_doc, model="claude-opus-5-5"):
    user = (f"# Spec\n\n{spec}\n\n# Plan\n\n```json\n{json.dumps(plan, indent=1)}\n```\n\n"
            f"# Questions asked and answers\n\n```json\n{json.dumps(qa, indent=1)}\n```\n\n"
            f"# Reference MA document\n\n{ma_doc}")
    out, usage, _ = json_call(make_client(), model, JUDGE_SYSTEM, user, JUDGE_SCHEMA,
                              effort="high", max_tokens=32000)
    ks = out["key_decisions"]
    silent = [k for k in ks if not k["spec_settles_it"]]
    score = {
        "key_decisions": len(ks),
        "matches": sum(k["in_plan"] == "matches" for k in ks),
        "differs": sum(k["in_plan"] == "differs" for k in ks),
        "missing": sum(k["in_plan"] == "missing" for k in ks),
        "spec_silent": len(silent),
        "spec_silent_differs": sum(k["in_plan"] == "differs" for k in silent),
        "material_differs": sum(k["in_plan"] == "differs" and k["difference"] == "material" for k in ks),
        "needless_questions": len(out["needless_questions"]),
    }
    score["coverage"] = round((score["matches"] + score["differs"]) / len(ks), 3) if ks else 0.0
    score["agreement"] = round(score["matches"] / len(ks), 3) if ks else 0.0
    score["sound"] = round((len(ks) - score["missing"] - score["material_differs"]) / len(ks), 3) if ks else 0.0
    return out, score, usage
