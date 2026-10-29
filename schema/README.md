# Example schema

Each training example lives in its own folder under `examples/`:

```
examples/NN_short_name/
  meta.json        # metadata
  spec.md          # model input: the specification, as a user would write it
  microarch.md     # model output: the micro-architecture plan
```

## meta.json

```json
{
  "id": "04_sync_fifo",
  "title": "Synchronous FIFO",
  "category": "storage",
  "difficulty": "easy",
  "split": "train",
  "tags": ["fifo", "memory", "flow-control"]
}
```

| Field | Values |
|-------|--------|
| `id` | Must equal the folder name. |
| `category` | `counter`, `fsm`, `storage`, `arithmetic`, `dsp`, `interface`, `bus`, `arbitration`, `memory-system`, `processor`, `peripheral` |
| `difficulty` | `easy`, `medium`, `hard` |
| `split` | `train` or `val` |
| `tags` | Free-form keywords. |

## spec.md (input)

Write it the way a real engineer, customer or architect would hand over a spec. Vary the
style across examples on purpose (bullet lists, prose, register tables, partial specs with
gaps) so the model learns to handle real-world input. Leaving some details unspecified is
fine and useful: the plan has to resolve them in section 11.

## microarch.md (output)

It must contain these level-2 headings, exactly and in this order (the build script
checks this):

1. `## 1. Overview` – purpose, key features, top-level behaviour summary.
2. `## 2. Interface` – port table: Name | Dir | Width | Description. Group by interface.
3. `## 3. Parameters` – Name | Default | Legal range | Description. Derived localparams.
4. `## 4. Block Diagram` – ASCII diagram plus a submodule table (instance, module, purpose).
5. `## 5. Datapath` – registers (name, width, reset value, purpose), muxes, arithmetic, memories.
6. `## 6. Control Logic` – FSM state tables, encodings, transition conditions, control-signal equations.
7. `## 7. Timing & Pipeline` – latency, throughput, pipeline stages, a cycle-by-cycle table.
8. `## 8. Clocking & Reset` – clocks, reset type/polarity, synchronizers, CDC.
9. `## 9. Corner Cases & Error Handling` – overflow, back-pressure, illegal inputs, simultaneous events.
10. `## 10. Verification Plan` – directed tests, random tests, assertions (SVA-style), coverage points.
11. `## 11. Assumptions & Open Questions` – decisions taken where the spec was silent.

Use Markdown tables, ASCII diagrams in fenced code blocks, and short Verilog snippets only
where they remove ambiguity. No full RTL.
