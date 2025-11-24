from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List, Set, Iterable

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

# --- Media / assets indexing ---

MEDIA_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg"}
MEDIA_BROCHURE_EXTENSIONS = {".pdf"}

# index.json lives under data/media/index.json
MEDIA_INDEX_FP = os.path.join(DATA_DIR, "media", "index.json")

# Where we scan for assets. Order matters; later entries override earlier ones on filename collisions.
MEDIA_SEARCH_DIRS: Iterable[str] = (
    "assets",                     # project_root/assets/...
    os.path.join("data", "media") # existing media folder
)


def _read_json_safe(path: str, default=None):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default if default is not None else {}
    except Exception:
        return default if default is not None else {}


def _write_json_safe(path: str, data: Any) -> None:
    """Write JSON with basic error handling."""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        st.error(f"Failed to write JSON file: {path}\nError: {e}")
        raise


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
                f"Field '{nm}' in section '{section.get('key')}'...d type '{ftype}'. Allowed types: {sorted(ALLOWED_FIELD_TYPES)}")
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
    # Overrides can also introduce fields via insert_after
    overrides = qdef.get("overrides", {})
    for scope, ov in (overrides or {}).items():
        inserts = (ov or {}).get("insert_after", [])
        for ins in inserts or []:
            fld = ins.get("field")
            if isinstance(fld, dict) and fld.get("name"):
                names.add(fld["name"])
    return names


def _each_visible_clause(cond: Any) -> List[Dict[str, Any]]:
    """
    visible_if can be:
      - None
      - {field, op, value}
      - {"and"/"or": [ ... ]}
      - [{"field": ...}, {"field": ...}, ...]
    Flatten to a list of simple {field, op, value}-like clauses.
    """
    if not cond:
        return []
    if isinstance(cond, dict):
        if "field" in cond:
            return [cond]
        # compound
        for key in ("and", "or"):
            if key in cond and isinstance(cond[key], list):
                out = []
                for item in cond[key]:
                    out.extend(_each_visible_clause(item))
                return out
        # unknown dict shape: treat as single clause just in case
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

    # Base sections
    for sec in qdef.get("base_sections", []):
        if not isinstance(sec, dict):
            continue
        for fld in sec.get("fields", []):
            cond = fld.get("visible_if")
            for clause in _each_visible_clause(cond):
                # Some legacy / compound clauses may not target a single field; skip those
                ref = clause.get("field")
                if not ref:
                    continue
                if ref not in known and ref not in virtuals:
                    st.error(
                        f"visible_if references unknown field '{ref}' in section '{sec.get('key')}'."
                    )
                    raise ValueError("visible_if bad reference")

    # Category packs
    for cat, secs in qdef.get("category_packs", {}).items():
        if secs is None:
            continue
        if not isinstance(secs, list):
            st.error(
                f"questions.category_packs['{cat}'] must be a list or null, "
                f"got {type(secs).__name__}."
            )
            raise ValueError("category_packs schema error")

        for sec in secs or []:
            if not isinstance(sec, dict):
                st.error(
                    f"questions.category_packs['{cat}'] entries must be objects with 'fields', "
                    f"got {type(sec).__name__}: {sec!r}"
                )
                raise ValueError("category_packs section not object")

            for fld in sec.get("fields", []):
                cond = fld.get("visible_if")
                for clause in _each_visible_clause(cond):
                    ref = clause.get("field")
                    if not ref:
                        # Same deal: clauses without 'field' are ignored for this validation
                        continue
                    if ref not in known and ref not in virtuals:
                        st.error(
                            f"visible_if references unknown field '{ref}' in category '{cat}', "
                            f"section '{sec.get('key')}'."
                        )
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



# ---------------- Media index (images / brochures) ----------------


def _scan_media_dirs() -> Dict[str, Dict[str, Any]]:
    """
    Walk MEDIA_SEARCH_DIRS and build the raw media index dict:
      { "images": {filename: {path, ts}}, "brochures": {...} }
    """
    base_dir = os.getcwd()
    images: Dict[str, Dict[str, Any]] = {}
    brochures: Dict[str, Dict[str, Any]] = {}

    for rel_dir in MEDIA_SEARCH_DIRS:
        root = os.path.join(base_dir, rel_dir)
        if not os.path.exists(root):
            continue

        for dirpath, _dirnames, filenames in os.walk(root):
            for filename in filenames:
                ext = os.path.splitext(filename)[1].lower()
                full_path = os.path.join(dirpath, filename)
                try:
                    ts = os.path.getmtime(full_path)
                except OSError:
                    ts = 0.0

                entry = {"path": full_path, "ts": ts}

                if ext in MEDIA_IMAGE_EXTENSIONS:
                    images[filename] = entry
                elif ext in MEDIA_BROCHURE_EXTENSIONS:
                    brochures[filename] = entry

    return {"images": images, "brochures": brochures}


def rebuild_media_index() -> Dict[str, Dict[str, Any]]:
    """
    Re-scan assets and data/media, write data/media/index.json,
    and return the in-memory dict.

    This is the single source of truth for index.json.
    """
    media_data = _scan_media_dirs()
    _write_json_safe(MEDIA_INDEX_FP, media_data)
    return media_data


def load_media_index() -> Dict[str, Dict[str, Any]]:
    """
    Public API for the rest of the app.

    For simplicity (and to guarantee new assets show up automatically),
    we always rebuild on call. If this ever becomes a bottleneck,
    we can add caching/versioning later.
    """
    return rebuild_media_index()


@st.cache_data(show_spinner=False)
def load_catalog(version: str) -> Dict[str, Any]:
    """
    Admin-first loader: only returns the new structure:
      { "makes": { make_key: {label, models{ model_key: {...} } } } }
    Tolerates missing or malformed data by returning an empty makes map.
    """
    raw = _read_json(os.path.join("data", "catalog.json"))
    if not isinstance(raw, dict):
        st.error("data/catalog.json is not a JSON object.")
        return {"makes": {}}

    makes = raw.get("makes", {})
    if not isinstance(makes, dict):
        st.error("data/catalog.json['makes'] must be an object.")
        makes = {}

    # Basic sanity checks
    for make_key, make_obj in makes.items():
        if not isinstance(make_obj, dict):
            st.error(f"Make '{make_key}' must be an object.")
            continue
        make_obj.setdefault("label", make_key)
        models = make_obj.get("models", {})
        if not isinstance(models, dict):
            st.error(f"Make '{make_key}'.models must be an object.")
            models = {}
        for model_key, model_obj in models.items():
            if not isinstance(model_obj, dict):
                st.error(f"Model '{make_key}/{model_key}' must be an object.")
                continue
            model_obj.setdefault("label", model_key)
            # Optional: validate expected keys like category, dimensions, media, etc.

    return {"makes": makes}


@st.cache_data(show_spinner=False)
def load_questions(version: str) -> Dict[str, Any]:
    qdef = _read_json(os.path.join("data", "questions.json"))
    if "base_sections" not in qdef or "category_packs" not in qdef or "overrides" not in qdef:
        st.error(
            "Questions JSON must contain 'base_sections', 'category_packs', and 'overrides'."
        )
        raise ValueError("Questions schema error")

    # Validate base sections
    for sec in qdef.get("base_sections", []):
        if not isinstance(sec, dict):
            st.error("Each entry in questions.base_sections must be an object.")
            raise ValueError("base_sections entry not object")
        _validate_unique_field_names(sec, where="base_sections")

    # Validate category packs
    for cat, secs in qdef.get("category_packs", {}).items():
        if secs is None:
            continue
        if not isinstance(secs, list):
            st.error(
                f"questions.category_packs['{cat}'] must be a list (or null). "
                f"Got {type(secs).__name__}."
            )
            raise ValueError("category_packs schema error")

        for sec in secs or []:
            if not isinstance(sec, dict):
                st.error(
                    f"questions.category_packs['{cat}'] entries must be section objects "
                    f"with 'fields', got {type(sec).__name__}: {sec!r}"
                )
                raise ValueError("category_packs section not object")
            _validate_unique_field_names(sec, where=f"category_packs['{cat}']")

    _validate_visible_if_references(qdef)
    _validate_insert_afters(qdef)

    return qdef



@st.cache_data(show_spinner=False)
def load_lang(locale: str = "en", version: str = "") -> Dict[str, str]:
    # Only 'en' exists now, but keep API flexible
    path = os.path.join("lang", f"{locale}.json")
    return _read_json(path)
