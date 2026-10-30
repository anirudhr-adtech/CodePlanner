"""Output contract of one planning turn.

The planner LLM answers with JSON matching PLAN_SCHEMA (enforced through
structured outputs). A fine-tuned model replacing Claude later has
to produce the same JSON.
"""

PLAN_SCHEMA = {
    "type": "object",
    "required": ["steps", "questions", "assumptions"],
    "properties": {
        "steps": {
            "type": "array",
            "description": "Ordered steps for writing the micro-architecture document.",
            "items": {
                "type": "object",
                "required": ["id", "title", "goal", "spec_evidence", "decisions",
                             "depends_on", "output_section", "done_when"],
                "properties": {
                    "id": {"type": "string", "description": "S1, S2, ..."},
                    "title": {"type": "string", "description": "Specific to this spec, not a generic heading."},
                    "goal": {"type": "string"},
                    "spec_evidence": {
                        "type": "array",
                        "description": "Exact quotes copied from the spec that motivate this step.",
                        "items": {
                            "type": "object",
                            "required": ["section", "quote"],
                            "properties": {
                                "section": {"type": "string", "description": "Section id from the numbered spec, e.g. P3."},
                                "quote": {"type": "string", "description": "Verbatim substring of the spec."},
                            },
                        },
                    },
                    "decisions": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["id", "topic", "options", "status", "rationale"],
                            "properties": {
                                "id": {"type": "string", "description": "D1, D2, ..."},
                                "topic": {"type": "string"},
                                "options": {"type": "array", "items": {"type": "string"}},
                                "status": {"type": "string", "enum": ["decided", "open"]},
                                "choice": {"type": "string", "description": "Chosen option when status is decided; empty string when open."},
                                "rationale": {"type": "string"},
                            },
                        },
                    },
                    "depends_on": {"type": "array", "items": {"type": "string"}},
                    "output_section": {"type": "string", "description": "Which MA doc section(s) this step feeds."},
                    "done_when": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "questions": {
            "type": "array",
            "description": "Questions for the user. Only ask what changes the architecture.",
            "items": {
                "type": "object",
                "required": ["id", "question", "why_it_matters", "blocking", "default", "decision_id"],
                "properties": {
                    "id": {"type": "string", "description": "Q1, Q2, ..."},
                    "question": {"type": "string"},
                    "why_it_matters": {"type": "string"},
                    "blocking": {"type": "boolean", "description": "True only if the spec gives no basis to choose AND the answer changes the architecture."},
                    "default": {"type": "string", "description": "What will be assumed if unanswered."},
                    "decision_id": {"type": "string", "description": "Decision this question resolves."},
                },
            },
        },
        "assumptions": {
            "type": "array",
            "description": "Defaults adopted for non-blocking open items.",
            "items": {"type": "string"},
        },
    },
}
