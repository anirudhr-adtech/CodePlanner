# Roadmap

Current focus: **Phase 0 and Phase 1 only.** Writing MA documents is Phase 2 and is out of
scope for now.

| Phase | Goal | Status |
|-------|------|--------|
| **P0** | Agent that produces the right **steps for creating an MA doc** from a spec, with the Claude API as the planning model | In progress (v0.1) |
| **P1** | Our own planner LLM that replaces the Claude API inside the P0 agent | Not started |
| P1.1 | Generate training sets | |
| P1.2 | Train | |
| P1.3 | Test, and loop back for improvement | |
| P2 | Write correct MA specs from the steps | Later, out of scope now |

## P0: Planning agent with the API inside

The agent turns a spec into a spec-specific step plan for writing the MA doc, asks the
user only the questions that matter, and stops when the plan is ready. The planning
model sits behind one interface (`agent/planner_llm.py`) so the P1 model can replace it
without changing the agent.

The MA docs in `examples/` are **reference answer keys** for scoring P0 plans. They are
not P2 output.

Done so far:
- v0: agent loop, code checks, simulated user, judge against the answer keys.
- v0.1: the agent owns the ask-or-assume rule; plans stay at architecture level; every
  MA section must be covered. Plans published in `plans/v0.1/`.

| Metric (20 specs) | v0 | v0.1 |
|---|---|---|
| Agreement with answer key | 69% | 78% |
| Material differences | 31 | 18 |
| Questions asked / needless | 2 / 0 | 31 / 6 |
| Decisions per plan (median) | 22 | 11 |

Goal set: **P0 at 90% good** (sound key decisions). Work towards it, scored on the 14
dev specs with 3 runs each; the 6 test specs in `agent/splits.json` are held out.

| Dev metric (pooled over runs) | v0.1 | v0.2 (42 runs) | v0.3 (32 of 42 runs) |
|---|---|---|---|
| P0 sound (delegated counts) | 89.2% | 91.0% | **93.3%** |
| Strict sound | 84.3% | 89.6% | **91.4%** |
| Agreement with answer key | 72% | 74% | 78% |
| Material differences per plan | 0.96 | 1.10 | 0.69 |
| Questions per plan | 1.6 | 1.6 | 4.0 |
| Needless share | 9-14% | 21% | 15.5% |

- v0.2: minimal-scope defaults, corner-case recommendations, confidence definitions, no
  questions on tool flow.
- v0.3: structured corner cases the agent can ask about, ask rule covers medium/medium,
  spec-delegated choices are not asked, agent repairs a missing question.
- The v0.3 dev run stopped when the API account ran out of credit (10 runs left). Still
  to do: finish dev, then 3 runs on the held-out test specs.

Proposed exit criteria for P0 (to be confirmed):
- Results repeat across 3 runs per spec, not one lucky run.
- Sound decisions (no material difference, nothing missing) at or above 90%.
- Needless questions at or below 10% of questions asked.
- Plan format and LLM/agent boundary frozen, because P1 trains against them.

## P1: Planner LLM

- **P1.1 Training sets:** agent logs from P0 runs (spec, Q&A history, plan JSON), the
  judge's verdict on every decision as labels for impact/confidence calibration, more
  specs, multi-turn pairs.
- **P1.2 Training:** LoRA fine-tune of an open 7-8B model on the frozen plan format.
- **P1.3 Testing and loop:** swap the trained model into the P0 agent, score it with the
  same judge on held-out specs, feed the failures back into P1.1.
