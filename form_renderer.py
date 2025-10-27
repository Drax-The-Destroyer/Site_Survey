"""
Form rendering utilities for the data-driven survey (Streamlit).

Exports:
- apply_overrides(form_def, make, model) -> list[Section]
- render_section(section, answers) -> None
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional
import copy
import streamlit as st


def _is_visible(field: Dict[str, Any], answers: Dict[str, Any]) -> bool:
    cond = field.get("visible_if")
    if not cond:
        return True
    dep_name = cond.get("field")
    expected = cond.get("equals")
    actual = answers.get(dep_name)
    return actual == expected


def apply_overrides(form_def: Dict[str, Any], make: str, model: str) -> List[Dict[str, Any]]:
    sections = copy.deepcopy(form_def.get("base_sections", []))
    overrides = form_def.get("model_overrides", {}).get((make, model), {})
    hide_fields = set(overrides.get("hide_fields", []))
    inserts = overrides.get("insert_after", [])

    if hide_fields:
        for sec in sections:
            sec["fields"] = [f for f in sec.get(
                "fields", []) if f.get("name") not in hide_fields]

    for ins in inserts:
        after_name = ins.get("after")
        new_field = ins.get("field")
        if not after_name or not isinstance(new_field, dict):
            continue
        inserted = False
        for sec in sections:
            fields = sec.get("fields", [])
            for idx, fld in enumerate(fields):
                if fld.get("name") == after_name:
                    fields.insert(idx + 1, new_field)
                    inserted = True
                    break
            if inserted:
                break
        if not inserted and sections:
            sections[-1].setdefault("fields", []).append(new_field)

    return sections


def render_section(section: Dict[str, Any], answers: Dict[str, Any]) -> None:
    for field in section.get("fields", []):
        name = field.get("name")
        label = field.get("label", name or "")
        ftype = field.get("type", "text")
        help_text = field.get("help")
        key = name

        if not name:
            continue
        if not _is_visible(field, answers):
            continue

        if ftype == "text":
            val = st.text_input(label, value=answers.get(
                name, ""), help=help_text, key=key)
            answers[name] = val

        elif ftype == "textarea":
            val = st.text_area(label, value=answers.get(
                name, ""), help=help_text, key=key)
            answers[name] = val

        elif ftype == "radio":
            options = field.get("options", [])
            if options:
                default_index: Optional[int] = None
                if name in answers and answers[name] in options:
                    default_index = options.index(answers[name])
                elif "default" in field and field["default"] in options:
                    default_index = options.index(field["default"])
                else:
                    default_index = 0
                val = st.radio(label, options=options, index=default_index,
                               horizontal=False, help=help_text, key=key)
            else:
                val = st.radio(label, options=[], help=help_text, key=key)
            answers[name] = val

        elif ftype == "time":
            val = st.time_input(label, help=help_text, key=key)
            answers[name] = val

        else:
            val = st.text_input(label, value=answers.get(
                name, ""), help=help_text, key=key)
            answers[name] = val
