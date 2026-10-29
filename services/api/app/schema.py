"""The Brief JSON contract, loaded from schema/brief.schema.json at the repo
root, and the per-section draft schemas derived from it.

One source of truth: the strict schemas the models are asked to fill are
built from the same $defs the UI and fixtures are checked against.
"""

import copy
import json
from functools import lru_cache
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker, ValidationError
from referencing import Registry, Resource

from app.config import REPO_ROOT

SECTION_IDS = ["on_your_grid", "coming", "your_bill", "protection", "hearing"]

# The one structured object each section carries beyond summary and claims.
SECTION_EXTRA: dict[str, tuple[str, str, bool]] = {
    # section: (property name, $defs name, is_array)
    "on_your_grid": ("facilities", "facility", True),
    "coming": ("facilities", "facility", True),
    "your_bill": ("price", "price", False),
    "protection": ("tariff", "tariff", False),
    "hearing": ("hearing", "hearing", False),
}

# What a drafted claim looks like before assembly turns it into a schema claim.
CLAIM_DRAFT = {
    "type": "object",
    "required": ["text", "source_title", "source_url", "quote", "page", "confidence"],
    "properties": {
        "text": {"type": "string", "description": "One factual sentence."},
        "source_title": {"type": "string"},
        "source_url": {
            "type": "string",
            "description": "A real, public URL you are confident exists.",
        },
        "quote": {
            "type": "string",
            "description": "Verbatim text from the source that supports the claim. "
            "Empty if you cannot recall one.",
        },
        "page": {"type": ["integer", "null"]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
}

# The plain-language strip, drafted after the five sections from their
# summaries. The bill sentence is never drafted: headline.py derives it from
# the price block, so no model can put a causal claim about bills here.
HOUSE_TOPICS = ["water", "noise", "land", "air", "grid", "taxes", "other"]
HOUSE_DRAFT = {
    "type": "object",
    "required": ["lines"],
    "properties": {
        "lines": {
            "type": "array",
            "maxItems": 3,
            "description": "Two or three sentences a resident would screenshot for a neighbor.",
            "items": {
                "type": "object",
                "required": ["text", "topic", "confidence", "claims"],
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "One or two short sentences. Plain words, no jargon. "
                        "Compare numbers to something a person knows (homes, miles, fields).",
                    },
                    "topic": {"enum": HOUSE_TOPICS},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "claims": {
                        "type": "array",
                        "items": CLAIM_DRAFT,
                        "description": "Every number in the sentence, with its source.",
                    },
                },
            },
        }
    },
}


def _metric_house_draft() -> dict[str, Any]:
    """HOUSE_DRAFT for a metric region: the same shape, numbers compared to
    kilometres and pitches instead of miles and fields."""
    out = copy.deepcopy(HOUSE_DRAFT)
    text = out["properties"]["lines"]["items"]["properties"]["text"]
    text["description"] = text["description"].replace(
        "(homes, miles, fields)", "(homes, kilometres, pitches)"
    )
    return out


HOUSE_DRAFT_METRIC = _metric_house_draft()

VERDICT_SCHEMA = {
    "type": "object",
    "required": ["verdict", "note"],
    "additionalProperties": False,
    "properties": {
        "verdict": {"enum": ["supported", "contradicted", "unverifiable"]},
        "note": {"type": "string", "description": "One sentence saying why."},
    },
}


@lru_cache
def load_brief_schema() -> dict[str, Any]:
    with open(REPO_ROOT / "schema" / "brief.schema.json", encoding="utf-8") as f:
        return json.load(f)


@lru_cache
def load_scenario_schema() -> dict[str, Any]:
    with open(REPO_ROOT / "schema" / "scenario.schema.json", encoding="utf-8") as f:
        return json.load(f)


@lru_cache
def _registry() -> Registry:
    """Both contracts under their $id, so the scenario's
    'brief.schema.json#/$defs/...' references resolve to the brief's own defs."""
    return Registry().with_resources(
        (s["$id"], Resource.from_contents(s)) for s in (load_brief_schema(), load_scenario_schema())
    )


@lru_cache
def _brief_validator() -> Draft202012Validator:
    return Draft202012Validator(
        load_brief_schema(), registry=_registry(), format_checker=FormatChecker()
    )


@lru_cache
def _scenario_validator() -> Draft202012Validator:
    return Draft202012Validator(
        load_scenario_schema(), registry=_registry(), format_checker=FormatChecker()
    )


def _errors(validator: Draft202012Validator, doc: dict[str, Any]) -> list[str]:
    return [
        f"{'/'.join(str(p) for p in e.absolute_path)}: {e.message}"
        for e in validator.iter_errors(doc)
    ]


def validate_brief(brief: dict[str, Any]) -> None:
    """Raise jsonschema.ValidationError if the brief breaks the contract."""
    _brief_validator().validate(brief)


def brief_errors(brief: dict[str, Any]) -> list[str]:
    return _errors(_brief_validator(), brief)


def validate_scenario(scenario: dict[str, Any]) -> None:
    """Raise jsonschema.ValidationError if the scenario breaks its contract."""
    _scenario_validator().validate(scenario)


def scenario_errors(scenario: dict[str, Any]) -> list[str]:
    return _errors(_scenario_validator(), scenario)


# --- draft schemas ----------------------------------------------------------


# Keys the engine owns and a model never fills: pruned from the draft schemas,
# so the prompts and strict schemas stay as they were before the key existed.
_ENGINE_ONLY: dict[str, tuple[str, ...]] = {"price": ("granularity",), "tariff": ("kind",)}


def _defs() -> dict[str, Any]:
    return load_brief_schema()["$defs"]


def _draft_defs() -> dict[str, Any]:
    """The $defs a draft is built from: the brief's, less engine-only keys."""
    defs = copy.deepcopy(_defs())
    for name, keys in _ENGINE_ONLY.items():
        node = defs[name]
        for k in keys:
            node["properties"].pop(k, None)
        if "required" in node:
            node["required"] = [r for r in node["required"] if r not in keys]
    return defs


def _inline(node: Any, defs: dict[str, Any]) -> Any:
    """Replace every {"$ref": "#/$defs/x"} with a deep copy of x, recursively."""
    if isinstance(node, dict):
        if "$ref" in node:
            name = node["$ref"].rsplit("/", 1)[-1]
            return _inline(copy.deepcopy(defs[name]), defs)
        return {k: _inline(v, defs) for k, v in node.items()}
    if isinstance(node, list):
        return [_inline(v, defs) for v in node]
    return node


def build_draft_schema(section_id: str) -> dict[str, Any]:
    """The un-strict (original-rules) schema for one section's draft: what the
    model's output is validated against after null pruning."""
    defs = _draft_defs()
    prop, def_name, is_array = SECTION_EXTRA[section_id]
    extra = (
        {"type": "array", "items": {"$ref": f"#/$defs/{def_name}"}}
        if is_array
        else {"$ref": f"#/$defs/{def_name}"}
    )
    schema = {
        "type": "object",
        "required": ["confidence", "summary", "gap", "card_line", prop, "claims"],
        "properties": {
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "summary": {
                "type": "string",
                "description": "Two or three plain-English sentences. "
                "Says not known when it is not.",
            },
            "gap": {
                "type": ["string", "null"],
                "description": "What you could not find out, and why. Null if nothing is missing.",
            },
            "card_line": {
                "type": ["string", "null"],
                "description": "One line for the share card, 60 characters or fewer, no causal "
                "claims. Null if nothing worth saying.",
            },
            prop: extra,
            "claims": {
                "type": "array",
                "items": CLAIM_DRAFT,
                "description": "Every checkable statement in the summary and the structured "
                "data, each with its source.",
            },
        },
    }
    return _inline(schema, defs)


_DROP_KEYS = {
    "format",
    "minimum",
    "maximum",
    "minItems",
    "maxItems",
    "minLength",
    "maxLength",
    "pattern",
    "$id",
    "$schema",
}


def strictify(node: Any, *, required: bool = True) -> Any:
    """Turn an (inlined) schema into one the OpenAI strict mode accepts:
    additionalProperties false, every property required, no validation keywords
    strict mode rejects. Properties the original schema left optional become
    nullable so the model can say "none" instead of inventing a value; the
    pruning step then removes those nulls before validation against the original."""
    if isinstance(node, list):
        return [strictify(v) for v in node]
    if not isinstance(node, dict):
        return node
    out: dict[str, Any] = {k: v for k, v in node.items() if k not in _DROP_KEYS}
    if "properties" in out:
        req = set(out.get("required", []))
        out["properties"] = {
            k: strictify(v, required=k in req) for k, v in out["properties"].items()
        }
        out["required"] = list(out["properties"].keys())
        out["additionalProperties"] = False
    if "items" in out:
        out["items"] = strictify(out["items"])
    if not required:
        out = _nullable(out)
    return out


def _nullable(node: dict[str, Any]) -> dict[str, Any]:
    if "enum" in node:
        if None not in node["enum"]:
            node["enum"] = [*node["enum"], None]
        return node
    t = node.get("type")
    if isinstance(t, str):
        if t in ("object", "array"):
            # Objects and arrays cannot take a type union in strict mode; wrap.
            return {"anyOf": [node, {"type": "null"}]}
        node["type"] = [t, "null"]
    elif isinstance(t, list) and "null" not in t:
        node["type"] = [*t, "null"]
    return node


@lru_cache
def draft_schemas(section_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """(original, strict) schemas for a section draft."""
    original = build_draft_schema(section_id)
    return original, strictify(copy.deepcopy(original))


def prune_nulls(obj: Any, schema: dict[str, Any]) -> Any:
    """Remove null values for properties the original schema does not require
    and does not itself allow to be null. Everything else passes through."""
    if isinstance(obj, dict) and (schema.get("type") == "object" or "properties" in schema):
        props = schema.get("properties", {})
        req = set(schema.get("required", []))
        out = {}
        for k, v in obj.items():
            sub = props.get(k, {})
            if v is None and k not in req and not _allows_null(sub):
                continue
            out[k] = prune_nulls(v, sub) if sub else v
        return out
    if isinstance(obj, list) and "items" in schema:
        return [prune_nulls(v, schema["items"]) for v in obj]
    return obj


def _allows_null(schema: dict[str, Any]) -> bool:
    t = schema.get("type")
    if t == "null" or (isinstance(t, list) and "null" in t):
        return True
    return "enum" in schema and None in schema["enum"]


@lru_cache
def house_schemas(units: str = "us") -> tuple[dict[str, Any], dict[str, Any]]:
    """(original, strict) schemas for the at-your-house draft; `units` is the
    region's locale.units ("us" or "metric")."""
    base = HOUSE_DRAFT if units == "us" else HOUSE_DRAFT_METRIC
    return base, strictify(copy.deepcopy(base))


def validate_house_draft(draft: dict[str, Any], units: str = "us") -> dict[str, Any]:
    original, _ = house_schemas(units)
    pruned = prune_nulls(draft, original)
    Draft202012Validator(original, format_checker=FormatChecker()).validate(pruned)
    return pruned


def validate_draft(section_id: str, draft: dict[str, Any]) -> dict[str, Any]:
    """Prune nulls, then validate against the original-rules schema. Returns
    the pruned draft or raises ValidationError."""
    original, _ = draft_schemas(section_id)
    pruned = prune_nulls(draft, original)
    Draft202012Validator(original, format_checker=FormatChecker()).validate(pruned)
    return pruned


__all__ = [
    "HOUSE_DRAFT",
    "HOUSE_DRAFT_METRIC",
    "HOUSE_TOPICS",
    "SECTION_EXTRA",
    "SECTION_IDS",
    "VERDICT_SCHEMA",
    "ValidationError",
    "brief_errors",
    "build_draft_schema",
    "draft_schemas",
    "house_schemas",
    "load_brief_schema",
    "load_scenario_schema",
    "prune_nulls",
    "scenario_errors",
    "strictify",
    "validate_brief",
    "validate_draft",
    "validate_house_draft",
    "validate_scenario",
]
