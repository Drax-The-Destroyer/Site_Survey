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
    customer_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Return combined admin-defined questions for a category/section.

    Merge order (lowest -> highest priority):
      1. category defaults: questions[category_key][section_name]
      2. model overrides: questions["overrides"]["by_model"]["make:model"][section_name]
      3. customer overrides: questions["overrides"]["by_customer"][customer_id][section_name]

    Later layers are appended on top of earlier ones.
    """

    base = (
        (questions_data or {})
        .get(category_key, {})
        .get(section_name, [])
        or []
    )

    model_extra: List[Dict[str, Any]] = []
    customer_extra: List[Dict[str, Any]] = []

    if make_key and model_key:
        overrides_root = (
            (questions_data or {})
            .get("overrides", {})
            .get("by_model", {})
            or {}
        )
        mid = model_q_id(make_key, model_key)
        model_extra = (
            overrides_root.get(mid, {})
            .get(section_name, [])
            or []
        )

    if customer_id:
        customer_root = (
            (questions_data or {})
            .get("overrides", {})
            .get("by_customer", {})
            or {}
        )
        customer_extra = (
            customer_root.get(customer_id, {})
            .get(section_name, [])
            or []
        )

    return list(base) + list(model_extra) + list(customer_extra)
