# CodePlanner

A planner for Verilog coding projects. **Current phase: P0**, an agent that turns a
Verilog design specification into the right **steps for creating a micro-architecture
(MA) document**, with the Claude API as the planning model until our own LLM replaces it
in P1. Writing the MA documents themselves is Phase 2. See [ROADMAP.md](ROADMAP.md).

The `examples/` folder holds 20 specs with reference MA documents. In P0 they are the
answer keys used to score the agent's plans.

## Layout

```
prompts/system.md          system prompt used in every training record
schema/README.md           example format and the required plan sections
examples/NN_name/          one folder per example
  meta.json                id, title, category, difficulty, split, tags
  spec.md                  model input  (the specification)
  microarch.md             model output (the micro-architecture plan)
scripts/build_dataset.py   validates examples and writes data/*.jsonl
data/train.jsonl           generated training set
data/val.jsonl             generated validation set
data/all.jsonl             train + val
```

## Plan structure

Every `microarch.md` uses the same 11 sections: Overview, Interface, Parameters, Block
Diagram, Datapath, Control Logic, Timing & Pipeline, Clocking & Reset, Corner Cases & Error
Handling, Verification Plan, and Assumptions & Open Questions. See `schema/README.md`.

## Building the dataset

```bash
python3 scripts/build_dataset.py --check   # validate only
python3 scripts/build_dataset.py           # validate and write data/*.jsonl
```

Each JSONL line is a chat record:

```json
{"id": "04_sync_fifo",
 "messages": [{"role": "system", "content": "..."},
              {"role": "user", "content": "Create a micro-architecture plan ...\n\n<spec>"},
              {"role": "assistant", "content": "<microarch plan>"}],
 "metadata": {"title": "...", "category": "...", "difficulty": "...", "tags": [...]}}
```

Most chat fine-tuning tools accept the `messages` field as-is. Drop `id` and `metadata` if
your trainer rejects extra keys.

## Adding an example

1. Create `examples/NN_name/` with `meta.json`, `spec.md` and `microarch.md`.
2. Run `python3 scripts/build_dataset.py --check`.
3. Rebuild the JSONL files.

## P0: MA planner agent (v0.1)

The planner does not write the MA doc. It turns a spec into a spec-specific **step plan**
for writing one, and lists the architecture decisions it depends on. Each decision is
`decided` (the spec or an answer settles it) or `defaulted`, with an impact and a
confidence rating plus the question that would settle it. The **agent**, not the model,
decides what to ask: a defaulted decision is put to the user when it is high impact with
less than high confidence, or medium impact with low confidence.

```
spec -> planner LLM (one turn, JSON) -> code checks --fail--> retry with feedback
                                          |pass
                     ask-or-assume rule? --ask--> ask user -> next turn
                                          |no
                                        READY -> plan.json / plan.md
```

| File | Role |
|------|------|
| `agent/planner_llm.py` | The only planning model call. Swap `ClaudePlanner` for the trained model later. |
| `agent/schema.py` | The plan JSON contract (steps, decisions with impact/confidence/question). |
| `prompts/planner_system.md` | Planner instructions. |
| `agent/checker.py` | Code checks: verbatim quotes, every MA section fed, step/decision counts, done-criteria, dependencies, generic titles. |
| `agent/loop.py` | Draft, check, retry, ask-or-assume rule, stop rule (ready or 5 rounds). |
| `agent/user.py` | Interactive user, or a simulated user that answers from the example's MA doc. |
| `agent/judge.py` | Evaluation only: compares the plan's decisions with the MA doc (answer key), separating material from equivalent differences. |
| `agent/rejudge.py` | Re-score an earlier run with the current judge. |

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=...
python3 -m agent --example 04_sync_fifo                 # simulated user + judge
python3 -m agent --example 04_sync_fifo --interactive   # you answer the questions
python3 -m agent --all --jobs 5                         # every example
```

Each run writes `runs/<timestamp>/<example>/`: `log.jsonl` (every prompt, raw output,
check result, question and answer), `plan.json`, `plan.md`, `qa.json`, `summary.json`
and `judge.json`. These logs are what we study to decide the LLM/agent boundary, and
later become training data.
