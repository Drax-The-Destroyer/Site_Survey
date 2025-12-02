"""
Declarative form schema loader + helpers for the Site Survey app.

This file keeps the legacy `from questions import FORM_DEFINITION` import
working, and also exposes helpers for working with the JSON-backed
question definition at runtime.
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional

from data_loader import load_questions

# Load JSON-backed question definition at import time (legacy shim).
FORM_DEFINITION: Dict[str, Any] = load_questions(getattr(load_questions, "version", ""))  # type: ignore[arg-type]


def model_q_id(make_key: str, model_key: str) -> str:
    """Stable ID for model-specific question overrides.

    Stored under questions['overrides']['by_model'][model_q_id].
    This mirrors the helper used in the Admin console.
    """

    return f"{make_key}:{model_key}"


def get_questions_for(
    questions_data: Dict[str, Any],
    *,
    category_key: str,
    section_name: str,
    make_key: Optional[str] = None,
    model_key: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Return combined admin-defined questions for a category/section.

    Category questions live at: questions[category_key][section_name]
    Model-specific overrides live at:
      questions["overrides"]["by_model"]["make:model"][section_name]

    Category questions are returned first; model questions are appended.
    If make_key/model_key are omitted or there are no overrides, this
    falls back to just the category questions.
    """

    # Base category-level questions (if any)
    base = (
        (questions_data or {})
        .get(category_key, {})
        .get(section_name, [])
        or []
    )

    extra: List[Dict[str, Any]] = []

    # Optional model-level overrides
    if make_key and model_key:
        overrides_root = (
            (questions_data or {})
            .get("overrides", {})
            .get("by_model", {})
            or {}
        )
        mid = model_q_id(make_key, model_key)
        extra = (
            overrides_root.get(mid, {})
            .get(section_name, [])
            or []
        )

    # Simple merge: category questions first, then model-specific.
    # If we ever want true overrides-by-key, we can extend this with
    # de-dupe logic based on each item's "key".
    return list(base) + list(extra)
