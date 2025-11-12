from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List, Set

import streamlit as st

# Centralized field type allowlist
ALLOWED_FIELD_TYPES: Set[str] = {
    "text",
    "textarea",
    "radio",
    "time",
    "number",
    "select",
    "multiselect",
    "checkbox",
    "file",
}


DATA_DIR = os.path.join(os.getcwd(), "data")
VERSION_FP = os.path.join(DATA_DIR, "version.json")


def _read_json_safe(path: str, default=None):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default if default is not None else {}
    except Exception:
        return default if default is not None else {}


def get_data_version() -> str:
    """
    Returns a monotonically increasing version string used to bust Streamlit caches.
    If the version file doesn't exist, returns '0-0'.
    """
    v = _read_json_safe(VERSION_FP, {"v": 0, "ts": 0})
    return str(v.get("v", 0)) + "-" + str(v.get("ts", 0))


def _read_json(rel_path: str) -> Any:
    """Read a JSON file relative to the app root with a helpful error on failure."""
    abs_path = os.path.join(os.getcwd(), rel_path)
    if not os.path.exists(abs_path):
        st.error(f"Missing file: {rel_path}. Please add it to continue.")
        raise FileNotFoundError(abs_path)
    try:
        with open(abs_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        st.error(f"Failed to parse JSON file: {rel_path}\nError: {e}")
        raise


def _validate_unique_field_names(section: Dict[str, Any], where: str) -> None:
    names: Set[str] = set()
    for fld in section.get("fields", []):
        nm = fld.get("name")
        if not nm:
            st.error(
                f"Section '{section.get('key') or section.get('title')}' in {where} has a field without a 'name'.")
            raise ValueError("Field without name")
        if nm in names:
            st.error(
                f"Duplicate field name '{nm}' in section '{section.get('key') or section.get('title')}' ({where}).")
            raise ValueError("Duplicate field name")
        names.add(nm)
        ftype = fld.get("type", "text")
        if ftype not in ALLOWED_FIELD_TYPES:
            st.error(
                f"Field '{nm}' in section '{section.get('key')}' ({where}) has unsupported type '{ftype}'. Allowed types: {sorted(ALLOWED_FIELD_TYPES)}")
            raise ValueError("Unsupported field type")


def _collect_all_field_names(qdef: Dict[str, Any]) -> Set[str]:
    names: Set[str] = set()
    for sec in qdef.get("base_sections", []):
        for fld in sec.get("fields", []):
            if fld.get("name"):
                names.add(fld["name"])
    for cat, secs in qdef.get("category_packs", {}).items():
        for sec in secs or []:
            for fld in sec.get("fields", []):
                if fld.get("name"):
                    names.add(fld["name"])
    return names


def _each_visible_clause(cond: Any) -> List[Dict[str, Any]]:
    """Flatten visible_if to list of clauses for validation only."""
    if not cond:
        return []
    if isinstance(cond, dict):
        if "all" in cond:
            out: List[Dict[str, Any]] = []
            for sub in cond["all"]:
                out.extend(_each_visible_clause(sub))
            return out
        if "any" in cond:
            out = []
            for sub in cond["any"]:
                out.extend(_each_visible_clause(sub))
            return out
        # Clause
        return [cond]
    if isinstance(cond, list):
        out = []
        for item in cond:
            out.extend(_each_visible_clause(item))
        return out
    return []


def _validate_visible_if_references(qdef: Dict[str, Any]) -> None:
    known = _collect_all_field_names(qdef)
    virtuals = {"__category__", "__make__", "__model__"}
    for sec in qdef.get("base_sections", []):
        for fld in sec.get("fields", []):
            cond = fld.get("visible_if")
            for clause in _each_visible_clause(cond):
                ref = clause.get("field")
                if not ref:
                    st.error(
                        f"visible_if clause missing 'field' in section '{sec.get('key')}'.")
                    raise ValueError("visible_if missing field")
                if ref not in known and ref not in virtuals:
                    st.error(
                        f"visible_if references unknown field '{ref}' in section '{sec.get('key')}'.")
                    raise ValueError("visible_if bad reference")
    for cat, secs in qdef.get("category_packs", {}).items():
        for sec in secs or []:
            for fld in sec.get("fields", []):
                cond = fld.get("visible_if")
                for clause in _each_visible_clause(cond):
                    ref = clause.get("field")
                    if not ref:
                        st.error(
                            f"visible_if clause missing 'field' in category '{cat}', section '{sec.get('key')}'.")
                        raise ValueError("visible_if missing field")
                    if ref not in known and ref not in virtuals:
                        st.error(
                            f"visible_if references unknown field '{ref}' in category '{cat}', section '{sec.get('key')}'.")
                        raise ValueError("visible_if bad reference")


def _validate_insert_afters(qdef: Dict[str, Any]) -> None:
    """Ensure every insert_after.after references an existing field name (base or any category pack)."""
    all_names = _collect_all_field_names(qdef)
    overrides = qdef.get("overrides", {})
    for scope, ov in (overrides or {}).items():
        inserts = (ov or {}).get("insert_after", [])
        for ins in inserts or []:
            after = ins.get("after")
            fld = ins.get("field")
            if not after or not isinstance(fld, dict):
                st.error(
                    f"Override '{scope}' has invalid insert_after entry: {ins!r}")
                raise ValueError("Invalid insert_after")
            if after not in all_names:
                st.error(
                    f"Override '{scope}' tries to insert after unknown field '{after}'.")
                raise ValueError("insert_after target not found")


@st.cache_data(show_spinner=False)
def load_catalog(version: str) -> Dict[str, Any]:
    """
    Admin-first loader: only returns the new structure:
      { "makes": { make_key: {label, models{ model_key: {...} } } } }
    Tolerates missing or malformed data by returning an empty makes map.
    """
    raw = _read_json(os.path.join("data", "catalog.json"))
    makes = raw.get("makes") if isinstance(raw, dict) else {}
    if not isinstance(makes, dict):
        makes = {}
    # No legacy synthesis, no sidebar warnings
    return {"makes": makes}


@st.cache_data(show_spinner=False)
def load_questions(version: str) -> Dict[str, Any]:
    qdef = _read_json(os.path.join("data", "questions.json"))
    if "base_sections" not in qdef or "category_packs" not in qdef or "overrides" not in qdef:
        st.error(
            "Questions JSON must contain 'base_sections', 'category_packs', and 'overrides'.")
        raise ValueError("Questions schema error")

    for sec in qdef.get("base_sections", []):
        _validate_unique_field_names(sec, where="base_sections")

    for cat, secs in qdef.get("category_packs", {}).items():
        for sec in secs or []:
            _validate_unique_field_names(sec, where=f"category_packs['{cat}']")

    _validate_visible_if_references(qdef)
    _validate_insert_afters(qdef)

    return qdef


@st.cache_data(show_spinner=False)
def load_lang(locale: str = "en", version: str = "") -> Dict[str, str]:
    # Only 'en' exists now, but keep API flexible
    path = os.path.join("lang", f"{locale}.json")
    return _read_json(path)
