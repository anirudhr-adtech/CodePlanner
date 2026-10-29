#!/usr/bin/env python3
"""Validate examples/ and build chat-format JSONL training files in data/.

Usage:
    python3 scripts/build_dataset.py            # validate + build
    python3 scripts/build_dataset.py --check    # validate only
"""

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"
DATA = ROOT / "data"
SYSTEM_PROMPT = ROOT / "prompts" / "system.md"

REQUIRED_SECTIONS = [
    "1. Overview",
    "2. Interface",
    "3. Parameters",
    "4. Block Diagram",
    "5. Datapath",
    "6. Control Logic",
    "7. Timing & Pipeline",
    "8. Clocking & Reset",
    "9. Corner Cases & Error Handling",
    "10. Verification Plan",
    "11. Assumptions & Open Questions",
]
META_FIELDS = {"id", "title", "category", "difficulty", "split", "tags"}
CATEGORIES = {
    "counter", "fsm", "storage", "arithmetic", "dsp", "interface", "bus",
    "arbitration", "memory-system", "processor", "peripheral",
}
DIFFICULTIES = {"easy", "medium", "hard"}
SPLITS = {"train", "val"}
USER_TEMPLATE = (
    "Create a micro-architecture plan for the following Verilog design "
    "specification.\n\n{spec}"
)


def validate(folder):
    errors = []
    meta_path, spec_path, ua_path = (
        folder / "meta.json", folder / "spec.md", folder / "microarch.md")
    for p in (meta_path, spec_path, ua_path):
        if not p.is_file():
            errors.append(f"missing {p.name}")
    if errors:
        return None, errors

    try:
        meta = json.loads(meta_path.read_text())
    except json.JSONDecodeError as e:
        return None, [f"meta.json: {e}"]
    missing = META_FIELDS - meta.keys()
    if missing:
        errors.append(f"meta.json missing fields: {sorted(missing)}")
    if meta.get("id") != folder.name:
        errors.append(f"meta id {meta.get('id')!r} != folder name {folder.name!r}")
    if meta.get("category") not in CATEGORIES:
        errors.append(f"bad category {meta.get('category')!r}")
    if meta.get("difficulty") not in DIFFICULTIES:
        errors.append(f"bad difficulty {meta.get('difficulty')!r}")
    if meta.get("split") not in SPLITS:
        errors.append(f"bad split {meta.get('split')!r}")

    spec = spec_path.read_text().strip()
    ua = ua_path.read_text().strip()
    if len(spec) < 200:
        errors.append("spec.md is suspiciously short")

    headings = [h.strip() for h in re.findall(r"^## (.+)$", ua, re.MULTILINE)]
    if headings != REQUIRED_SECTIONS:
        errors.append(
            "microarch.md level-2 headings must be exactly, in order:\n      "
            + "\n      ".join(REQUIRED_SECTIONS)
            + "\n    found:\n      " + "\n      ".join(headings))
    if ua.count("```") % 2:
        errors.append("microarch.md has an unclosed code fence")

    return {"meta": meta, "spec": spec, "microarch": ua}, errors


def to_record(ex, system):
    return {
        "id": ex["meta"]["id"],
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": USER_TEMPLATE.format(spec=ex["spec"])},
            {"role": "assistant", "content": ex["microarch"]},
        ],
        "metadata": {k: ex["meta"][k] for k in ("title", "category", "difficulty", "tags")},
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="validate only, write nothing")
    args = ap.parse_args()

    folders = sorted(p for p in EXAMPLES.iterdir() if p.is_dir())
    examples, failed = [], False
    for folder in folders:
        ex, errors = validate(folder)
        if errors:
            failed = True
            print(f"FAIL {folder.name}")
            for e in errors:
                print(f"    {e}")
        else:
            examples.append(ex)
    if failed:
        sys.exit(1)
    print(f"OK   {len(examples)} examples valid")
    if args.check:
        return

    system = SYSTEM_PROMPT.read_text().strip()
    DATA.mkdir(exist_ok=True)
    outputs = {"train": [], "val": []}
    for ex in examples:
        outputs[ex["meta"]["split"]].append(to_record(ex, system))
    outputs["all"] = outputs["train"] + outputs["val"]
    for name, records in outputs.items():
        path = DATA / f"{name}.jsonl"
        with path.open("w") as f:
            for r in records:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"wrote {path.relative_to(ROOT)} ({len(records)} records)")


if __name__ == "__main__":
    main()
