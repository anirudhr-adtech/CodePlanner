"""Code checks on a planning turn. No model judgement here.

`check_plan` returns (errors, metrics). Errors send the draft back to the LLM;
metrics are logged for studying behaviour.
"""

import re

from .schema import MA_SECTIONS
from .spec_reader import normalize, split_sections

MIN_STEPS = 6
MAX_DECISIONS = 16

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
    decisions = [d for s in steps for d in s.get("decisions", [])]
    decision_ids = [d.get("id") for d in decisions]

    if len(set(step_ids)) != len(step_ids):
        errors.append("duplicate step ids")
    if len(set(decision_ids)) != len(decision_ids):
        errors.append("duplicate decision ids; decision ids must be unique across the plan")
    if len(steps) < MIN_STEPS:
        errors.append(f"only {len(steps)} steps; a complete plan needs at least {MIN_STEPS}")
    if len(decisions) > MAX_DECISIONS:
        errors.append(f"{len(decisions)} decisions; keep only architecture-level ones "
                      f"(at most {MAX_DECISIONS}) and leave details to the MA writer")

    fed = {sec for s in steps for sec in s.get("output_section", [])}
    missing_sections = [sec for sec in MA_SECTIONS if sec not in fed]
    if missing_sections:
        errors.append(f"no step feeds MA section(s): {', '.join(missing_sections)}")

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
        title = re.sub(r"[^a-z ]", "", s.get("title", "").lower()).strip()
        if title in GENERIC_TITLES:
            generic += 1
            errors.append(f"{sid}: title {s.get('title')!r} is generic; make it specific to this design")
    if _has_cycle(steps):
        errors.append("depends_on graph has a cycle")

    for d in decisions:
        did = d.get("id", "?")
        if not d.get("choice"):
            errors.append(f"{did}: no choice given")
        if d.get("status") == "defaulted" and not d.get("question"):
            errors.append(f"{did}: defaulted decision has no question")

    defaulted = [d for d in decisions if d.get("status") == "defaulted"]
    metrics = {
        "steps": len(steps),
        "decisions": len(decisions),
        "defaulted": len(defaulted),
        "defaulted_high_impact": sum(d.get("impact") == "high" for d in defaulted),
        "defaulted_low_confidence": sum(d.get("confidence") == "low" for d in defaulted),
        "quotes": quotes,
        "grounded_quotes": grounded,
        "grounding": round(grounded / quotes, 3) if quotes else 0.0,
        "generic_titles": generic,
        "sections_fed": len(MA_SECTIONS) - len(missing_sections),
    }
    return errors, metrics
