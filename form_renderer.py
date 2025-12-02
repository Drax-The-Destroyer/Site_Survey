"""
Form rendering utilities for the data-driven survey (Streamlit).

Exports:
- apply_overrides(sections, merged_overrides) -> list[Section]
- render_section(section, answers, lang=None, category=None, make=None, model=None) -> None
- seed_defaults(state_dict, defaults_dict, overwrite_empty_only=True) -> None
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional

import copy
import streamlit as st

from visible_if import is_visible as _is_visible

RADIO_EMPTY_LABEL = "--- Select one ---"


def _find_field_index(fields: List[Dict[str, Any]], name: str) -> int:
    for i, f in enumerate(fields):
        if f.get("name") == name:
            return i
    return -1


from typing import Any, Dict, List


def _normalize_admin_fields(cat_key: str, section_title: str, questions_json: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Normalize Admin -> Question Sets items into runtime field dicts.

    Backwards compatible API:
    - Legacy usage: `questions_json` is the full questions dict and we read
      `questions_json[cat_key][section_title]`.
    - New usage: `questions_json` may be *already* a list of question dicts
      (e.g. result of get_questions_for). In that case we use it directly.

    Input item shape (per Admin UI):
      {key, label, type, required, options, visible_if}

    Output field shape (runtime):
      {name, label?, type, required, options?, visible_if?}

    Also fixes the common 'Yes/No' single-token mistake by splitting on '/'.
    """
    out: List[Dict[str, Any]] = []

    # Accept either a list of question dicts or the full questions.json mapping.
    if isinstance(questions_json, list):
        admin_list = questions_json or []
    else:
        admin_list = (
            (questions_json or {})
            .get(cat_key, {})
            .get(section_title, [])
            or []
        )

    for q in admin_list:
        if not isinstance(q, dict):
            continue
        name = (q.get("key") or "").strip()
        if not name:
            continue

        f: Dict[str, Any] = {
            "name": name,  # key -> name
            "type": (q.get("type") or "text").strip(),
            "required": bool(q.get("required", False)),
        }

        # Prefer literal label if provided (we also support label_key elsewhere).
        if q.get("label"):
            f["label"] = str(q["label"]).strip()

        # Options: expect a list; if a single string contains '/', split defensively.
        opts = q.get("options")
        if isinstance(opts, list):
            cleaned = []
            for item in opts:
                if isinstance(item, str) and "/" in item and "," not in item:
                    parts = [p.strip() for p in item.split("/") if p.strip()]
                    cleaned.extend(parts if parts else [item])
                else:
                    cleaned.append(item)
            f["options"] = cleaned

        # visible_if can be a simple {"field": "...", "equals": "..."} or our DSL
        if isinstance(q.get("visible_if"), dict):
            f["visible_if"] = q["visible_if"]

        out.append(f)

    return out


# Small public alias for easy import
normalize_admin_fields = _normalize_admin_fields


def apply_overrides(sections: List[Dict[str, Any]], merged_overrides: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Apply merged overrides onto a composed sections list:
      - remove fields in hide_fields
      - insert insert_after fields
      - mark required per overrides
    Returns a deep-copied list.
    """
    ov = merged_overrides or {}
    hide_fields = set(ov.get("hide_fields") or [])
    inserts = list(ov.get("insert_after") or [])
    required = set(ov.get("required") or [])

    out_sections = copy.deepcopy(sections or [])

    # 1) Hide fields
    if hide_fields:
        for sec in out_sections:
            sec["fields"] = [f for f in (sec.get("fields") or []) if f.get(
                "name") not in hide_fields]

    # 2) Insert fields after a target
    for ins in inserts:
        after_name = (ins or {}).get("after")
        new_field = (ins or {}).get("field")
        if not after_name or not isinstance(new_field, dict):
            continue
        inserted = False
        for sec in out_sections:
            fields = sec.get("fields") or []
            idx = _find_field_index(fields, after_name)
            if idx >= 0:
                fields.insert(idx + 1, copy.deepcopy(new_field))
                inserted = True
                break
        # If not found anywhere, append to last section as a fallback
        if not inserted and out_sections:
            out_sections[-1].setdefault("fields", []).append(copy.deepcopy(new_field))

    # 3) Mark required flags
    if required:
        for sec in out_sections:
            for fld in (sec.get("fields") or []):
                if fld.get("name") in required:
                    fld["required"] = True

    return out_sections


def seed_defaults(state: Dict[str, Any], defaults: Dict[str, Any], overwrite_empty_only: bool = True) -> None:
    """
    Seed default values into Streamlit session state or an answers dict.
    If overwrite_empty_only is True, only set when missing or empty/None/""
    """
    if not isinstance(defaults, dict):
        return
    for k, v in defaults.items():
        if not overwrite_empty_only:
            st.session_state[k] = v
            state[k] = v
            continue
        curr = st.session_state.get(k, state.get(k))
        if curr is None or curr == "":
            st.session_state[k] = v
            state[k] = v


def _translated_label(field: Dict[str, Any], lang: Optional[Dict[str, str]]) -> str:
    # Prefer label_key -> lookup in lang map; fallback to literal 'label' -> fallback to name
    name = field.get("name") or ""
    if lang and field.get("label_key"):
        return lang.get(field["label_key"], field.get("label", name))
    return field.get("label", name)


def _coerce_number_input_defaults(field: Dict[str, Any]) -> Dict[str, Any]:
    # Provide sensible defaults for number_input to avoid Streamlit warnings
    kwargs: Dict[str, Any] = {}
    if "min" in field:
        kwargs["min_value"] = field["min"]
    if "max" in field:
        kwargs["max_value"] = field["max"]
    if "step" in field:
        kwargs["step"] = field["step"]
    else:
        # Prefer integer step when reasonable
        kwargs["step"] = 1 if isinstance(field.get("default"), int) else 1
    return kwargs


def _init_field_state(field: Dict[str, Any], answers: Dict[str, Any]) -> None:
    """
    Ensure st.session_state[name] is initialized for a field and keep answers in sync.

    Rules:
    - If the key already exists in st.session_state, treat that as canonical and
      mirror into answers if missing.
    - Otherwise, prefer:
        1) Existing answers[name] (e.g. from seed_defaults / saved state)
        2) field["default"] if present
        3) A type-appropriate empty value
    - For select/radio with no effective default, we intentionally do NOT pre-seed
      st.session_state so that Streamlit's own default behaviour (first option)
      can apply on first render.
    """
    name = field.get("name")
    if not name:
        return

    # Existing widget state is the single source of truth
    if name in st.session_state:
        # Always mirror canonical widget state back into answers
        answers[name] = st.session_state[name]
        return

    ftype = field.get("type", "text")

    # Start from any existing canonical answer or field-level default
    if name in answers:
        initial = answers[name]
    elif "default" in field:
        initial = field["default"]
    else:
        initial = None

    # Type-specific fallbacks when no explicit default provided
    if initial is None:
        if ftype in ("text",):
            initial = ""
        elif ftype in ("textarea",):
            initial = ""
        elif ftype == "number":
            default_val = field.get("default", 0)
            if not isinstance(default_val, (int, float)):
                try:
                    default_val = int(default_val)
                except Exception:
                    default_val = 0
            initial = default_val
        elif ftype == "multiselect":
            if initial is None:
                initial = []
            elif not isinstance(initial, list):
                initial = [initial]
        elif ftype == "checkbox":
            initial = False
        elif ftype == "time":
            # Let Streamlit's time_input handle None as "no time chosen" / default
            initial = None
        elif ftype in ("select", "radio"):
            # For selects/radios with no default, do not pre-seed session state.
            initial = None
        elif ftype == "file":
            initial = [] if field.get("multiple", False) else None
        else:
            initial = ""

    # For select/radio, ensure any default is among options; otherwise treat as no default.
    if ftype in ("select", "radio"):
        opts = field.get("options", []) or []
        if initial is not None and initial not in opts:
            initial = None

    # If we still have no concrete initial value, just reflect explicit None in answers
    if initial is None:
        if name not in answers:
            answers[name] = None
        return

    st.session_state[name] = initial
    answers[name] = initial


def render_section(
    section: Dict[str, Any],
    answers: Dict[str, Any],
    *,
    lang: Optional[Dict[str, str]] = None,
    category: Optional[str] = None,
    make: Optional[str] = None,
    model: Optional[str] = None,
    show_required_errors: bool = False
) -> None:
    """
    Render a section's fields with Streamlit widgets, updating the provided answers dict.

    - Uses visible_if with injected virtual fields (__category__, __make__, __model__)
    - Translates labels via lang map when label_key/title_key present
    - Supports types: text, textarea, radio, time (HH:MM), number, select, multiselect, checkbox, file
    - Displays a small red caption under required fields if show_required_errors=True and value is missing
    """
    fields = section.get("fields") or []
    for field in fields:
        name = field.get("name")
        if not name:
            continue

        # visible_if evaluation
        if not _is_visible(field, answers, category, make, model):
            continue

        ftype = field.get("type", "text")
        help_text = field.get("help")

        # Use the field name as the Streamlit widget key so widget state and
        # canonical answers share the same identifier.
        key = name
        label_text = _translated_label(field, lang)
        if field.get("required"):
            # Visual indicator only; Streamlit widgets do not enforce required at input
            label_to_show = f"{label_text} *"
        else:
            label_to_show = label_text

        # Ensure widget/session state is initialized before rendering so that
        # one-time defaults (overrides or field["default"]) are respected without
        # re-applying them on every rerun.
        _init_field_state(field, answers)

        # Render per type
        if ftype == "text":
            st.text_input(label_to_show, help=help_text, key=key)
            val = st.session_state.get(name)
            answers[name] = val

        elif ftype == "textarea":
            st.text_area(label_to_show, help=help_text, key=key)
            val = st.session_state.get(name)
            answers[name] = val

        elif ftype == "radio":
            options = field.get("options", []) or []

            # Always show the placeholder as the first option.
            ui_options = [RADIO_EMPTY_LABEL] + options

            st.radio(
                label_to_show,
                options=ui_options,
                key=key,
                horizontal=False,
                help=help_text,
            )

            raw_val = st.session_state.get(name)

            # Map placeholder selection to None in canonical answers so that
            # required checks and PDF rendering treat it as "unanswered".
            if raw_val == RADIO_EMPTY_LABEL:
                val = None
            else:
                val = raw_val

            answers[name] = val

        elif ftype == "time":
            # Render time without seconds by using minute step granularity
            st.time_input(label_to_show, step=60, help=help_text, key=key)
            val = st.session_state.get(name)
            answers[name] = val

        elif ftype == "number":
            kwargs = _coerce_number_input_defaults(field)
            st.number_input(label_to_show, help=help_text, key=key, **kwargs)
            val = st.session_state.get(name)
            answers[name] = val

        elif ftype == "select":
            options = field.get("options", []) or []
            st.selectbox(
                label_to_show,
                options=options,
                help=help_text,
                key=key,
            )
            val = st.session_state.get(name)
            answers[name] = val

        elif ftype == "multiselect":
            options = field.get("options", []) or []
            st.multiselect(
                label_to_show,
                options=options,
                help=help_text,
                key=key,
            )
            val = st.session_state.get(name)
            # Ensure multiselect answers are always a list
            if val is None:
                val = []
            answers[name] = val

        elif ftype == "checkbox":
            st.checkbox(label_to_show, help=help_text, key=key)
            val = st.session_state.get(name)
            answers[name] = bool(val)

        elif ftype == "file":
            allow_multi = bool(field.get("multiple", False))
            exts = field.get("allowed_ext")
            if isinstance(exts, list):
                # Streamlit expects extensions without dot, e.g., ["png", "jpg"]
                types = [
                    e[1:] if isinstance(e, str) and e.startswith(".") else e
                    for e in exts
                ]
            else:
                types = None
            st.file_uploader(
                label_to_show,
                type=types,
                accept_multiple_files=allow_multi,
                help=help_text,
                key=key,
            )
            val = st.session_state.get(name)
            answers[name] = val

        else:
            # Fallback to text
            st.text_input(label_to_show, help=help_text, key=key)
            val = st.session_state.get(name)
            answers[name] = val

        # Inline required error
        if show_required_errors and field.get("required"):
            v = answers.get(name)
            is_empty = (v is None) or (isinstance(v, str) and v.strip() == "") or (
                isinstance(v, list) and len(v) == 0)
            if is_empty:
                st.caption(":red[This field is required.]")
