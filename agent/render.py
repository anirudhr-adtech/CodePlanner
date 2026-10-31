"""Render plan JSON as Markdown for people to read."""


def plan_to_markdown(plan, title="MA plan"):
    out = [f"# {title}", ""]
    for s in plan.get("steps", []):
        deps = ", ".join(s.get("depends_on", [])) or "none"
        out += [f"## {s['id']}. {s['title']}", "", f"**Goal:** {s['goal']}", "",
                f"**Feeds:** {', '.join(s.get('output_section', []))} · **Depends on:** {deps}", "",
                "**Spec evidence:**"]
        out += [f"- [{e['section']}] \"{e['quote']}\"" for e in s.get("spec_evidence", [])]
        if s.get("decisions"):
            out += ["", "**Decisions:**"]
            for d in s["decisions"]:
                tag = "decided" if d["status"] == "decided" else f"default, {d['impact']} impact, {d['confidence']} confidence"
                out += [f"- {d['id']} {d['topic']}: **{d['choice']}** ({tag})",
                        f"  - options: {' / '.join(d.get('options', []))}",
                        f"  - {d.get('rationale', '')}"]
        out += ["", "**Done when:**"] + [f"- {c}" for c in s.get("done_when", [])] + [""]
    if plan.get("assumptions"):
        out += ["## Assumptions (defaults not confirmed by the user)", ""]
        out += [f"- {a['decision_id']} {a['topic']}: {a['assumed']} "
                f"({a['impact']} impact, {a['confidence']} confidence)" for a in plan["assumptions"]]
        out.append("")
    return "\n".join(out)
