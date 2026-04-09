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
import re
import streamlit as st

from utils.logger import setup_logger
from visible_if import is_visible as _is_visible

logger = setup_logger(__name__)

NUMBER_VALUE_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")


def _find_field_index(fields: List[Dict[str, Any]], name: str) -> int:
    for i, f in enumerate(fields):
        if f.get("name") == name:
            return i
    return -1


from typing import Any, Dict, List

def _normalize_admin_fields(cat_key: str, section_title: str, questions_json: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Adapt Admin -> Question Sets items stored like:
      questions_json[cat_key][section_title] = [
        {key,label,type,required,options,visible_if}
      ]
    into runtime fields with shape:
      {name, label?, type, required, options?, visible_if?}
    Also fixes the common 'Yes/No' single-token mistake by splitting on '/'.
    """
    out: List[Dict[str, Any]] = []
    admin_list = (questions_json or {}).get(cat_key, {}).get(section_title, []) or []

    for q in admin_list:
        if not isinstance(q, dict):
            continue
        name = (q.get("key") or "").strip()
        if not name:
            continue

        f: Dict[str, Any] = {
            "name": name,                         # key -> name
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


def seed_defaults(answers: Dict[str, Any], defaults: Dict[str, Any], overwrite_empty_only: bool = True) -> None:
    """
    Seed default values. answers IS st.session_state["form_data"].
    If overwrite_empty_only is True, only set when missing or empty/None/""
    """
    if not isinstance(defaults, dict):
        return
    for k, v in defaults.items():
        if not overwrite_empty_only:
            answers[k] = v
            continue
        curr = answers.get(k)
        if curr is None or curr == "":
            answers[k] = v


def _translated_label(field: Dict[str, Any], lang: Optional[Dict[str, str]]) -> str:
    # Prefer label_key -> lookup in lang map; fallback to literal 'label' -> fallback to name
    name = field.get("name") or ""
    if lang and field.get("label_key"):
        return lang.get(field["label_key"], field.get("label", name))
    return field.get("label", name)


def _coerce_number_input_defaults(field: Dict[str, Any]) -> Dict[str, Any]:
    # Provide sensible defaults for number_input to avoid Streamlit warnings
    kwargs: Dict[str, Any] = {}
    uses_float = _number_field_uses_float(field)
    if "min" in field:
        min_value = field["min"]
        kwargs["min_value"] = float(min_value) if uses_float and isinstance(min_value, int) else min_value
    if "max" in field:
        max_value = field["max"]
        kwargs["max_value"] = float(max_value) if uses_float and isinstance(max_value, int) else max_value
    if "step" in field:
        step_value = field["step"]
        kwargs["step"] = float(step_value) if uses_float and isinstance(step_value, int) else step_value
    else:
        kwargs["step"] = 0.01 if uses_float else 1
    if "format" in field:
        kwargs["format"] = field["format"]
    return kwargs


def _number_field_uses_float(field: Dict[str, Any]) -> bool:
    for key in ("min", "max", "step", "default"):
        value = field.get(key)
        if isinstance(value, float) and not value.is_integer():
            return True
    return False


def _coerce_number_value(field: Dict[str, Any], value: Any) -> Any:
    uses_float = _number_field_uses_float(field)

    if value is None or isinstance(value, bool):
        return None

    if isinstance(value, (int, float)):
        if uses_float:
            return float(value)
        return int(round(float(value)))

    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        match = NUMBER_VALUE_RE.search(stripped.replace(",", ""))
        if not match:
            return None
        try:
            parsed = float(match.group(0))
        except ValueError:
            return None
        if uses_float:
            return parsed
        return int(round(parsed))

    return None


def _get_default_value(field: Dict[str, Any]) -> Any:
    """Get appropriate default value for field type."""
    if "default" in field:
        return field["default"]
    
    ftype = field.get("type", "text")
    defaults = {
        "text": "",
        "textarea": "",
        "number": None,
        "multiselect": [],
        "checkbox": False,
        "radio": None,  # Will use placeholder/no default
        "time": None,
        "select": None,
        "file": None,
    }
    return defaults.get(ftype, "")


def _init_field_state(field: Dict[str, Any], answers: Dict[str, Any]) -> None:
    """Initialize field value if missing. answers IS session_state["form_data"]."""
    name = field.get("name")
    if not name:
        return
    
    # Only initialize if truly missing
    if name not in answers:
        answers[name] = _get_default_value(field)


def render_section(
    section: Dict[str, Any],
    answers: Dict[str, Any],
    *,
    lang: Optional[Dict[str, str]] = None,
    category: Optional[str] = None,
    make: Optional[str] = None,
    model: Optional[str] = None,
    show_required_errors: bool = False,
    visibility_state: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Render a section's fields with Streamlit widgets, updating the provided answers dict.

    - Uses visible_if with injected virtual fields (__category__, __make__, __model__)
    - Translates labels via lang map when label_key/title_key present
    - Supports types: text, textarea, radio, time (HH:MM), number, select, multiselect, checkbox, file
    - Displays a small red caption under required fields if show_required_errors=True and value is missing
    """
    fields = section.get("fields") or []
    visible_state = dict(visibility_state) if isinstance(visibility_state, dict) else answers
    for field in fields:
        name = field.get("name")
        if not name:
            continue

        # visible_if evaluation
        if not _is_visible(field, visible_state, category, make, model):
            continue

        ftype = field.get("type", "text")
        help_text = field.get("help")
        description_text = str(field.get("description") or "").strip()
        checkbox_label = str(field.get("checkbox_label") or "Complete").strip() or "Complete"
        # Make Streamlit widget keys unique across sections to avoid duplicate-key crashes
        sec_prefix = section.get("key") or section.get("title") or "sec"
        key = f"{sec_prefix}__{name}"
        label_text = _translated_label(field, lang)
        if field.get("required"):
            # Visual indicator only; Streamlit widgets do not enforce required at input
            label_to_show = f"{label_text} *"
        else:
            label_to_show = label_text

        # Render per type - Initialize, create widget, sync back
        if ftype == "text":
            _init_field_state(field, answers)
            st.text_input(label_to_show, value=answers[name], key=key, help=help_text)
            answers[name] = st.session_state[key]

        elif ftype == "textarea":
            _init_field_state(field, answers)
            st.text_area(label_to_show, value=answers[name], key=key, help=help_text)
            answers[name] = st.session_state[key]

        elif ftype == "radio":
            _init_field_state(field, answers)
            options = field.get("options", []) or []
            # Resolve default/index from answers
            default_index: Optional[int] = None
            if answers[name] is not None and answers[name] in options:
                default_index = options.index(answers[name])
            
            if options:
                st.radio(label_to_show, options=options, index=default_index,
                        horizontal=False, key=key, help=help_text)
            else:
                st.radio(label_to_show, options=[], key=key, help=help_text)
            answers[name] = st.session_state[key]

        elif ftype == "time":
            _init_field_state(field, answers)
            # Render time without seconds by using minute step granularity
            st.time_input(label_to_show, value=answers[name], step=60, key=key, help=help_text)
            answers[name] = st.session_state[key]

        elif ftype == "number":
            _init_field_state(field, answers)
            kwargs = _coerce_number_input_defaults(field)
            default_val = _coerce_number_value(field, answers[name])
            st.number_input(
                label_to_show,
                value=default_val,
                key=key,
                help=help_text,
                placeholder=field.get("placeholder"),
                **kwargs,
            )
            answers[name] = st.session_state[key]

        elif ftype == "select":
            _init_field_state(field, answers)
            options = field.get("options", []) or []
            current = answers[name]
            index = 0
            if current in options:
                index = options.index(current)
            st.selectbox(label_to_show, options=options, index=index if options else 0, 
                        key=key, help=help_text)
            answers[name] = st.session_state[key]

        elif ftype == "multiselect":
            _init_field_state(field, answers)
            options = field.get("options", []) or []
            default_vals = answers[name]
            if not isinstance(default_vals, list):
                default_vals = [default_vals] if default_vals is not None else []
            st.multiselect(label_to_show, options=options, default=default_vals, 
                          key=key, help=help_text)
            answers[name] = st.session_state[key]

        elif ftype == "checkbox":
            _init_field_state(field, answers)
            if description_text:
                st.markdown(f"**{label_to_show}**")
                st.markdown(description_text)
                st.checkbox(checkbox_label, value=bool(answers[name]), key=key, help=help_text)
            else:
                st.checkbox(label_to_show, value=bool(answers[name]), key=key, help=help_text)
            answers[name] = st.session_state[key]

        elif ftype == "file":
            _init_field_state(field, answers)
            allow_multi = bool(field.get("multiple", False))
            exts = field.get("allowed_ext")
            if isinstance(exts, list):
                # Streamlit expects extensions without dot, e.g., ["png", "jpg"]
                types = [e[1:] if isinstance(e, str) and e.startswith(
                    ".") else e for e in exts]
            else:
                types = None
            st.file_uploader(label_to_show, type=types, accept_multiple_files=allow_multi,
                           key=key, help=help_text)
            answers[name] = st.session_state[key]

        else:
            # Fallback to text
            _init_field_state(field, answers)
            st.text_input(label_to_show, value=answers[name], key=key, help=help_text)
            answers[name] = st.session_state[key]

        if isinstance(visible_state, dict):
            visible_state[name] = answers.get(name)

        # Inline required error
        if show_required_errors and field.get("required"):
            v = answers.get(name)
            is_empty = (v is None) or (isinstance(v, str) and v.strip() == "") or (
                isinstance(v, list) and len(v) == 0)
            if is_empty:
                logger.warning(f"Required field missing: {name}", extra={"field": name, "type": ftype})
                st.caption(":red[This field is required.]")
