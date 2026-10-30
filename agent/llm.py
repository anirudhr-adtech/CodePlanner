"""Shared helper: one Claude call that must return JSON matching a schema."""

import copy
import json

import anthropic


def strict_schema(schema):
    """Structured outputs need additionalProperties: false and every property required."""
    s = copy.deepcopy(schema)

    def fix(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                node["additionalProperties"] = False
                node["required"] = list(node.get("properties", {}))
            for v in node.values():
                fix(v)
        elif isinstance(node, list):
            for v in node:
                fix(v)

    fix(s)
    return s


class LLMRefusal(RuntimeError):
    pass


def json_call(client, model, system, user, schema, effort="high", max_tokens=64000):
    """Return (parsed_json, usage_dict, stop_reason)."""
    with client.beta.messages.stream(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
        output_config={"effort": effort,
                       "format": {"type": "json_schema", "schema": strict_schema(schema)}},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    ) as stream:
        resp = stream.get_final_message()
    if resp.stop_reason == "refusal":
        raise LLMRefusal(f"model refused: {getattr(resp, 'stop_details', None)}")
    if resp.stop_reason == "max_tokens":
        raise RuntimeError("output hit max_tokens; plan truncated")
    text = next(b.text for b in resp.content if b.type == "text")
    usage = {"input": resp.usage.input_tokens, "output": resp.usage.output_tokens}
    return json.loads(text), usage, resp.stop_reason


def make_client():
    return anthropic.Anthropic()
