"""Output contract of one planning turn.

The planner LLM answers with JSON matching PLAN_SCHEMA (enforced through
structured outputs). A fine-tuned model replacing Claude later has
to produce the same JSON.

The planner does not decide whether to ask the user. It rates each decision's
impact and its confidence in the choice, and supplies the question; the agent's
ask-or-assume rule (agent/loop.py) decides what is actually asked.
"""

MA_SECTIONS = [
    "Overview", "Interface", "Parameters", "Block Diagram", "Datapath", "Control Logic",
    "Timing & Pipeline", "Clocking & Reset", "Corner Cases & Error Handling",
    "Verification Plan", "Assumptions & Open Questions",
]

LEVELS = ["high", "medium", "low"]

PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "steps": {
            "type": "array",
            "description": "Ordered steps for writing the micro-architecture document.",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "S1, S2, ..."},
                    "title": {"type": "string", "description": "Specific to this spec, not a generic heading."},
                    "goal": {"type": "string"},
                    "spec_evidence": {
                        "type": "array",
                        "description": "Exact quotes copied from the spec that motivate this step.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "section": {"type": "string", "description": "Section id from the numbered spec, e.g. P3."},
                                "quote": {"type": "string", "description": "Verbatim substring of the spec."},
                            },
                        },
                    },
                    "decisions": {
                        "type": "array",
                        "description": "Architecture-level choices only; leave details to the MA writer.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string", "description": "D1, D2, ... unique across the plan."},
                                "topic": {"type": "string"},
                                "options": {"type": "array", "items": {"type": "string"}},
                                "status": {"type": "string", "enum": ["decided", "defaulted"],
                                           "description": "decided: the spec or a user answer settles it. defaulted: the spec is silent and choice is the planner's default."},
                                "choice": {"type": "string"},
                                "rationale": {"type": "string"},
                                "impact": {"type": "string", "enum": LEVELS,
                                           "description": "How much the rest of the architecture changes if this choice is wrong."},
                                "confidence": {"type": "string", "enum": LEVELS,
                                               "description": "Confidence that choice is what the spec author wants."},
                                "question": {"type": "string",
                                             "description": "The question to put to the user about this decision; empty string if decided."},
                            },
                        },
                    },
                    "depends_on": {"type": "array", "items": {"type": "string"}},
                    "output_section": {"type": "array", "items": {"type": "string", "enum": MA_SECTIONS},
                                       "description": "MA doc section(s) this step feeds."},
                    "done_when": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
    },
}
