from __future__ import annotations

from typing import Any, Dict, List, Set, TypedDict


class OverrideOut(TypedDict):
    required: Set[str]
    defaults: Dict[str, Any]
    hide_fields: Set[str]
    # { "after": str, "field": FieldSchema }
    insert_after: List[Dict[str, Any]]


def _normalize_scope_name(s: str) -> str:
    # Defensive normalization (strip spaces); input is trusted from questions.json
    return (s or "").strip()


def _empty() -> OverrideOut:
    return {
        "required": set(),
        "defaults": {},
        "hide_fields": set(),
        "insert_after": [],
    }


def merge_overrides(qdef: Dict[str, Any], category: str, make: str, model: str) -> OverrideOut:
    """
    Merge overrides in increasing precedence order:
      "*", f"category:{category}", f"make:{make}", f"model:{make}|{model}"
    Rules:
      - required: extend set (union)
      - defaults: later scopes overwrite same keys
      - hide_fields: extend set (union)
      - insert_after: concatenate (preserve order; later scopes appended)
    Returns a normalized structure with sets for required/hide_fields.
    """
    ov_map: Dict[str, Any] = (qdef.get("overrides") or {})
    scopes: List[str] = [
        "*",
        f"category:{category}",
        f"make:{make}",
        f"model:{make}|{model}",
    ]

    out: OverrideOut = _empty()

    for s in scopes:
        scope = _normalize_scope_name(s)
        ov = ov_map.get(scope)
        if not ov:
            continue

        # required (list[str] -> set union)
        req = ov.get("required")
        if isinstance(req, list):
            out["required"].update([str(x) for x in req])

        # defaults (dict -> merge with overwrite)
        defs = ov.get("defaults")
        if isinstance(defs, dict):
            out["defaults"].update(defs)

        # hide_fields (list[str] -> set union)
        hides = ov.get("hide_fields")
        if isinstance(hides, list):
            out["hide_fields"].update([str(x) for x in hides])

        # insert_after (list[{"after": str, "field": {...}}]) -> concat
        inserts = ov.get("insert_after")
        if isinstance(inserts, list):
            # Shallow validation: only accept dicts with at least "after" and "field"
            for item in inserts:
                if isinstance(item, dict) and "after" in item and "field" in item:
                    out["insert_after"].append(item)

    return out
