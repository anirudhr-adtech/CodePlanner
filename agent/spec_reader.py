"""Split a spec into numbered sections so quotes can be cited and checked."""

import re


def normalize(text):
    """Lower-sensitivity form for quote matching: drop markdown marks, collapse spaces."""
    text = re.sub(r"[`*_]", "", text)
    text = text.replace("’", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", text).strip().lower()


def split_sections(spec):
    """Return [(id, text)]: one section per blank-line separated block (P1, P2, ...)."""
    blocks = [b.strip() for b in re.split(r"\n\s*\n", spec) if b.strip()]
    return [(f"P{i}", b) for i, b in enumerate(blocks, 1)]


def numbered(spec):
    """Spec text with section ids prefixed, as shown to the planner."""
    return "\n\n".join(f"[{sid}]\n{text}" for sid, text in split_sections(spec))
