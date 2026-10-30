"""Who answers the planner's questions: a person at the terminal, or a
simulated user that answers from the example's MA document."""

from .llm import json_call, make_client

ANSWER_SCHEMA = {
    "type": "object",
    "required": ["in_doc", "answer"],
    "properties": {
        "in_doc": {"type": "boolean", "description": "True if the MA document settles this question."},
        "answer": {"type": "string", "description": "The answer as the MA document decides it, or 'use your default' if it does not."},
    },
}

SIM_SYSTEM = (
    "You play the customer who wrote a hardware spec. The attached micro-architecture "
    "document records what you actually want. Answer the designer's question briefly, "
    "only from that document. If the document does not settle the question, set in_doc "
    "to false and answer 'use your default'. Never invent requirements."
)


class InteractiveUser:
    kind = "interactive"

    def ask(self, q):
        print(f"\n[{q['id']}] {q['question']}")
        print(f"   why: {q['why_it_matters']}")
        print(f"   default: {q['default']}")
        ans = input("   answer (Enter = accept default): ").strip()
        return {"answer": ans or f"Use the default: {q['default']}", "in_doc": None}


class SimulatedUser:
    kind = "simulated"

    def __init__(self, ma_doc, model="claude-opus-5-5"):
        self.client = make_client()
        self.ma_doc = ma_doc
        self.model = model

    def ask(self, q):
        user = (f"# Micro-architecture document\n\n{self.ma_doc}\n\n# Question\n\n"
                f"{q['question']}\n(Default if unanswered: {q['default']})")
        out, _, _ = json_call(self.client, self.model, SIM_SYSTEM, user, ANSWER_SCHEMA,
                              effort="low", max_tokens=8000)
        if not out["in_doc"]:
            out["answer"] = f"Use the default: {q['default']}"
        return out
