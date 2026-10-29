# CodePlanner

A planner for Verilog coding projects. This repository holds a fine-tuning dataset that
teaches a model to turn a **Verilog design specification** into a **micro-architecture plan**.

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
