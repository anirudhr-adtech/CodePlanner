"""Render plan JSON as Markdown for people to read."""


def plan_to_markdown(plan, title="MA plan"):
    out = [f"# {title}", ""]
    for s in plan.get("steps", []):
        deps = ", ".join(s.get("depends_on", [])) or "none"
        out += [f"## {s['id']}. {s['title']}", "", f"**Goal:** {s['goal']}", "",
                f"**Feeds:** {s.get('output_section', '')} · **Depends on:** {deps}", "",
                "**Spec evidence:**"]
        out += [f"- [{e['section']}] \"{e['quote']}\"" for e in s.get("spec_evidence", [])]
        if s.get("decisions"):
            out += ["", "**Decisions:**"]
            for d in s["decisions"]:
                head = f"- {d['id']} {d['topic']} ({' / '.join(d.get('options', []))})"
                if d.get("status") == "decided":
                    head += f": **{d.get('choice')}**"
                else:
                    head += ": _open_"
                out += [head, f"  - {d.get('rationale', '')}"]
        out += ["", "**Done when:**"] + [f"- {c}" for c in s.get("done_when", [])] + [""]
    if plan.get("questions"):
        out += ["## Open blocking questions", ""]
        out += [f"- {q['id']}: {q['question']} (default: {q['default']})" for q in plan["questions"]]
        out.append("")
    if plan.get("deferred_questions"):
        out += ["## Deferred (non-blocking) questions", ""]
        out += [f"- {q['id']}: {q['question']} (assumed: {q['default']})" for q in plan["deferred_questions"]]
        out.append("")
    if plan.get("assumptions"):
        out += ["## Assumptions", ""] + [f"- {a}" for a in plan["assumptions"]] + [""]
    return "\n".join(out)
