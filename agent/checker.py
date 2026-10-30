"""Code checks on a planning turn. No model judgement here.

`check_plan` returns (errors, metrics). Errors send the draft back to the LLM;
metrics are logged for studying behaviour.
"""

import re

from .spec_reader import normalize, split_sections

# Bare titles that say nothing about the specific design.
GENERIC_TITLES = {
    "define interface", "define the interface", "define ports", "define parameters",
    "define datapath", "design datapath", "design the datapath", "define control logic",
    "design control logic", "design fsm", "define timing", "define clocking and reset",
    "define reset", "handle corner cases", "verification plan", "plan verification",
    "write verification plan", "document assumptions", "list assumptions", "overview",
    "write overview", "block diagram", "draw block diagram",
}


def _has_cycle(steps):
    graph = {s["id"]: s.get("depends_on", []) for s in steps}
    state = {}

    def visit(n):
        if state.get(n) == 1:
            return True
        if state.get(n) == 2 or n not in graph:
            return False
        state[n] = 1
        if any(visit(m) for m in graph[n]):
            return True
        state[n] = 2
        return False

    return any(visit(n) for n in graph)


def check_plan(plan, spec):
    errors = []
    if not isinstance(plan, dict) or not plan.get("steps"):
        return ["no plan or no steps returned"], {}

    spec_norm = normalize(spec)
    section_ids = {sid for sid, _ in split_sections(spec)}
    steps = plan["steps"]
    step_ids = [s.get("id") for s in steps]
    decision_ids = {d.get("id") for s in steps for d in s.get("decisions", [])}

    if len(set(step_ids)) != len(step_ids):
        errors.append("duplicate step ids")

    quotes = grounded = generic = 0
    for s in steps:
        sid = s.get("id", "?")
        ev = s.get("spec_evidence") or []
        if not ev:
            errors.append(f"{sid}: no spec_evidence")
        for e in ev:
            quotes += 1
            q = normalize(e.get("quote", ""))
            if q and q in spec_norm:
                grounded += 1
            else:
                errors.append(f"{sid}: quote not found verbatim in spec: {e.get('quote', '')!r}")
            if e.get("section") not in section_ids:
                errors.append(f"{sid}: unknown section id {e.get('section')!r}")
        if not s.get("done_when"):
            errors.append(f"{sid}: no done_when criteria")
        for dep in s.get("depends_on", []):
            if dep not in step_ids:
                errors.append(f"{sid}: depends on unknown step {dep!r}")
        for d in s.get("decisions", []):
            if d.get("status") == "decided" and not d.get("choice"):
                errors.append(f"{sid}/{d.get('id')}: decided but no choice given")
        title = re.sub(r"[^a-z ]", "", s.get("title", "").lower()).strip()
        if title in GENERIC_TITLES:
            generic += 1
            errors.append(f"{sid}: title {s.get('title')!r} is generic; make it specific to this design")
    if _has_cycle(steps):
        errors.append("depends_on graph has a cycle")

    questions = plan.get("questions", [])
    for q in questions:
        if not q.get("default"):
            errors.append(f"{q.get('id')}: question has no default")
        if q.get("decision_id") and q["decision_id"] not in decision_ids:
            errors.append(f"{q.get('id')}: refers to unknown decision {q['decision_id']!r}")

    decisions = [d for s in steps for d in s.get("decisions", [])]
    asked_for = {q.get("decision_id") for q in questions}
    for d in decisions:
        if d.get("status") == "open" and d.get("id") not in asked_for:
            errors.append(f"{d.get('id')}: open decision with no question; decide it or ask")
    metrics = {
        "steps": len(steps),
        "decisions": len(decisions),
        "open_decisions": sum(d.get("status") == "open" for d in decisions),
        "questions": len(questions),
        "blocking_questions": sum(bool(q.get("blocking")) for q in questions),
        "quotes": quotes,
        "grounded_quotes": grounded,
        "grounding": round(grounded / quotes, 3) if quotes else 0.0,
        "generic_titles": generic,
    }
    return errors, metrics
