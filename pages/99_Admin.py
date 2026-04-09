# import streamlit as st

# st.set_page_config(page_title="Admin", layout="centered")

# st.title("🛠️ Admin")
# st.info("Admin UI coming soon")

# st.markdown(
#     """
# This page is a placeholder for future administrative features, such as:

# - Managing catalog (categories, makes, models, hero images, dimensions)
# - Editing question packs and overrides
# - Localization management (EN/FR)
# - Photo rules configuration

# For now, please edit JSON files under `data/` and `lang/` directly.
# """
# )


# File: pages/99_Admin.py
"""
Admin Console for the Site Survey Web App (Streamlit)

Features
- Catalog Manager (Makes ➜ Models ➜ Variants)
- Categories & Sections (Smart Safe / Recycler / Dispenser / Note Sorter, etc.)
- Question Sets Builder (per Category + per Section)
- Media Library (images, brochures; dimension extraction helper)
- Imports (CSV / JSON normalizer to internal schema)
- Users & Roles (simple local file edition; swap to DB later)
- System Settings (branding, PDF header/footer, paths)
- Maintenance (rebuild caches, validate cross-refs)

Data backend: JSON files under ./data/ (safe to migrate to DB later)

Dependencies: streamlit>=1.30, pandas, pydantic (optional – hard fallback provided)
"""
from __future__ import annotations
import os
import io
import re
import json
import time
import shutil
import zipfile
from dataclasses import dataclass, asdict
from typing import Dict, List, Any, Optional, Tuple

import pandas as pd
import streamlit as st
import qrcode
from app.ui import wide_button
from utils.database import SurveyDatabase
from config import Config

from data_loader import (
    load_catalog,
    load_questions,
    load_lang,
    get_data_version,
    load_media_index,   # NEW
)
from question_profiles import (
    build_sections_for_profile,
    ensure_category_profile_data,
    ensure_question_profile_schema,
    get_default_profile_id,
    get_profiles_for_category,
    get_question_bank_sections,
    normalize_category_key,
    question_id,
    slugify as profile_slugify,
)


# Simple password
def _get_admin_password(default="CashTech"):
    return os.getenv("ADMIN_PASSWORD", default)

PASSWORD = _get_admin_password()


def require_admin_password():
    if st.session_state.get("admin_ok"):
        if st.sidebar.button("Log out"):
            st.session_state.pop("admin_ok", None)
            st.rerun()
        return
    st.title("Admin Sign In")
    pwd = st.text_input("Password", type="password", key="admin_pwd")
    if st.button("Sign in", type="primary"):
        if pwd == PASSWORD:
            st.session_state["admin_ok"] = True
            st.rerun()
        else:
            st.error("Invalid password")
    st.stop()


require_admin_password()


# -----------------------------
# Paths & Utilities
# -----------------------------
DATA_DIR = os.path.join(os.getcwd(), "data")
MEDIA_DIR = os.path.join(DATA_DIR, "media")
CATALOG_FP = os.path.join(DATA_DIR, "catalog.json")
CATEGORIES_FP = os.path.join(DATA_DIR, "categories.json")
QUESTIONS_FP = os.path.join(DATA_DIR, "questions.json")
SETTINGS_FP = os.path.join(DATA_DIR, "settings.json")
CUSTOMERS_FP = os.path.join(DATA_DIR, "customers.json")
MEDIA_INDEX_FP = os.path.join(MEDIA_DIR, "index.json")
VERSION_FP = os.path.join(DATA_DIR, "version.json")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(MEDIA_DIR, exist_ok=True)


def resolve_image_path(filename: str) -> Optional[str]:
    """
    Try to locate an image by filename in data/media, assets, or common
    cloud mount paths. Returns an absolute path or None.
    """
    if not filename:
        return None
    base = os.path.basename(filename)

    candidates = [
        os.path.join(MEDIA_DIR, base),                          # data/media (Admin uploads)
        os.path.join("assets", base),                           # local assets folder
        os.path.join("/mount/src/site_survey/data/media", base),  # Streamlit Cloud paths
        os.path.join("/mount/src/site_survey/assets", base),
        os.path.join("/mount/src/data/media", base),
    ]

    for p in candidates:
        if os.path.exists(p):
            return p
    return None


# ---- File I/O helpers (atomic-ish writes) ----


def _read_json(path: str, default: Any) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except json.JSONDecodeError:
        st.warning(
            f"{os.path.basename(path)} had invalid JSON. Loading defaults.")
        return default


def _write_json(path: str, data: Any) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def bump_data_version() -> dict:
    """Increment data/version.json to bust all @st.cache_data loaders that depend on version."""
    cur = _read_json(VERSION_FP, {"v": 0, "ts": 0})
    cur["v"] = int(cur.get("v", 0)) + 1
    cur["ts"] = int(time.time())
    _write_json(VERSION_FP, cur)
    try:
        st.cache_data.clear()
    except Exception:
        pass
    return cur


def _mtime(path: str) -> float:
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0

# ---- Slug & validation helpers ----


def slugify(text: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "_", text.strip()).strip("_")
    return s.lower()


def model_q_id(make_key: str, model_key: str) -> str:
    """
    Stable ID for model-specific question overrides.
    Stored under questions['overrides']['by_model'][model_q_id].
    """
    return f"{make_key}:{model_key}"


def ensure_unique(seq: List[str]) -> Tuple[bool, Optional[str]]:
    seen = set()
    for x in seq:
        if x in seen:
            return False, x
        seen.add(x)
    return True, None


def _as_str(x) -> str:
    if x is None:
        return ""
    try:
        return str(x).strip()
    except Exception:
        return ""


def _default_media() -> dict:
    return {
        "hero_image": "",
        "gallery": [],
        "brochures": [],
    }


def _normalize_media(media_in: Any) -> dict:
    media = dict(media_in) if isinstance(media_in, dict) else {}
    normalized = _default_media()
    normalized["hero_image"] = _as_str(media.get("hero_image", ""))
    normalized["gallery"] = [str(item).strip() for item in media.get("gallery", []) or [] if str(item).strip()]
    normalized["brochures"] = [str(item).strip() for item in media.get("brochures", []) or [] if str(item).strip()]
    return normalized


def _normalize_dimensions(dims_in: Any) -> dict:
    dims_in = dims_in if isinstance(dims_in, dict) else {}
    return {
        "weight": _as_str(dims_in.get("weight", "")),
        "width": _as_str(dims_in.get("width", "")),
        "depth": _as_str(dims_in.get("depth", "")),
        "height": _as_str(dims_in.get("height", "")),
    }


def _merge_model_record(existing: Any, *, label: str, category: str, dimensions: dict) -> dict:
    model_obj = dict(existing) if isinstance(existing, dict) else {}
    model_obj["label"] = label
    model_obj["category"] = category
    model_obj["dimensions"] = _normalize_dimensions(dimensions)
    model_obj["media"] = _normalize_media(model_obj.get("media"))
    return model_obj


def _coerce_models_map(models_in) -> dict:
    """
    Accepts list|dict|None and returns dict: {model_key: {label, category, dimensions{...}}}
    """
    if isinstance(models_in, dict):
        out = {}
        for model_key, model_obj in models_in.items():
            if not isinstance(model_obj, dict):
                out[model_key] = _merge_model_record({}, label=_as_str(model_key), category="", dimensions={})
                continue
            out[model_key] = _merge_model_record(
                model_obj,
                label=_as_str(model_obj.get("label") or model_key),
                category=_as_str(model_obj.get("category", "")),
                dimensions=model_obj.get("dimensions"),
            )
        return out
    out = {}
    if isinstance(models_in, list):
        for item in models_in:
            if isinstance(item, dict):
                label = _as_str(item.get("label") or item.get(
                    "name") or item.get("model") or "model")
                key = slugify(item.get("key") or label)
                category = _as_str(item.get("category")
                                   or item.get("cat") or "")
                out[key] = _merge_model_record(
                    item,
                    label=label,
                    category=category,
                    dimensions=item.get("dimensions"),
                )
            elif isinstance(item, str):
                key = slugify(item)
                out[key] = _merge_model_record({}, label=item, category="", dimensions={})
    # anything else → empty
    return out


def _coerce_makes_map(makes_in) -> dict:
    """
    Accepts list|dict|None and returns dict: {make_key: {label, models:{...}}}
    """
    if isinstance(makes_in, dict):
        # ensure nested models are dicts
        for mk, mv in list(makes_in.items()):
            if not isinstance(mv, dict):
                makes_in[mk] = {"label": _as_str(mv), "models": {}}
            else:
                mv["label"] = _as_str(mv.get("label") or mk)
                mv["models"] = _coerce_models_map(mv.get("models"))
        return makes_in

    out = {}
    if isinstance(makes_in, list):
        for item in makes_in:
            if isinstance(item, dict):
                label = _as_str(item.get("label") or item.get(
                    "name") or item.get("make") or "make")
                key = slugify(item.get("key") or label)
                models = _coerce_models_map(item.get("models"))
                out[key] = {"label": label, "models": models}
            elif isinstance(item, str):
                key = slugify(item)
                out[key] = {"label": item, "models": {}}
    return out


def _get_model_ref(catalog: dict, make_key: str, model_key: str) -> dict:
    return (
        catalog
        .setdefault("makes", {})
        .setdefault(make_key, {"label": make_key, "models": {}})
        .setdefault("models", {})
        .setdefault(model_key, _merge_model_record({}, label=model_key, category="", dimensions={}))
    )


def _ensure_media(model_obj: dict) -> dict:
    media = _normalize_media(model_obj.get("media"))
    model_obj["media"] = media
    return media


def _cat_label_from_key(cat_key: str, categories_map: dict) -> str:
    if not cat_key:
        return ""
    if cat_key in categories_map:
        return categories_map[cat_key].get("label", cat_key)
    # fallback: snake_case -> Title Case
    return cat_key.replace("_", " ").title()


def rebuild_derived_catalog_structures(catalog: dict, categories: dict) -> dict:
    """
    Admin-only catalog normalizer; legacy fields are no longer written.
    """
    return catalog


# -----------------------------
# Default structures
# -----------------------------
DEFAULT_CATALOG = {
    "makes": {
        # "TiDel": {"models": {"Series 4": {"category": "smart_safe", "dimensions": {"weight": "65 kg / 143 lb"}}}}
    }
}

DEFAULT_CATEGORIES = {
    "smart_safe": {"label": "Smart Safe", "sections": ["Delivery", "Installation", "Power", "Networking"]},
    "recycler": {"label": "Recycler", "sections": ["Delivery", "Installation", "Power", "Networking"]},
    "dispenser": {"label": "Dispenser", "sections": ["Delivery", "Installation", "Power", "Networking"]},
    "note_sorter": {"label": "Note Sorter", "sections": ["Delivery", "Installation", "Power", "Networking"]},
}

DEFAULT_QUESTIONS = {
    # by category, then section; each item: { key, label, type, required, options?, visible_if? }
    # e.g., "smart_safe": {"Delivery": [{"key":"dock_height","label":"Dock height (in)","type":"number","required":False}]}
}

DEFAULT_USERS = {
    "roles": ["admin", "editor", "viewer"],
    "users": [
        {"email": "admin@example.com", "name": "Admin",
            "role": "admin", "active": True}
    ],
}

DEFAULT_SETTINGS = {
    "branding": {
        "company_name": "CashTech Currency Products",
        "pdf_header": "Site Survey Report",
        "pdf_footer": "Confidential",
    },
    "media": {
        "hero_image": "",
    },
}

DEFAULT_MEDIA_INDEX = {"images": {}, "brochures": {}}

# -----------------------------
# Session boot
# -----------------------------
if "_admin_loaded_at" not in st.session_state:
    st.session_state._admin_loaded_at = time.time()

st.title("🛠️ Admin Console")
st.caption("Manage catalogs, questions, media, users, and system settings.")

# Load data
catalog = _read_json(CATALOG_FP, DEFAULT_CATALOG)
categories = _read_json(CATEGORIES_FP, DEFAULT_CATEGORIES)
questions = _read_json(QUESTIONS_FP, DEFAULT_QUESTIONS)
settings = _read_json(SETTINGS_FP, DEFAULT_SETTINGS)
media_index = _read_json(MEDIA_INDEX_FP, DEFAULT_MEDIA_INDEX)
questions = ensure_question_profile_schema(questions)
lang_map = load_lang("en", get_data_version())

# --- Normalize catalog shape and ensure every model has stable media structure ---
catalog_before_normalize = json.dumps(catalog, sort_keys=True)
catalog["makes"] = _coerce_makes_map(catalog.get("makes", {}))
catalog = rebuild_derived_catalog_structures(catalog, categories)
if json.dumps(catalog, sort_keys=True) != catalog_before_normalize:
    _write_json(CATALOG_FP, catalog)

# -----------------------------
col_a, col_b, col_c, col_d = st.columns([1, 1, 1, 1])
with col_a:
    st.metric("Makes", len(catalog.get("makes", {})))
with col_b:
    st.metric("Categories", len(categories))
with col_c:
    st.metric("Questions (cats)", len(questions))
with col_d:
    st.metric("Media Items", len(media_index.get("images", {})) +
              len(media_index.get("brochures", {})))

# -----------------------------
# Helper: kg ↔ lb, mm ↔ in formatters
# -----------------------------
KG_PER_LB = 0.45359237
IN_PER_MM = 0.0393700787


def fmt_weight(kg: Optional[float], lb: Optional[float]) -> str:
    if kg is not None and lb is None:
        lb = round(kg / KG_PER_LB)
    if lb is not None and kg is None:
        kg = round(lb * KG_PER_LB)
    if kg is None and lb is None:
        return ""
    return f"{int(kg)} kg / {int(lb)} lb"


def fmt_length(mm: Optional[float], inches: Optional[float]) -> str:
    if mm is not None and inches is None:
        inches = round(mm * IN_PER_MM, 1)
    if inches is not None and mm is None:
        mm = round(inches / IN_PER_MM)
    if mm is None and inches is None:
        return ""
    # keep 1 decimal for inches, int mm
    return f"{int(mm)} mm / {inches:.1f} in"


# Parse helpers from free text like "55 kg" or "31.5 in"
WEIGHT_RE = re.compile(
    r"(?P<num>\d+(?:\.\d+)?)\s*(?P<u>kg|kilograms|lb|pounds?)\b", re.I)
LENGTH_RE = re.compile(
    r"(?P<num>\d+(?:\.\d+)?)\s*(?P<u>mm|millimeters?|cm|in|inches?)\b", re.I)


def parse_weight(text: str) -> Tuple[Optional[float], Optional[float]]:
    m = WEIGHT_RE.search(text or "")
    if not m:
        return None, None
    val = float(m.group("num"))
    u = m.group("u").lower()
    if u.startswith("kg"):
        return val, None
    return None, val


def parse_length(text: str) -> Tuple[Optional[float], Optional[float]]:
    m = LENGTH_RE.search(text or "")
    if not m:
        return None, None
    val = float(m.group("num"))
    u = m.group("u").lower()
    if u.startswith("mm"):
        return val, None
    if u.startswith("cm"):
        return val * 10.0, None
    return None, val


# -----------------------------
# TABS
# -----------------------------
# Compatibility helper for Streamlit width API differences (no use_container_width to avoid warnings)
def editor_width_kwargs(width=None):
    """
    Normalizes width args for st.data_editor / st.dataframe across Streamlit versions
    WITHOUT using `use_container_width` (avoids deprecation warnings).
    - 'stretch'  -> width=2000 (large int; Streamlit caps to container)
    - 'content'  -> omit width (component decides)
    - int/float  -> width=int(value)
    - None       -> omit width
    """
    if isinstance(width, str):
        w = width.lower().strip()
        if w == "stretch":
            return {"width": 2000}
        if w == "content":
            return {}
        return {}
    if isinstance(width, (int, float)):
        return {"width": int(width)}
    return {}


def persist_questions_config(updated_questions: Dict[str, Any]) -> None:
    normalized = ensure_question_profile_schema(updated_questions)
    _write_json(QUESTIONS_FP, normalized)
    bump_data_version()


def section_label(section: Dict[str, Any]) -> str:
    title_key = str(section.get("title_key") or "").strip()
    if title_key:
        translated = str(lang_map.get(title_key) or "").strip()
        if translated:
            return translated
    title = str(section.get("title") or "").strip()
    if title:
        return title
    key = str(section.get("key") or "").strip()
    return key.replace("_", " ").title() if key else "Section"


def question_text(question: Dict[str, Any]) -> str:
    label = str(question.get("label") or "").strip()
    if label:
        return label
    label_key = str(question.get("label_key") or "").strip()
    if label_key:
        translated = str(lang_map.get(label_key) or "").strip()
        if translated:
            return translated
    qid = question_id(question)
    return qid or "Question"


def question_bank_row(
    question: Dict[str, Any],
    profile_question_map: Dict[str, Dict[str, Any]],
    default_order: int,
) -> Dict[str, Any]:
    qid = question_id(question)
    profile_item = profile_question_map.get(qid, {})
    include = qid in profile_question_map
    effective_required = bool(profile_item.get("required", question.get("required", False))) if include else bool(question.get("required", False))
    order_value = profile_item.get("order", default_order)
    return {
        "Include": include,
        "Required": effective_required,
        "Order": int(order_value),
        "Question ID": qid,
        "Question": question_text(question),
        "Type": str(question.get("type", "text")),
        "Default Required": bool(question.get("required", False)),
        "Options (comma)": ", ".join(question.get("options", []))
        if isinstance(question.get("options"), list)
        else "",
        "visible_if (JSON)": json.dumps(question.get("visible_if"))
        if isinstance(question.get("visible_if"), (dict, list))
        else "",
    }


def checkbox_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    try:
        if pd.isna(value):
            return False
    except Exception:
        pass
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(value)


def build_profile_question_items(
    rows: List[Dict[str, Any]],
    bank_required_by_id: Dict[str, bool],
) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    used_ids = set()
    next_order = 1
    for row in rows:
        qid = str(row.get("Question ID", "")).strip()
        include = checkbox_value(row.get("Include", False))
        if not qid or not include or qid in used_ids:
            continue
        used_ids.add(qid)
        try:
            order_value = int(row.get("Order", next_order))
        except Exception:
            order_value = next_order
        item: Dict[str, Any] = {
            "question_id": qid,
            "order": order_value,
        }
        effective_required = checkbox_value(row.get("Required", False))
        default_required = bool(bank_required_by_id.get(qid, False))
        if effective_required != default_required:
            item["required"] = effective_required
        items.append(item)
        next_order += 1
    return sorted(items, key=lambda item: (item.get("order", 0), item.get("question_id", "")))


def load_customers_config() -> List[Dict[str, Any]]:
    payload = _read_json(CUSTOMERS_FP, {"customers": []})
    customers = payload.get("customers", []) if isinstance(payload, dict) else []
    return customers if isinstance(customers, list) else []


def save_customers_config(customers: List[Dict[str, Any]]) -> None:
    _write_json(CUSTOMERS_FP, {"customers": customers})


def find_make_key_by_label(label: Optional[str]) -> Optional[str]:
    wanted = _as_str(label).lower()
    if not wanted:
        return None
    for make_key, make_obj in (catalog.get("makes", {}) or {}).items():
        if _as_str((make_obj or {}).get("label", make_key)).lower() == wanted:
            return make_key
    return None


def find_model_key_by_label(make_key: Optional[str], label: Optional[str]) -> Optional[str]:
    wanted = _as_str(label).lower()
    if not make_key or not wanted:
        return None
    models = ((catalog.get("makes", {}) or {}).get(make_key, {}) or {}).get("models", {}) or {}
    for model_key, model_obj in models.items():
        if _as_str((model_obj or {}).get("label", model_key)).lower() == wanted:
            return model_key
    return None


def override_question_row(question: Dict[str, Any], default_order: int) -> Dict[str, Any]:
    qid = question_id(question)
    return {
        "Include": True,
        "Required": bool(question.get("required", False)),
        "Order": int(question.get("order", default_order)),
        "Question ID": qid,
        "Question": question_text(question),
        "Type": str(question.get("type", "text")),
        "Default Required": bool(question.get("required", False)),
        "Options (comma)": ", ".join(question.get("options", [])) if isinstance(question.get("options"), list) else "",
        "visible_if (JSON)": json.dumps(question.get("visible_if")) if isinstance(question.get("visible_if"), (dict, list)) else "",
    }


def build_override_editor_rows(
    base_questions: List[Dict[str, Any]],
    override_questions: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    override_map = {
        question_id(question): dict(question)
        for question in (override_questions or [])
        if isinstance(question, dict) and question_id(question)
    }

    for default_order, base_question in enumerate(base_questions or [], start=1):
        qid = question_id(base_question)
        if not qid:
            continue

        override_question = override_map.pop(qid, None)
        effective_question = dict(base_question)
        include = True
        if override_question:
            include = checkbox_value(override_question.get("include", True))
            for key, value in override_question.items():
                if key == "include":
                    continue
                effective_question[key] = value

        row = override_question_row(effective_question, default_order=default_order)
        row["Include"] = include
        row["Default Required"] = bool(base_question.get("required", False))
        rows.append(row)

    extra_questions = sorted(
        (
            question
            for question in override_map.values()
            if checkbox_value(question.get("include", True))
        ),
        key=lambda item: (
            int(item.get("order", 10000)) if str(item.get("order", "")).strip() else 10000,
            question_id(item),
        ),
    )
    next_order = len(rows) + 1
    for question in extra_questions:
        rows.append(override_question_row(question, default_order=next_order))
        next_order += 1

    return rows


def build_override_questions(
    rows: List[Dict[str, Any]],
    *,
    base_question_map: Optional[Dict[str, Dict[str, Any]]] = None,
    base_order_by_id: Optional[Dict[str, int]] = None,
) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    used_ids = set()
    next_order = 1
    for row in rows:
        question_label = str(row.get("Question", "") or "").strip()
        qid = str(row.get("Question ID", "") or "").strip() or profile_slugify(question_label)
        include = checkbox_value(row.get("Include", False))
        if not qid or qid in used_ids:
            continue
        used_ids.add(qid)
        try:
            order_value = int(row.get("Order", next_order))
        except Exception:
            order_value = next_order
        options_raw = str(row.get("Options (comma)", "") or "").strip()
        visible_if_raw = str(row.get("visible_if (JSON)", "") or "").strip()
        row_options = [option.strip() for option in options_raw.split(",") if option.strip()] if options_raw else []
        row_visible_if = json.loads(visible_if_raw) if visible_if_raw else None
        row_required = checkbox_value(row.get("Required", False))
        row_type = str(row.get("Type", "text") or "text")

        base_question = (base_question_map or {}).get(qid)
        if base_question:
            if not include:
                items.append({"id": qid, "name": qid, "include": False})
                next_order += 1
                continue

            question: Dict[str, Any] = {"id": qid, "name": qid}
            changed = False
            default_order = int((base_order_by_id or {}).get(qid, next_order))
            if order_value != default_order:
                question["order"] = order_value
                changed = True

            effective_label = question_label or qid
            if effective_label != question_text(base_question):
                question["label"] = effective_label
                changed = True

            if row_type != str(base_question.get("type", "text") or "text"):
                question["type"] = row_type
                changed = True

            if row_required != bool(base_question.get("required", False)):
                question["required"] = row_required
                changed = True

            base_options = (
                [str(option).strip() for option in base_question.get("options", []) if str(option).strip()]
                if isinstance(base_question.get("options"), list)
                else []
            )
            if row_options != base_options:
                question["options"] = row_options
                changed = True

            base_visible_if = base_question.get("visible_if") if isinstance(base_question.get("visible_if"), (dict, list)) else None
            if visible_if_raw:
                if row_visible_if != base_visible_if:
                    question["visible_if"] = row_visible_if
                    changed = True
            elif base_visible_if is not None:
                question["visible_if"] = None
                changed = True

            if changed:
                items.append(question)
            next_order += 1
            continue

        if not include:
            continue

        question = {
            "id": qid,
            "name": qid,
            "label": question_label or qid,
            "type": row_type,
            "required": row_required,
            "order": order_value,
        }
        if row_options:
            question["options"] = row_options
        if visible_if_raw:
            question["visible_if"] = row_visible_if
        items.append(question)
        next_order += 1
    return sorted(items, key=lambda item: (item.get("order", 0), item.get("id", "")))

TAB = st.tabs([
    "Catalog",
    "Customers",
    "Categories & Sections",
    "Question Sets",
    "Media Library",
    "Imports",
    "Settings",
    "Share Links",
    "Maintenance",
])

# -----------------------------
# Catalog Tab
# -----------------------------
with TAB[0]:
    st.subheader("Catalog Manager")
    st.write(
        "Makes → Models → (optional) Variants. Attach category and dimensions per model.")

    makes: Dict[str, Any] = _coerce_makes_map(catalog.get("makes", {}))
    catalog["makes"] = makes  # keep in-memory consistent

    col1, col2 = st.columns([1, 2], vertical_alignment="top")
    with col1:
        st.markdown("**Makes**")
        make_new = st.text_input("Add new make", key="make_new")
        if wide_button("➕ Add Make", type="primary"):
            if not make_new.strip():
                st.warning("Enter a make name.")
            else:
                sk = slugify(make_new)
                if sk in makes:
                    st.error("Make already exists.")
                else:
                    makes[sk] = {"label": make_new.strip(), "models": {}}
                    catalog = rebuild_derived_catalog_structures(
                        catalog, categories)
                    _write_json(CATALOG_FP, catalog)
                    bump_data_version()
                    st.success(f"Added make: {make_new}")
                    st.rerun()

        if makes:
            make_keys = [k for k in makes.keys()]
            make_labels = [makes[k].get("label", k) for k in make_keys]
            idx = st.selectbox("Select make", options=list(
                range(len(make_keys))), format_func=lambda i: make_labels[i])
            sel_make_key = make_keys[idx]
        else:
            sel_make_key = None

        if sel_make_key:
            with st.expander("Rename / Delete make"):
                new_label = st.text_input(
                    "Make label", value=makes[sel_make_key].get("label", sel_make_key))
                c1, c2 = st.columns(2)
                with c1:
                    if wide_button("💾 Save make"):
                        makes[sel_make_key]["label"] = new_label.strip(
                        ) or makes[sel_make_key]["label"]
                        catalog = rebuild_derived_catalog_structures(
                            catalog, categories)
                        _write_json(CATALOG_FP, catalog)
                        bump_data_version()
                        st.success("Saved.")
                with c2:
                    if wide_button("🗑️ Delete make"):
                        del makes[sel_make_key]
                        catalog = rebuild_derived_catalog_structures(
                            catalog, categories)
                        _write_json(CATALOG_FP, catalog)
                        bump_data_version()
                        st.success("Deleted.")
                        st.rerun()

    with col2:
        if not sel_make_key:
            st.info("Add or select a make to manage its models.")
        else:
            st.markdown(f"**Models for {makes[sel_make_key]['label']}**")
            models: Dict[str, Any] = makes[sel_make_key].setdefault(
                "models", {})

            with st.form("add_model_form"):
                mdl_name = st.text_input("Model name")
                mdl_category = st.selectbox("Category", options=list(
                    categories.keys()), format_func=lambda k: categories[k]["label"])
                cA, cB = st.columns(2)
                with cA:
                    kg_txt = st.text_input(
                        "Weight (e.g., '55 kg' or '120 lb')")
                with cB:
                    w_txt = st.text_input(
                        "Width (e.g., '300 mm' or '11.8 in')")
                cC, cD = st.columns(2)
                with cC:
                    d_txt = st.text_input(
                        "Depth (e.g., '520 mm' or '20.5 in')")
                with cD:
                    h_txt = st.text_input(
                        "Height (e.g., '800 mm' or '31.5 in')")
                submitted = st.form_submit_button(
                    "➕ Add Model", type="primary")
            if submitted:
                if not mdl_name.strip():
                    st.warning("Enter model name.")
                else:
                    mkey = slugify(mdl_name)
                    if mkey in models:
                        st.error("Model already exists.")
                    else:
                        kg, lb = parse_weight(kg_txt)
                        w_mm, w_in = parse_length(w_txt)
                        d_mm, d_in = parse_length(d_txt)
                        h_mm, h_in = parse_length(h_txt)
                        models[mkey] = _merge_model_record(
                            models.get(mkey),
                            label=mdl_name.strip(),
                            category=mdl_category,
                            dimensions={
                                "weight": fmt_weight(kg, lb),
                                "width": fmt_length(w_mm, w_in),
                                "depth": fmt_length(d_mm, d_in),
                                "height": fmt_length(h_mm, h_in),
                            },
                        )
                        catalog = rebuild_derived_catalog_structures(
                            catalog, categories)
                        _write_json(CATALOG_FP, catalog)
                        bump_data_version()
                        st.success(f"Added model: {mdl_name}")
                        st.rerun()

            if models:
                # Table editor view
                rows = []
                for mk, mv in models.items():
                    dims = mv.get("dimensions", {})
                    rows.append({
                        "key": mk,
                        "Model": mv.get("label", mk),
                        "Category": mv.get("category", ""),
                        "Weight": dims.get("weight", ""),
                        "Width": dims.get("width", ""),
                        "Depth": dims.get("depth", ""),
                        "Height": dims.get("height", ""),
                    })
                df = pd.DataFrame(rows)
                edited = st.data_editor(
                    df,
                    num_rows="dynamic",
                    **editor_width_kwargs(width='stretch'),
                    column_config={
                        "Category": st.column_config.SelectboxColumn(options=list(categories.keys()), required=True, help="Select category"),
                    },
                    hide_index=True,
                )

                c1, c2, c3 = st.columns([1, 1, 1])
                with c1:
                    if wide_button("💾 Save Changes", type="primary"):
                        # write back
                        new_models: Dict[str, Any] = {}
                        for _, r in edited.iterrows():
                            key = str(r["key"]).strip()
                            label = str(r["Model"]).strip()
                            cat = str(r["Category"]).strip()
                            dims = {
                                "weight": str(r.get("Weight", "")).strip(),
                                "width": str(r.get("Width", "")).strip(),
                                "depth": str(r.get("Depth", "")).strip(),
                                "height": str(r.get("Height", "")).strip(),
                            }
                            if not key:
                                key = slugify(label) or slugify(
                                    f"model-{time.time_ns()}")
                            new_models[key] = _merge_model_record(
                                models.get(key),
                                label=label,
                                category=cat,
                                dimensions=dims,
                            )
                        makes[sel_make_key]["models"] = new_models
                        catalog = rebuild_derived_catalog_structures(
                            catalog, categories)
                        _write_json(CATALOG_FP, catalog)
                        bump_data_version()
                        st.success("Catalog saved.")
                with c2:
                    if wide_button("🧪 Validate"):
                        # Validate unique model names and categories exist
                        keys = [k for k in edited["key"]]
                        ok, dup = ensure_unique([str(k) for k in keys])
                        if not ok:
                            st.error(f"Duplicate model key found: {dup}")
                        else:
                            cats_ok = all(
                                str(c) in categories for c in edited["Category"])
                            if not cats_ok:
                                st.error(
                                    "Some rows reference missing categories.")
                            else:
                                st.success("Validation passed.")
                with c3:
                    if wide_button("🗑️ Delete Selected (by key)"):
                        # If user deletes rows in editor, saving already replaces. This button cleans unknown keys.
                        current_keys = set(
                            [str(k) for k in edited["key"] if str(k).strip()])
                        for k in list(models.keys()):
                            if k not in current_keys:
                                del models[k]
                        catalog = rebuild_derived_catalog_structures(
                            catalog, categories)
                        _write_json(CATALOG_FP, catalog)
                        bump_data_version()
                        st.success("Deleted removed rows.")
                        st.rerun()

# -----------------------------
# Customers Tab
# -----------------------------
with TAB[1]:
    st.subheader("Customers")
    st.write(
        "Manage named customer presets used by the survey selector, share links, and customer-specific question overrides."
    )

    customers = load_customers_config()
    customer_ids = [_as_str(customer.get("id")) for customer in customers if _as_str(customer.get("id"))]
    customer_lookup = {
        _as_str(customer.get("id")): customer
        for customer in customers
        if _as_str(customer.get("id"))
    }
    customer_override_root = (
        ((questions.get("overrides", {}) or {}).get("by_customer", {}) or {})
        if isinstance(questions, dict)
        else {}
    )

    make_keys = list((catalog.get("makes", {}) or {}).keys())
    make_options = ["__none__"] + make_keys

    def _default_model_key(make_key: str) -> str:
        if not make_key or make_key == "__none__":
            return "__none__"
        model_keys = list((((catalog.get("makes", {}) or {}).get(make_key, {}) or {}).get("models", {}) or {}).keys())
        return model_keys[0] if model_keys else "__none__"

    def _generate_customer_id(name: str, existing_ids: List[str]) -> str:
        base = slugify(name)
        if not base:
            return ""
        taken = {cid for cid in existing_ids if cid}
        if base not in taken:
            return base
        suffix = 2
        while f"{base}_{suffix}" in taken:
            suffix += 1
        return f"{base}_{suffix}"

    customer_options = ["__new__"] + customer_ids
    pending_customer_sel = st.session_state.pop("_admin_customer_pending_sel", None)
    if pending_customer_sel in customer_options:
        st.session_state["admin_customer_sel"] = pending_customer_sel
    elif pending_customer_sel == "__new__":
        st.session_state["admin_customer_sel"] = "__new__"
    if st.session_state.get("admin_customer_sel") not in customer_options:
        st.session_state["admin_customer_sel"] = customer_ids[0] if customer_ids else "__new__"

    selected_customer_id = st.selectbox(
        "Customer Record",
        options=customer_options,
        format_func=lambda cid: (
            "Add New Customer" if cid == "__new__"
            else (customer_lookup.get(cid) or {}).get("name", cid)
        ),
        key="admin_customer_sel",
    )

    selected_customer = customer_lookup.get(selected_customer_id) if selected_customer_id != "__new__" else None
    customer_state_token = selected_customer_id or "__new__"
    if st.session_state.get("_admin_customer_state_token") != customer_state_token:
        st.session_state["_admin_customer_name"] = _as_str((selected_customer or {}).get("name"))

        initial_make_key = find_make_key_by_label((selected_customer or {}).get("make"))
        if selected_customer_id == "__new__":
            initial_make_key = initial_make_key or (make_keys[0] if make_keys else "__none__")
        st.session_state["_admin_customer_make_key"] = initial_make_key or "__none__"

        initial_model_key = find_model_key_by_label(
            st.session_state["_admin_customer_make_key"],
            (selected_customer or {}).get("model"),
        )
        if selected_customer_id == "__new__":
            initial_model_key = initial_model_key or _default_model_key(st.session_state["_admin_customer_make_key"])
        st.session_state["_admin_customer_model_key"] = initial_model_key or "__none__"
        st.session_state["_admin_customer_delete_confirm"] = False
        st.session_state["_admin_customer_delete_overrides"] = False
        st.session_state["_admin_customer_state_token"] = customer_state_token

    left_col, right_col = st.columns([2, 1])
    with left_col:
        customer_name_value = _as_str(st.session_state.get("_admin_customer_name"))
        generated_customer_id = (
            selected_customer_id
            if selected_customer_id != "__new__"
            else _generate_customer_id(customer_name_value, customer_ids)
        )

        if selected_customer_id == "__new__":
            st.text_input(
                "Customer ID",
                value=generated_customer_id,
                disabled=True,
                help="Automatically generated from the customer name and used by share links and customer-specific overrides.",
            )
        else:
            st.text_input(
                "Customer ID",
                value=generated_customer_id,
                disabled=True,
                help="This ID stays fixed after creation because question overrides and shared links reference it.",
            )

        st.text_input("Customer Name", key="_admin_customer_name")

        selected_make_key = st.selectbox(
            "Make",
            options=make_options,
            format_func=lambda k: "— Select a make —" if k == "__none__" else ((catalog.get("makes", {}).get(k) or {}).get("label", k)),
            key="_admin_customer_make_key",
        )

        models_map = (
            (((catalog.get("makes", {}) or {}).get(selected_make_key, {}) or {}).get("models", {}) or {})
            if selected_make_key != "__none__"
            else {}
        )
        model_keys = list(models_map.keys())
        model_options = ["__none__"] + model_keys
        if st.session_state.get("_admin_customer_model_key") not in model_options:
            st.session_state["_admin_customer_model_key"] = model_keys[0] if model_keys else "__none__"

        selected_model_key = st.selectbox(
            "Model",
            options=model_options,
            format_func=lambda k: "— Select a model —" if k == "__none__" else ((models_map.get(k) or {}).get("label", k)),
            key="_admin_customer_model_key",
        )

        if selected_customer and not find_make_key_by_label(selected_customer.get("make")):
            st.warning("This customer references a make that is no longer present in the catalog. Pick a valid make before saving.")
        elif selected_customer and selected_make_key != "__none__" and not find_model_key_by_label(selected_make_key, selected_customer.get("model")):
            st.warning("This customer references a model that is no longer present in the selected make. Pick a valid model before saving.")

        save_customer = wide_button("💾 Save Customer", type="primary")
        if save_customer:
            customer_name = _as_str(st.session_state.get("_admin_customer_name"))
            if selected_customer_id == "__new__":
                customer_id_value = _generate_customer_id(customer_name, customer_ids)
            else:
                customer_id_value = selected_customer_id

            if not customer_name:
                st.error("Customer name is required.")
            elif not customer_id_value:
                st.error("Customer ID is required.")
            elif selected_make_key == "__none__":
                st.error("Select a make.")
            elif selected_model_key == "__none__":
                st.error("Select a model.")
            else:
                make_label_value = ((catalog.get("makes", {}).get(selected_make_key) or {}).get("label", selected_make_key))
                model_label_value = ((models_map.get(selected_model_key) or {}).get("label", selected_model_key))
                record = {
                    "id": customer_id_value,
                    "name": customer_name,
                    "make": make_label_value,
                    "model": model_label_value,
                }

                updated_customers: List[Dict[str, Any]] = []
                replaced = False
                for customer in customers:
                    existing_id = _as_str(customer.get("id"))
                    if selected_customer_id != "__new__" and existing_id == selected_customer_id:
                        updated_customers.append(record)
                        replaced = True
                    else:
                        updated_customers.append(customer)
                if not replaced:
                    updated_customers.append(record)

                save_customers_config(updated_customers)
                bump_data_version()
                st.session_state["_admin_customer_pending_sel"] = customer_id_value
                st.success("Customer saved.")
                st.rerun()

    with right_col:
        st.markdown("### Delete")
        if selected_customer_id == "__new__":
            st.caption("Select an existing customer to remove it.")
        else:
            has_question_overrides = selected_customer_id in customer_override_root
            st.checkbox("Confirm delete", key="_admin_customer_delete_confirm")
            if has_question_overrides:
                st.checkbox(
                    "Also delete customer question overrides",
                    key="_admin_customer_delete_overrides",
                    help="Customer-specific question overrides are stored in questions.json under this customer ID.",
                )
                st.warning("This customer has question overrides. Remove them with the customer or keep the record.")
            delete_customer = wide_button("🗑️ Delete Customer")
            if delete_customer:
                if not st.session_state.get("_admin_customer_delete_confirm"):
                    st.error("Confirm the delete first.")
                elif has_question_overrides and not st.session_state.get("_admin_customer_delete_overrides"):
                    st.error("Enable override deletion before removing this customer.")
                else:
                    updated_customers = [
                        customer
                        for customer in customers
                        if _as_str(customer.get("id")) != selected_customer_id
                    ]
                    save_customers_config(updated_customers)
                    if has_question_overrides:
                        questions.setdefault("overrides", {}).setdefault("by_customer", {}).pop(selected_customer_id, None)
                        _write_json(QUESTIONS_FP, questions)
                    bump_data_version()
                    st.session_state["_admin_customer_pending_sel"] = "__new__"
                    st.success("Customer deleted.")
                    st.rerun()

    st.markdown("### Current Customers")
    customer_rows = []
    for customer in customers:
        customer_id_value = _as_str(customer.get("id"))
        customer_rows.append(
            {
                "ID": customer_id_value,
                "Name": _as_str(customer.get("name")),
                "Make": _as_str(customer.get("make")),
                "Model": _as_str(customer.get("model")),
                "Question Overrides": "Yes" if customer_id_value in customer_override_root else "",
            }
        )
    if customer_rows:
        st.dataframe(pd.DataFrame(customer_rows), **editor_width_kwargs(width="stretch"), hide_index=True)
    else:
        st.info("No customers configured yet.")

# -----------------------------
# Categories & Sections Tab
# -----------------------------
with TAB[2]:
    st.subheader("Categories & Sections")

    with st.expander("Add Category", expanded=False):
        c1, c2 = st.columns([2, 1])
        with c1:
            label = st.text_input("Category label (e.g., 'Smart Safe')")
        with c2:
            key = st.text_input("Key (e.g., 'smart_safe')",
                                value=slugify(label))
        sections_txt = st.text_input(
            "Comma-separated sections", value="Delivery, Installation, Power, Networking")
        if wide_button("➕ Add Category"):
            if not key:
                st.warning("Provide a key.")
            elif key in categories:
                st.error("Key already exists.")
            else:
                categories[key] = {"label": label or key, "sections": [
                    s.strip() for s in sections_txt.split(",") if s.strip()]}
                _write_json(CATEGORIES_FP, categories)
                bump_data_version()
                st.success("Category added.")
                st.rerun()

    # Editable table
    rows = []
    for k, v in categories.items():
        rows.append({"key": k, "Label": v.get("label", k),
                    "Sections (comma)": ", ".join(v.get("sections", []))})
    df = pd.DataFrame(rows)
    edited = st.data_editor(df, **editor_width_kwargs(width='stretch'),
                            hide_index=True, num_rows="dynamic")

    c1, c2 = st.columns(2)
    with c1:
        if wide_button("💾 Save Categories", type="primary"):
            new = {}
            for _, r in edited.iterrows():
                k = str(r["key"]).strip() or slugify(
                    r.get("Label", f"cat-{time.time_ns()}"))
                new[k] = {
                    "label": str(r.get("Label", k)).strip(),
                    "sections": [s.strip() for s in str(r.get("Sections (comma)", "")).split(",") if s.strip()],
                }
            _write_json(CATEGORIES_FP, new)
            bump_data_version()
            st.success("Categories saved.")
    with c2:
        if wide_button("🧪 Validate cats"):
            ok, dup = ensure_unique([str(r["key"])
                                    for _, r in edited.iterrows()])
            if not ok:
                st.error(f"Duplicate key: {dup}")
            else:
                st.success("Validation passed.")

# -----------------------------
# Question Sets Tab
# -----------------------------
with TAB[3]:
    st.subheader("Question Sets")
    st.write(
        "Manage questions at the category default, make/model override, or customer override level. "
        "Types: text, textarea, number, select, multiselect, radio, time, checkbox, file. "
        "Use visible_if to show conditionally."
    )

    scope = st.selectbox(
        "Scope",
        options=["Category Default", "By Make/Model", "By Customer"],
        key="question_set_scope",
    )

    # -------------------------
    # Scope: By category (existing behaviour)
    # -------------------------
    if scope == "Category Default":
        cat_keys = list(categories.keys())
        if not cat_keys:
            st.info("Create at least one category first.")
        else:
            cat_sel = st.selectbox(
                "Category",
                options=cat_keys,
                format_func=lambda k: categories[k]["label"],
                key="profile_cat_sel",
            )
            cat_key = normalize_category_key(cat_sel)
            questions = ensure_category_profile_data(questions, cat_key)

            bank_sections = get_question_bank_sections(questions, cat_key)
            profiles = get_profiles_for_category(questions, cat_key)
            profile_ids = [profile["id"] for profile in profiles]
            default_profile_id = get_default_profile_id(questions, cat_key)

            if st.session_state.get("profile_template_sel") not in profile_ids:
                st.session_state["profile_template_sel"] = (
                    default_profile_id if default_profile_id in profile_ids else profile_ids[0]
                )

            profile_sel = st.selectbox(
                "Profile",
                options=profile_ids,
                format_func=lambda pid: next(
                    (profile["name"] for profile in profiles if profile["id"] == pid),
                    pid,
                ),
                key="profile_template_sel",
            )
            selected_profile = next(
                (profile for profile in profiles if profile["id"] == profile_sel),
                profiles[0],
            )

            profile_token = f"{cat_key}:{profile_sel}"
            if st.session_state.get("_admin_profile_state_token") != profile_token:
                st.session_state["_admin_profile_name"] = selected_profile.get("name", "")
                st.session_state["_admin_profile_default"] = profile_sel == default_profile_id
                st.session_state["_admin_profile_state_token"] = profile_token

            st.text_input("Profile name", key="_admin_profile_name")
            st.checkbox(
                "Use this as the default profile for new and legacy surveys",
                key="_admin_profile_default",
            )

            act1, act2, act3 = st.columns(3)
            with act1:
                if wide_button("New Profile", type="primary"):
                    new_name = st.session_state.get("_admin_profile_name", "").strip() or "New Profile"
                    new_id = profile_slugify(new_name)
                    if not new_id:
                        st.error("Enter a profile name first.")
                    elif new_id in {profile["id"] for profile in profiles}:
                        st.error("A profile with that id already exists for this category.")
                    else:
                        questions["profiles"].setdefault(cat_key, []).append(
                            {
                                "id": new_id,
                                "name": new_name,
                                "category": cat_key,
                                "questions": [],
                                "custom_questions": [],
                            }
                        )
                        questions["profile_defaults"].setdefault(cat_key, default_profile_id)
                        persist_questions_config(questions)
                        st.session_state["profile_template_sel"] = new_id
                        st.rerun()
            with act2:
                if wide_button("Duplicate Profile"):
                    copy_name = st.session_state.get("_admin_profile_name", "").strip() or f"{selected_profile.get('name', 'Profile')} Copy"
                    copy_id = profile_slugify(copy_name)
                    if not copy_id:
                        st.error("Enter a profile name first.")
                    elif copy_id in {profile["id"] for profile in profiles}:
                        st.error("A profile with that id already exists for this category.")
                    else:
                        duplicated = json.loads(json.dumps(selected_profile))
                        duplicated["id"] = copy_id
                        duplicated["name"] = copy_name
                        questions["profiles"].setdefault(cat_key, []).append(duplicated)
                        persist_questions_config(questions)
                        st.session_state["profile_template_sel"] = copy_id
                        st.rerun()
            with act3:
                if wide_button("Delete Profile"):
                    if len(profiles) <= 1:
                        st.error("At least one profile must remain for each category.")
                    else:
                        questions["profiles"][cat_key] = [
                            profile for profile in profiles if profile["id"] != profile_sel
                        ]
                        next_profile_id = questions["profiles"][cat_key][0]["id"]
                        if questions.get("profile_defaults", {}).get(cat_key) == profile_sel:
                            questions.setdefault("profile_defaults", {})[cat_key] = next_profile_id
                        persist_questions_config(questions)
                        st.session_state["profile_template_sel"] = next_profile_id
                        st.rerun()

            st.divider()
            st.markdown("### Question Bank and Profile Coverage")
            st.caption(
                "Edit the reusable bank and choose which questions belong to this profile. "
                "Only included questions render at runtime."
            )

            profile_question_map = {
                item.get("question_id"): item
                for item in selected_profile.get("questions", []) or []
                if isinstance(item, dict) and item.get("question_id")
            }
            edited_sections: List[Tuple[Dict[str, Any], pd.DataFrame]] = []
            type_options = [
                "text",
                "textarea",
                "number",
                "select",
                "multiselect",
                "radio",
                "time",
                "checkbox",
                "file",
            ]

            for section in bank_sections:
                section_rows = [
                    question_bank_row(question, profile_question_map, default_order=index)
                    for index, question in enumerate(section.get("questions", []) or [], start=1)
                ]
                if not section_rows:
                    section_rows = [{
                        "Include": False,
                        "Required": False,
                        "Order": 1,
                        "Question ID": "",
                        "Question": "",
                        "Type": "text",
                        "Default Required": False,
                        "Options (comma)": "",
                        "visible_if (JSON)": "",
                    }]
                with st.expander(section_label(section), expanded=True):
                    edited_df = st.data_editor(
                        pd.DataFrame(section_rows),
                        **editor_width_kwargs(width="stretch"),
                        hide_index=True,
                        num_rows="dynamic",
                        key=f"profile_editor_{cat_key}_{profile_sel}_{section.get('key')}",
                        column_config={
                            "Include": st.column_config.CheckboxColumn(),
                            "Required": st.column_config.CheckboxColumn(),
                            "Order": st.column_config.NumberColumn(min_value=1, step=1),
                            "Type": st.column_config.SelectboxColumn(options=type_options),
                            "Default Required": st.column_config.CheckboxColumn(),
                        },
                    )
                    edited_sections.append((section, edited_df))

            st.divider()
            st.markdown("### Add Question to Category Bank")
            with st.form("add_bank_question_form"):
                section_options = [section.get("key") for section in bank_sections]
                add_section_key = st.selectbox(
                    "Section",
                    options=section_options,
                    format_func=lambda key: next(
                        (section_label(section) for section in bank_sections if section.get("key") == key),
                        key,
                    ),
                )
                add_label = st.text_input("Question label", key="bank_q_label")
                add_key = st.text_input("Question ID", value=profile_slugify(add_label), key="bank_q_key")
                add_type = st.selectbox("Type", options=type_options, key="bank_q_type")
                add_required = st.checkbox("Default required", value=False, key="bank_q_required")
                add_col1, add_col2 = st.columns(2)
                with add_col1:
                    add_options = st.text_input("Options (comma-separated)", key="bank_q_options")
                with add_col2:
                    add_visible_if = st.text_input("visible_if (JSON)", key="bank_q_visible_if")
                add_submit = st.form_submit_button("Add Question")

            if add_submit:
                target_section = next(
                    (section for section in bank_sections if section.get("key") == add_section_key),
                    None,
                )
                new_id = str(add_key or "").strip() or profile_slugify(add_label)
                existing_ids = {
                    question_id(question)
                    for section in bank_sections
                    for question in section.get("questions", []) or []
                }
                if not new_id:
                    st.error("Question ID is required.")
                elif new_id in existing_ids:
                    st.error("Question ID already exists in this category bank.")
                elif target_section is None:
                    st.error("Select a valid section.")
                else:
                    new_question = {
                        "id": new_id,
                        "name": new_id,
                        "label": add_label or new_id,
                        "type": add_type,
                        "required": add_required,
                    }
                    if add_options.strip():
                        new_question["options"] = [
                            option.strip()
                            for option in add_options.split(",")
                            if option.strip()
                        ]
                    if add_visible_if.strip():
                        try:
                            new_question["visible_if"] = json.loads(add_visible_if)
                        except Exception as exc:
                            st.error(f"Invalid JSON for visible_if: {exc}")
                            st.stop()

                    for section in questions["question_bank"][cat_key]["sections"]:
                        if section.get("key") == add_section_key:
                            section.setdefault("questions", []).append(new_question)
                            break
                    persist_questions_config(questions)
                    st.success("Question added to the category bank.")
                    st.rerun()

            if wide_button("Save Profile", type="primary"):
                updated_sections: List[Dict[str, Any]] = []
                all_profile_rows: List[Dict[str, Any]] = []
                bank_required_by_id: Dict[str, bool] = {}
                section_errors: List[str] = []

                for section, edited_df in edited_sections:
                    updated_section = dict(section)
                    updated_questions: List[Dict[str, Any]] = []
                    existing_question_map = {
                        question_id(question): question
                        for question in section.get("questions", []) or []
                        if isinstance(question, dict) and question_id(question)
                    }
                    seen_ids = set()

                    for _, row in edited_df.iterrows():
                        question_label = str(row.get("Question", "")).strip()
                        qid = str(row.get("Question ID", "")).strip() or profile_slugify(question_label)
                        if not qid:
                            continue
                        if qid in seen_ids:
                            section_errors.append(f"Duplicate question id '{qid}' in section '{section_label(section)}'.")
                            continue
                        seen_ids.add(qid)

                        existing_question = dict(existing_question_map.get(qid) or {})
                        question = dict(existing_question)
                        question["id"] = qid
                        question["name"] = qid
                        question.pop("key", None)
                        question["type"] = str(row.get("Type", "text") or "text")
                        question["required"] = checkbox_value(row.get("Default Required", False))

                        existing_label = str(existing_question.get("label") or "").strip()
                        existing_label_key = str(existing_question.get("label_key") or "").strip()
                        existing_resolved_text = question_text(existing_question)
                        if question_label:
                            if existing_label_key and not existing_label and question_label == existing_resolved_text:
                                question.pop("label", None)
                                question["label_key"] = existing_label_key
                            else:
                                question["label"] = question_label
                                if existing_label_key and question_label != existing_resolved_text:
                                    question.pop("label_key", None)
                        else:
                            question["label"] = qid

                        options_raw = str(row.get("Options (comma)", "") or "").strip()
                        if options_raw:
                            question["options"] = [
                                option.strip()
                                for option in options_raw.split(",")
                                if option.strip()
                            ]
                        elif "options" in question:
                            question.pop("options", None)

                        visible_if_raw = str(row.get("visible_if (JSON)", "") or "").strip()
                        if visible_if_raw:
                            try:
                                question["visible_if"] = json.loads(visible_if_raw)
                            except Exception as exc:
                                section_errors.append(
                                    f"Invalid visible_if JSON for '{qid}' in section '{section_label(section)}': {exc}"
                                )
                                continue

                        updated_questions.append(question)
                        bank_required_by_id[qid] = bool(question["required"])
                        all_profile_rows.append(
                            {
                                "Include": checkbox_value(row.get("Include", False)),
                                "Required": checkbox_value(row.get("Required", False)),
                                "Order": row.get("Order", len(all_profile_rows) + 1),
                                "Question ID": qid,
                            }
                        )

                    updated_section["questions"] = updated_questions
                    updated_sections.append(updated_section)

                if section_errors:
                    for error in section_errors:
                        st.error(error)
                    st.stop()

                updated_profile = json.loads(json.dumps(selected_profile))
                updated_profile["name"] = st.session_state.get("_admin_profile_name", "").strip() or selected_profile.get("name", profile_sel)
                updated_profile["category"] = cat_key
                updated_profile["questions"] = build_profile_question_items(all_profile_rows, bank_required_by_id)
                updated_profile.setdefault("custom_questions", [])

                questions["question_bank"][cat_key] = {"sections": updated_sections}
                questions["profiles"][cat_key] = [
                    updated_profile if profile.get("id") == profile_sel else profile
                    for profile in profiles
                ]

                if st.session_state.get("_admin_profile_default"):
                    questions.setdefault("profile_defaults", {})[cat_key] = profile_sel
                elif questions.get("profile_defaults", {}).get(cat_key) == profile_sel:
                    questions["profile_defaults"][cat_key] = profile_sel

                persist_questions_config(questions)
                st.success("Profile and category question bank saved.")
                st.rerun()

    elif scope in {"By Make/Model", "By Customer"}:
        type_options = [
            "text",
            "textarea",
            "number",
            "select",
            "multiselect",
            "radio",
            "time",
            "checkbox",
            "file",
        ]

        selected_override_key = None
        selected_category_key = None
        override_sections: Dict[str, List[Dict[str, Any]]] = {}

        if scope == "By Make/Model":
            make_keys = list((catalog.get("makes", {}) or {}).keys())
            if not make_keys:
                st.info("Create at least one make/model first.")
                st.stop()
            mm_col1, mm_col2 = st.columns(2)
            with mm_col1:
                make_key_sel = st.selectbox(
                    "Make",
                    options=make_keys,
                    format_func=lambda k: ((catalog.get("makes", {}) or {}).get(k, {}) or {}).get("label", k),
                    key="qs_make_sel",
                )
            model_options = list((((catalog.get("makes", {}) or {}).get(make_key_sel, {}) or {}).get("models", {}) or {}).keys())
            with mm_col2:
                model_key_sel = (
                    st.selectbox(
                        "Model",
                        options=model_options,
                        format_func=lambda k: (((catalog.get("makes", {}) or {}).get(make_key_sel, {}) or {}).get("models", {}) or {}).get(k, {}).get("label", k),
                        key="qs_model_sel",
                    )
                    if model_options else None
                )

            if not model_key_sel:
                st.info("Select a model to edit make/model overrides.")
                st.stop()

            selected_override_key = f"{make_key_sel}:{model_key_sel}"
            selected_category_key = normalize_category_key(
                (((catalog.get("makes", {}) or {}).get(make_key_sel, {}) or {}).get("models", {}) or {}).get(model_key_sel, {}).get("category", "")
            )
            override_sections = (((questions.setdefault("overrides", {}) or {}).setdefault("by_model", {}) or {}).get(selected_override_key, {}) or {})
            st.caption(f"Editing override key: {selected_override_key}")
        else:
            customers = load_customers_config()
            customer_ids = [customer.get("id") for customer in customers if customer.get("id")]
            customer_lookup = {customer.get("id"): customer for customer in customers if customer.get("id")}
            if not customer_ids:
                st.info("No customers found in data/customers.json.")
                st.stop()
            customer_id = st.selectbox(
                "Customer",
                options=customer_ids,
                format_func=lambda cid: (customer_lookup.get(cid) or {}).get("name", cid),
                key="qs_customer_sel",
            )
            customer = customer_lookup.get(customer_id) or {}
            make_key_sel = find_make_key_by_label(customer.get("make"))
            model_key_sel = find_model_key_by_label(make_key_sel, customer.get("model"))
            selected_override_key = customer_id
            selected_category_key = normalize_category_key(
                (((catalog.get("makes", {}) or {}).get(make_key_sel, {}) or {}).get("models", {}) or {}).get(model_key_sel, {}).get("category", "")
            )
            override_sections = (((questions.setdefault("overrides", {}) or {}).setdefault("by_customer", {}) or {}).get(customer_id, {}) or {})
            st.caption(f"Editing customer override: {(customer.get('name') or customer_id)}")

        if not selected_category_key:
            st.warning("Unable to determine category for the selected scope.")
            st.stop()

        bank_sections = get_question_bank_sections(questions, selected_category_key)
        default_profile_sections, _ = build_sections_for_profile(
            questions,
            selected_category_key,
            get_default_profile_id(questions, selected_category_key),
        )
        default_section_fields = {
            str(section.get("key") or "").strip(): list(section.get("fields", []) or [])
            for section in default_profile_sections
            if str(section.get("key") or "").strip()
        }
        st.caption("Showing questions from the default profile for this category plus any explicit overrides. Uncheck Include to disable a default question for this scope.")
        edited_sections: List[Tuple[Dict[str, Any], List[Dict[str, Any]], pd.DataFrame]] = []

        for section in bank_sections:
            section_key = section.get("key")
            base_questions = default_section_fields.get(section_key, [])
            existing_questions = override_sections.get(section_key, []) or []
            section_rows = build_override_editor_rows(base_questions, existing_questions)
            if not section_rows:
                section_rows = [{
                    "Include": False,
                    "Required": False,
                    "Order": 1,
                    "Question ID": "",
                    "Question": "",
                    "Type": "text",
                    "Default Required": False,
                    "Options (comma)": "",
                    "visible_if (JSON)": "",
                }]
            with st.expander(section_label(section), expanded=True):
                edited_df = st.data_editor(
                    pd.DataFrame(section_rows),
                    **editor_width_kwargs(width="stretch"),
                    hide_index=True,
                    num_rows="dynamic",
                    key=f"override_editor_{scope}_{selected_override_key}_{section_key}",
                    column_config={
                        "Include": st.column_config.CheckboxColumn(),
                        "Required": st.column_config.CheckboxColumn(),
                        "Order": st.column_config.NumberColumn(min_value=1, step=1),
                        "Type": st.column_config.SelectboxColumn(options=type_options),
                        "Default Required": st.column_config.CheckboxColumn(disabled=True),
                    },
                )
                edited_sections.append((section, base_questions, edited_df))

        st.divider()
        st.markdown("### Add Question to Override Set")
        with st.form(f"add_override_question_form_{scope}"):
            section_options = [section.get("key") for section in bank_sections]
            add_section_key = st.selectbox(
                "Section",
                options=section_options,
                format_func=lambda key: next((section_label(section) for section in bank_sections if section.get("key") == key), key),
            )
            add_label = st.text_input("Question label", key=f"override_q_label_{scope}")
            add_key = st.text_input("Question ID", value=profile_slugify(add_label), key=f"override_q_key_{scope}")
            add_type = st.selectbox("Type", options=type_options, key=f"override_q_type_{scope}")
            add_required = st.checkbox("Required", value=False, key=f"override_q_required_{scope}")
            add_col1, add_col2 = st.columns(2)
            with add_col1:
                add_options = st.text_input("Options (comma-separated)", key=f"override_q_options_{scope}")
            with add_col2:
                add_visible_if = st.text_input("visible_if (JSON)", key=f"override_q_visible_if_{scope}")
            add_submit = st.form_submit_button("Add Question")

        if add_submit:
            new_id = str(add_key or "").strip() or profile_slugify(add_label)
            if not new_id:
                st.error("Question ID is required.")
            else:
                new_question = {
                    "id": new_id,
                    "name": new_id,
                    "label": add_label or new_id,
                    "type": add_type,
                    "required": add_required,
                }
                if add_options.strip():
                    new_question["options"] = [option.strip() for option in add_options.split(",") if option.strip()]
                if add_visible_if.strip():
                    try:
                        new_question["visible_if"] = json.loads(add_visible_if)
                    except Exception as exc:
                        st.error(f"Invalid JSON for visible_if: {exc}")
                        st.stop()

                target_map = questions.setdefault("overrides", {}).setdefault("by_model" if scope == "By Make/Model" else "by_customer", {})
                target_sections = target_map.setdefault(selected_override_key, {})
                target_sections.setdefault(add_section_key, []).append(new_question)
                persist_questions_config(questions)
                st.success("Question added to override set.")
                st.rerun()

        if wide_button("Save Question Set", type="primary"):
            updated_scope_sections: Dict[str, List[Dict[str, Any]]] = {}
            section_errors: List[str] = []
            for section, base_questions, edited_df in edited_sections:
                section_key = section.get("key")
                rows = edited_df.to_dict("records")
                base_question_map = {
                    question_id(question): question
                    for question in (base_questions or [])
                    if isinstance(question, dict) and question_id(question)
                }
                base_order_by_id = {
                    question_id(question): index
                    for index, question in enumerate(base_questions or [], start=1)
                    if isinstance(question, dict) and question_id(question)
                }
                try:
                    built_questions = build_override_questions(
                        rows,
                        base_question_map=base_question_map,
                        base_order_by_id=base_order_by_id,
                    )
                except Exception as exc:
                    section_errors.append(f"Invalid override data in section '{section_label(section)}': {exc}")
                    continue
                if built_questions:
                    updated_scope_sections[section_key] = built_questions

            if section_errors:
                for error in section_errors:
                    st.error(error)
                st.stop()

            scope_root_key = "by_model" if scope == "By Make/Model" else "by_customer"
            target_root = questions.setdefault("overrides", {}).setdefault(scope_root_key, {})
            if updated_scope_sections:
                target_root[selected_override_key] = updated_scope_sections
            else:
                target_root.pop(selected_override_key, None)
            persist_questions_config(questions)
            st.success("Override question set saved.")
            st.rerun()

            # Editor
            if q_list:
                q_rows = []
                for it in q_list:
                    q_rows.append(
                        {
                            "key": it.get("key", ""),
                            "Label": it.get("label", ""),
                            "Type": it.get("type", "text"),
                            "Required": bool(it.get("required", False)),
                            "Options (comma)": ", ".join(it.get("options", []))
                            if isinstance(it.get("options"), list)
                            else "",
                            "visible_if (JSON)": json.dumps(it.get("visible_if"))
                            if isinstance(it.get("visible_if"), dict)
                            else "",
                        }
                    )
                df = pd.DataFrame(q_rows)
                edited = st.data_editor(
                    df,
                    **editor_width_kwargs(width="stretch"),
                    hide_index=True,
                    column_config={
                        "Type": st.column_config.SelectboxColumn(
                            options=[
                                "text",
                                "textarea",
                                "number",
                                "select",
                                "multiselect",
                                "radio",
                                "time",
                                "checkbox",
                                "file",
                            ]
                        ),
                        "Required": st.column_config.CheckboxColumn(),
                    },
                    num_rows="dynamic",
                )
                c1, c2 = st.columns(2)
                with c1:
                    if wide_button("💾 Save Questions", type="primary"):
                        new_list = []
                        keys_seen = set()
                        for _, r in edited.iterrows():
                            k = str(r["key"]).strip() or slugify(
                                r.get("Label", "field")
                            )
                            if k in keys_seen:
                                st.error(f"Duplicate key in section: {k}")
                                st.stop()
                            keys_seen.add(k)
                            item = {
                                "key": k,
                                "label": str(r.get("Label", "")),
                                "type": str(r.get("Type", "text")),
                                "required": bool(r.get("Required", False)),
                            }
                            opts = str(r.get("Options (comma)", "")).strip()
                            if opts:
                                item["options"] = [
                                    o.strip() for o in opts.split(",") if o.strip()
                                ]
                            vis = str(r.get("visible_if (JSON)", "")).strip()
                            if vis:
                                try:
                                    item["visible_if"] = json.loads(vis)
                                except Exception as e:
                                    st.error(
                                        f"Invalid visible_if JSON on {k}: {e}"
                                    )
                                    st.stop()
                            new_list.append(item)
                        questions.setdefault(cat_sel, {})[sec_sel] = new_list
                        _write_json(QUESTIONS_FP, questions)
                        bump_data_version()
                        st.success("Saved.")
                with c2:
                    if wide_button("🧪 Validate Section"):
                        st.success("Basic validation OK (unique keys & JSON parse).")
            else:
                st.info("No fields yet for this section.")

    # -------------------------
    # Scope: By model (new)
    # -------------------------
    else:
        makes_map = catalog.get("makes", {})
        if not makes_map:
            st.info("Add a make/model in the Catalog tab first.")
        else:
            make_keys = list(makes_map.keys())
            c1, c2, c3 = st.columns(3)
            with c1:
                sel_make = st.selectbox(
                    "Make",
                    options=make_keys,
                    format_func=lambda k: makes_map[k].get("label", k),
                    key="q_make_sel",
                )

            models_map = makes_map.get(sel_make, {}).get("models", {})
            if not models_map:
                st.warning("Selected make has no models yet.")
                st.stop()

            model_keys = list(models_map.keys())
            with c2:
                sel_model = st.selectbox(
                    "Model",
                    options=model_keys,
                    format_func=lambda k: models_map[k].get("label", k),
                    key="q_model_sel",
                )

            mdl_obj = models_map.get(sel_model, {})
            mdl_cat = mdl_obj.get("category") or None
            if mdl_cat and mdl_cat in categories:
                sec_options = categories[mdl_cat].get("sections", [])
            else:
                # fallback if category is missing
                first_cat = next(iter(categories.keys()))
                sec_options = categories[first_cat].get("sections", [])
                mdl_cat = first_cat

            with c3:
                sec_sel = st.selectbox("Section", options=sec_options, key="q_model_sec")

            # Load or init model override list
            overrides_root = questions.setdefault("overrides", {}).setdefault(
                "by_model", {}
            )
            model_id = model_q_id(sel_make, sel_model)
            model_sec_map = overrides_root.setdefault(model_id, {})
            q_list: List[Dict[str, Any]] = model_sec_map.setdefault(sec_sel, [])

            st.caption(
                f"Model override for **{makes_map[sel_make].get('label', sel_make)} → "
                f"{mdl_obj.get('label', sel_model)}**, section **{sec_sel}** "
                f"(category: {mdl_cat})"
            )

            # New model-specific question form
            with st.form("add_q_model"):
                q_label = st.text_input("Question label", key="m_q_label")
                q_key = st.text_input(
                    "Key", value=slugify(q_label), key="m_q_key"
                )
                q_type = st.selectbox(
                    "Type",
                    options=[
                        "text",
                        "textarea",
                        "number",
                        "select",
                        "multiselect",
                        "radio",
                        "time",
                        "checkbox",
                        "file",
                    ],
                    key="m_q_type",
                )
                q_required = st.checkbox(
                    "Required", value=False, key="m_q_req"
                )
                colx, coly = st.columns(2)
                with colx:
                    q_options = st.text_input(
                        "Options (comma-separated, for select/radio/multiselect)",
                        key="m_q_opts",
                    )
                with coly:
                    q_visible_if = st.text_input(
                        'visible_if (JSON; e.g., {"field":"dock","equals":"Yes"})',
                        key="m_q_vis",
                    )
                q_submit = st.form_submit_button(
                    "➕ Add Model Field", type="primary"
                )

            if q_submit:
                if not q_key:
                    st.warning("Key is required.")
                elif any(q.get("key") == q_key for q in q_list):
                    st.error("Key already exists in this model/section.")
                else:
                    new_q = {
                        "key": q_key,
                        "label": q_label or q_key,
                        "type": q_type,
                        "required": q_required,
                    }
                    if q_options.strip():
                        new_q["options"] = [
                            o.strip() for o in q_options.split(",") if o.strip()
                        ]
                    if q_visible_if.strip():
                        try:
                            new_q["visible_if"] = json.loads(q_visible_if)
                        except Exception as e:
                            st.error(f"Invalid JSON for visible_if: {e}")
                    q_list.append(new_q)
                    overrides_root[model_id] = model_sec_map
                    questions.setdefault("overrides", {})["by_model"] = overrides_root
                    _write_json(QUESTIONS_FP, questions)
                    bump_data_version()
                    st.success("Model field added.")

            # Editor for model overrides
            if q_list:
                q_rows = []
                for it in q_list:
                    q_rows.append(
                        {
                            "key": it.get("key", ""),
                            "Label": it.get("label", ""),
                            "Type": it.get("type", "text"),
                            "Required": bool(it.get("required", False)),
                            "Options (comma)": ", ".join(it.get("options", []))
                            if isinstance(it.get("options"), list)
                            else "",
                            "visible_if (JSON)": json.dumps(it.get("visible_if"))
                            if isinstance(it.get("visible_if"), dict)
                            else "",
                        }
                    )
                df = pd.DataFrame(q_rows)
                edited = st.data_editor(
                    df,
                    **editor_width_kwargs(width="stretch"),
                    hide_index=True,
                    column_config={
                        "Type": st.column_config.SelectboxColumn(
                            options=[
                                "text",
                                "textarea",
                                "number",
                                "select",
                                "multiselect",
                                "radio",
                                "time",
                                "checkbox",
                                "file",
                            ]
                        ),
                        "Required": st.column_config.CheckboxColumn(),
                    },
                    num_rows="dynamic",
                )

                c1, c2 = st.columns(2)
                with c1:
                    if wide_button("💾 Save Model Questions", type="primary"):
                        new_list = []
                        keys_seen = set()
                        for _, r in edited.iterrows():
                            k = str(r["key"]).strip() or slugify(
                                r.get("Label", "field")
                            )
                            if k in keys_seen:
                                st.error(
                                    f"Duplicate key in model section: {k}"
                                )
                                st.stop()
                            keys_seen.add(k)
                            item = {
                                "key": k,
                                "label": str(r.get("Label", "")),
                                "type": str(r.get("Type", "text")),
                                "required": bool(r.get("Required", False)),
                            }
                            opts = str(r.get("Options (comma)", "")).strip()
                            if opts:
                                item["options"] = [
                                    o.strip() for o in opts.split(",") if o.strip()
                                ]
                            vis = str(r.get("visible_if (JSON)", "")).strip()
                            if vis:
                                try:
                                    item["visible_if"] = json.loads(vis)
                                except Exception as e:
                                    st.error(
                                        f"Invalid visible_if JSON on {k}: {e}"
                                    )
                                    st.stop()
                            new_list.append(item)

                        model_sec_map[sec_sel] = new_list
                        overrides_root[model_id] = model_sec_map
                        questions.setdefault("overrides", {})["by_model"] = overrides_root
                        _write_json(QUESTIONS_FP, questions)
                        bump_data_version()
                        st.success("Model questions saved.")
                with c2:
                    if wide_button("🧪 Validate Model Section"):
                        st.success(
                            "Basic validation OK (unique keys & JSON parse)."
                        )
            else:
                st.info(
                    "No model-specific fields yet for this section."
                )

# -----------------------------
# Media Library Tab
# -----------------------------
with TAB[4]:
    st.subheader("Media Library")
    st.write(
        "Upload images and brochures. Extract dimensions from brochure text if present.")

    up_col1, up_col2 = st.columns(2)
    with up_col1:
        img_files = st.file_uploader("Upload images", type=[
                                     "png", "jpg", "jpeg", "webp"], accept_multiple_files=True)
        if wide_button("⬆️ Save Images"):
            count = 0
            # Optional quick-attach to currently selected model (if selected in Model Media panel)
            sel_make = st.session_state.get("media_make_sel")
            sel_model = st.session_state.get("media_model_sel")
            media_obj = None
            if sel_make and sel_model:
                try:
                    mdl_obj = _get_model_ref(catalog, sel_make, sel_model)
                    media_obj = _ensure_media(mdl_obj)
                except Exception:
                    media_obj = None
            attached = 0
            hero_set = False

            for f in img_files or []:
                fname = slugify(os.path.splitext(f.name)[
                                0]) + os.path.splitext(f.name)[1].lower()
                out = os.path.join(MEDIA_DIR, fname)
                with open(out, "wb") as w:
                    w.write(f.read())
                media_index.setdefault("images", {})[fname] = {
                    "path": out, "ts": time.time()}
                # Quick-attach: add to gallery and set hero if not set
                if media_obj is not None:
                    if fname not in media_obj.get("gallery", []):
                        media_obj["gallery"].append(fname)
                        attached += 1
                    if not media_obj.get("hero_image"):
                        media_obj["hero_image"] = fname
                        hero_set = True
                count += 1

            _write_json(MEDIA_INDEX_FP, media_index)

            # Persist catalog if we attached anything
            if media_obj is not None and (attached > 0 or hero_set):
                catalog = rebuild_derived_catalog_structures(
                    catalog, categories)
                _write_json(CATALOG_FP, catalog)
                bump_data_version()
                make_label = catalog.get("makes", {}).get(
                    sel_make, {}).get("label", sel_make)
                model_label = catalog.get("makes", {}).get(sel_make, {}).get(
                    "models", {}).get(sel_model, {}).get("label", sel_model)
                st.info(
                    f"Auto-attached {attached} image(s){' and set hero' if hero_set else ''} to {make_label} → {model_label}.")

            st.success(f"Saved {count} image(s).")
    with up_col2:
        br_files = st.file_uploader("Upload brochures (PDF or text)", type=[
                                    "pdf", "txt"], accept_multiple_files=True)
        if wide_button("⬆️ Save Brochures"):
            count = 0
            sel_make = st.session_state.get("media_make_sel")
            sel_model = st.session_state.get("media_model_sel")
            media_obj = None
            if sel_make and sel_model:
                try:
                    mdl_obj = _get_model_ref(catalog, sel_make, sel_model)
                    media_obj = _ensure_media(mdl_obj)
                except Exception:
                    media_obj = None
            attached = 0

            for f in br_files or []:
                fname = slugify(os.path.splitext(f.name)[
                                0]) + os.path.splitext(f.name)[1].lower()
                out = os.path.join(MEDIA_DIR, fname)
                with open(out, "wb") as w:
                    w.write(f.read())
                media_index.setdefault("brochures", {})[fname] = {
                    "path": out, "ts": time.time()}
                if media_obj is not None and fname not in media_obj.get("brochures", []):
                    media_obj["brochures"].append(fname)
                    attached += 1
                count += 1

            _write_json(MEDIA_INDEX_FP, media_index)

            if media_obj is not None and attached > 0:
                catalog = rebuild_derived_catalog_structures(
                    catalog, categories)
                _write_json(CATALOG_FP, catalog)
                bump_data_version()
                make_label = catalog.get("makes", {}).get(
                    sel_make, {}).get("label", sel_make)
                model_label = catalog.get("makes", {}).get(sel_make, {}).get(
                    "models", {}).get(sel_model, {}).get("label", sel_model)
                st.info(
                    f"Auto-attached {attached} brochure(s) to {make_label} → {model_label}.")

            st.success(f"Saved {count} brochure(s).")

    st.markdown("**Current Media Index**")
    tbl_rows = []
    for kind in ("images", "brochures"):
        for fname, meta in media_index.get(kind, {}).items():
            tbl_rows.append({"Kind": kind, "File": fname, "Path": meta.get(
                "path", ""), "Added": time.strftime('%Y-%m-%d %H:%M', time.localtime(meta.get("ts", 0)))})
    if tbl_rows:
        st.dataframe(
            pd.DataFrame(tbl_rows),
            hide_index=True,
            **editor_width_kwargs(width='stretch'),
        )
    else:
        st.info("No media yet.")

    st.divider()
    st.markdown("### Model Media")

    # Build make/model selectors from the normalized catalog
    makes_map = catalog.get("makes", {})
    make_options = list(makes_map.keys())
    if not make_options:
        st.info("Add a make/model first in Catalog.")
    else:
        c1, c2 = st.columns(2)
        with c1:
            sel_make = st.selectbox(
                "Make",
                options=make_options,
                format_func=lambda k: makes_map[k].get("label", k),
                key="media_make_sel",
            )
        models_map = makes_map.get(sel_make, {}).get(
            "models", {}) if sel_make else {}
        with c2:
            sel_model = st.selectbox(
                "Model",
                options=list(models_map.keys()),
                format_func=lambda k: models_map[k].get("label", k),
                key="media_model_sel",
            )

        if sel_make and sel_model:
            mdl_obj = _get_model_ref(catalog, sel_make, sel_model)
            media_obj = _ensure_media(mdl_obj)

            # Build picklists from media_index
            image_choices = sorted((media_index.get("images") or {}).keys())
            brochure_choices = sorted(
                (media_index.get("brochures") or {}).keys())

            st.markdown("#### Attach")
            a1, a2 = st.columns(2)
            with a1:
                hero = st.selectbox(
                    "Hero image (single, optional)",
                    options=[""] + image_choices,
                    index=([""] + image_choices).index(media_obj.get("hero_image", "")
                                                       ) if media_obj.get("hero_image", "") in image_choices else 0,
                    help="Shown prominently in app/PDF if used.",
                )
            with a2:
                gallery = st.multiselect(
                    "Gallery images",
                    options=image_choices,
                    default=[x for x in media_obj.get(
                        "gallery", []) if x in image_choices],
                )
            brochures = st.multiselect(
                "Brochures / PDFs",
                options=brochure_choices,
                default=[x for x in media_obj.get(
                    "brochures", []) if x in brochure_choices],
            )

            # Preview hero
            # Preview hero
            if hero:
                st.caption("Hero preview:")
                img_path = resolve_image_path(hero)
                if img_path:
                    st.image(img_path, width=250)
                else:
                    st.warning(f"Hero image not found on disk: {hero}")


            # --- Gallery thumbnails preview ---
            if gallery:
                st.caption("Gallery preview:")
                cols = st.columns(min(4, max(1, len(gallery))))
                for i, fname in enumerate(gallery):
                    fpath = resolve_image_path(fname)
                    with cols[i % len(cols)]:
                        if fpath and os.path.exists(fpath):
                            try:
                                with open(fpath, "rb") as f:
                                    img_bytes = f.read()
                                st.image(img_bytes, caption=fname, width=250)
                                st.download_button(
                                    "Download",
                                    data=img_bytes,
                                    file_name=fname,
                                    key=f"dl_img_{fname}",
                                )
                            except Exception:
                                st.warning(f"Error reading: {fname}")
                        else:
                            st.warning(f"Missing: {fname}")


            # --- Brochures list with download buttons ---
            if brochures:
                st.caption("Brochures:")
                for fname in brochures:
                    fpath = os.path.join(MEDIA_DIR, fname)
                    try:
                        size_kb = os.path.getsize(fpath) // 1024
                    except Exception:
                        size_kb = None

                    left, right = st.columns([3, 1])
                    with left:
                        meta = f"📄 {fname}" + \
                            (f"  ({size_kb} KB)" if size_kb is not None else "")
                        st.write(meta)
                    with right:
                        try:
                            with open(fpath, "rb") as f:
                                pdf_bytes = f.read()
                            st.download_button(
                                "Download PDF",
                                data=pdf_bytes,
                                file_name=fname,
                                mime="application/pdf",
                                key=f"dl_pdf_{fname}",
                            )
                        except Exception:
                            st.warning("Not found")

            if wide_button("💾 Save Media Attachments", type="primary"):
                media_obj["hero_image"] = hero
                media_obj["gallery"] = gallery
                media_obj["brochures"] = brochures

                # persist changes
                _write_json(CATALOG_FP, catalog)
                bump_data_version()
                st.success("Media saved.")

# -----------------------------
# Imports Tab
# -----------------------------
with TAB[5]:
    st.subheader("Imports & Normalization")
    st.write(
        "Drop CSV/JSON lists of models with free-text dimensions; we will normalize to app schema."
    )

    # --- Downloadable import templates (CSV + JSON) ---
    st.markdown("### Download import templates")

    # Columns that match the default mapper fields below
    tmpl_columns = ["make", "model", "category", "weight", "width", "depth", "height"]

    # Empty CSV with just headers
    tmpl_df = pd.DataFrame(columns=tmpl_columns)
    csv_bytes = tmpl_df.to_csv(index=False).encode("utf-8")

    # JSON example with one sample row
    json_template = [
        {
            "make": "TiDel",
            "model": "Series 4",
            "category": "smart_safe",
            "weight": "55 kg",
            "width": "300 mm",
            "depth": "520 mm",
            "height": "800 mm",
        }
    ]
    json_bytes = json.dumps(json_template, indent=2).encode("utf-8")

    c_t1, c_t2 = st.columns(2)
    with c_t1:
        st.download_button(
            "📄 Download CSV template",
            data=csv_bytes,
            file_name="model_import_template.csv",
            mime="text/csv",
            key="dl_csv_template",
        )
    with c_t2:
        st.download_button(
            "🧾 Download JSON template",
            data=json_bytes,
            file_name="model_import_template.json",
            mime="application/json",
            key="dl_json_template",
        )

    st.divider()
    st.markdown("### Upload file for import")

    # --- Upload & preview ---
    uploaded = st.file_uploader(
        "CSV or JSON", type=["csv", "json"], accept_multiple_files=False
    )
    raw = None  # will hold JSON content when needed

    if uploaded is not None:
        # Try to display raw
        if uploaded.type.endswith("json"):
            raw = json.load(uploaded)
            st.code(json.dumps(raw, indent=2)[:2000])
        else:
            df = pd.read_csv(uploaded)
            st.dataframe(df, **editor_width_kwargs(width='stretch'))

    # --- Field mapper ---
    with st.expander("Mapper", expanded=True):
        st.write("Tell the importer which fields are which. (Leave unused blank)")
        c1, c2, c3, c4, c5, c6 = st.columns(6)
        with c1:
            f_make = st.text_input("col: make", value="make")
        with c2:
            f_model = st.text_input("col: model", value="model")
        with c3:
            f_cat = st.text_input("col: category", value="category")
        with c4:
            f_w = st.text_input("col: weight", value="weight")
        with c5:
            f_width = st.text_input("col: width", value="width")
        with c6:
            f_depth = st.text_input("col: depth", value="depth")
        c7, c8 = st.columns(2)
        with c7:
            f_height = st.text_input("col: height", value="height")
        with c8:
            do_update = st.checkbox(
                "Update existing if keys match", value=True
            )

    # --- Import button ---
    if wide_button("📥 Import to Catalog", type="primary"):
        if uploaded is None:
            st.warning("Upload a file first.")
        else:
            try:
                if uploaded.type.endswith("json"):
                    data = raw if isinstance(raw, list) else raw.get("items", [])
                    df = pd.DataFrame(data)
                else:
                    uploaded.seek(0)
                    df = pd.read_csv(uploaded)
            except Exception as e:
                st.error(f"Failed to read file: {e}")
                st.stop()

            # Normalize each row
            imp_count = 0
            for _, r in df.iterrows():
                make = str(r.get(f_make, "")).strip()
                model = str(r.get(f_model, "")).strip()
                cat = str(r.get(f_cat, "")).strip() or "smart_safe"
                if not make or not model:
                    continue
                mk = slugify(make)
                mdlk = slugify(model)
                makes = catalog.setdefault("makes", {})
                m_entry = makes.setdefault(mk, {"label": make, "models": {}})
                mm = m_entry.setdefault("models", {})
                target = mm.get(mdlk)
                if target and not do_update:
                    continue
                kg, lb = parse_weight(str(r.get(f_w, "")))
                w_mm, w_in = parse_length(str(r.get(f_width, "")))
                d_mm, d_in = parse_length(str(r.get(f_depth, "")))
                h_mm, h_in = parse_length(str(r.get(f_height, "")))
                mm[mdlk] = _merge_model_record(
                    target,
                    label=model,
                    category=cat if cat in categories else "smart_safe",
                    dimensions={
                        "weight": fmt_weight(kg, lb),
                        "width": fmt_length(w_mm, w_in),
                        "depth": fmt_length(d_mm, d_in),
                        "height": fmt_length(h_mm, h_in),
                    },
                )
                imp_count += 1

            catalog = rebuild_derived_catalog_structures(catalog, categories)
            _write_json(CATALOG_FP, catalog)
            bump_data_version()
            st.success(f"Imported {imp_count} rows.")


# -----------------------------
# Settings Tab
# -----------------------------
with TAB[6]:
    st.subheader("System Settings")
    st.write("Branding, PDF header/footer, and media defaults.")

    s = settings

        # --- Load media index (image filenames) ---
    media_index_path = os.path.join("data", "media", "index.json")
    try:
        with open(media_index_path, "r", encoding="utf-8") as f:
            media_index = json.load(f)
    except Exception:
        media_index = {"images": {}}

    # Collect image files from BOTH index.json and the filesystem,
    # so "logo only" images still show up even if not attached to a model.
    exts = {".png", ".jpg", ".jpeg", ".webp"}
    try:
        fs_files = [
            f for f in os.listdir(MEDIA_DIR)
            if os.path.splitext(f)[1].lower() in exts
        ]
    except FileNotFoundError:
        fs_files = []

    index_files = list((media_index.get("images") or {}).keys())
    # Union of both sources
    image_files = sorted(set(fs_files) | set(index_files))


    with st.form("settings_form"):
        c1, c2 = st.columns(2)

        # Make sure these keys exist
        s.setdefault("branding", {})
        s.setdefault("media", {})
        s.pop("email", None)
        s.pop("smtp", None)

        with c1:
            s["branding"]["company_name"] = st.text_input(
                "Company name", value=s.get("branding", {}).get("company_name", "")
            )
            s["branding"]["pdf_header"] = st.text_input(
                "PDF Header", value=s.get("branding", {}).get("pdf_header", "")
            )

        with c2:
            s["branding"]["pdf_footer"] = st.text_input(
                "PDF Footer",
                value=s["branding"].get("pdf_footer", "")
            )

            # Safe handling of current hero image
            hero_current = s["media"].get("hero_image", "") or ""
            hero_options = [""] + image_files
            hero_index = hero_options.index(hero_current) if hero_current in hero_options else 0

            s["media"]["hero_image"] = st.selectbox(
                "Hero image (optional)",
                options=hero_options,
                index=hero_index,
            )

        submitted = st.form_submit_button("💾 Save Settings", type="primary")

    # --- Save Settings ONCE and rerun ---
    if submitted:
        _write_json(SETTINGS_FP, s)
        bump_data_version()
        st.success("Settings saved!")
        st.rerun()

    # --- Preview (outside the form) ---
    if s["media"].get("hero_image"):
        st.markdown("### Hero Image Preview")
        img_path = os.path.join(MEDIA_DIR, s["media"]["hero_image"])
        if os.path.exists(img_path):
            st.image(img_path, width=250)
        else:
            st.error(f"Image not found: {img_path}")

def build_data_bundle_zip() -> bytes:
    """
    Create an in-memory ZIP containing the entire ./data folder
    (JSON files + media). Used for backup/export so you can
    download and then commit to GitHub or move to another host.
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(DATA_DIR):
            for fname in files:
                full_path = os.path.join(root, fname)
                # Store paths inside the zip starting at "data/..."
                rel = os.path.relpath(full_path, DATA_DIR)
                arcname = os.path.join("data", rel)
                zf.write(full_path, arcname)
    buf.seek(0)
    return buf.getvalue()


# -----------------------------
# Share Links Tab
# -----------------------------
with TAB[7]:
    st.subheader("Share Links")
    st.write("Generate pre-filled survey links for a customer or a specific make/model.")

    customers = load_customers_config()
    customer_ids = [customer.get("id") for customer in customers if customer.get("id")]
    customer_lookup = {customer.get("id"): customer for customer in customers if customer.get("id")}
    makes_map = catalog.get("makes", {}) or {}

    base_url = st.text_input(
        "Base survey URL",
        value="https://yourapp.streamlit.app/",
        help="Used to generate the shareable link.",
    ).strip()

    link_mode = st.radio("Prefill type", ["Customer", "Make + Model"], horizontal=True)

    generated_url = ""
    if link_mode == "Customer":
        if customer_ids:
            customer_id = st.selectbox(
                "Customer",
                options=customer_ids,
                format_func=lambda cid: (customer_lookup.get(cid) or {}).get("name", cid),
                key="share_customer_id",
            )
            generated_url = f"{base_url}?customer={customer_id}"
        else:
            st.info("No customers found in data/customers.json.")
    else:
        make_keys = list(makes_map.keys())
        if make_keys:
            make_key = st.selectbox(
                "Make",
                options=make_keys,
                format_func=lambda k: ((makes_map.get(k) or {}).get("label", k)),
                key="share_make_key",
            )
            models_map = ((makes_map.get(make_key) or {}).get("models", {}) or {})
            model_keys = list(models_map.keys())
            model_key = st.selectbox(
                "Model",
                options=model_keys,
                format_func=lambda k: ((models_map.get(k) or {}).get("label", k)),
                key="share_model_key",
            ) if model_keys else None
            if model_key:
                make_label_value = ((makes_map.get(make_key) or {}).get("label", make_key))
                model_label_value = ((models_map.get(model_key) or {}).get("label", model_key))
                generated_url = f"{base_url}?make={make_label_value}&model={model_label_value}"
        else:
            st.info("No makes/models found in the catalog.")

    if generated_url:
        st.markdown("### Generated URL")
        st.code(generated_url, language="text")

        qr = qrcode.make(generated_url)
        qr_buf = io.BytesIO()
        qr.save(qr_buf, format="PNG")
        qr_buf.seek(0)
        st.markdown("### QR Code")
        st.image(qr_buf.getvalue(), width=220)

# -----------------------------
# Maintenance Tab
# -----------------------------
with TAB[8]:
    st.subheader("Maintenance")

    st.markdown("### All Drafts")
    all_drafts = SurveyDatabase(Config.DATABASE_PATH).list_all_drafts(limit=200)
    if all_drafts:
        draft_rows = [
            {
                "survey_id": survey_id,
                "user_id": user_id,
                "store_name": store_name,
                "make": make,
                "model": model,
                "updated_at": updated_at,
                "technician_name": technician_name,
            }
            for survey_id, user_id, store_name, make, model, updated_at, technician_name in all_drafts
        ]
        st.dataframe(pd.DataFrame(draft_rows), use_container_width=True)
    else:
        st.info("No drafts found.")

    if wide_button("🔎 Validate All", type="primary"):
        errs = []
        # Categories referenced by catalog
        for mk, mv in catalog.get("makes", {}).items():
            for mdlk, mdlv in mv.get("models", {}).items():
                cat = mdlv.get("category")
                if cat not in categories:
                    errs.append(
                        f"Model {mv.get('label')}/{mdlv.get('label')} has missing category '{cat}'.")
        # 2) Questions should reference valid cats/sections (ignore meta keys)
        QUESTIONS_META_KEYS = {
            "base_sections",
            "category_packs",
            "overrides",
            "question_bank",
            "profiles",
            "profile_defaults",
        }
        for ck, secmap in (questions or {}).items():
            if ck in QUESTIONS_META_KEYS:
                continue
            if ck not in categories:
                errs.append(f"Questions for missing category '{ck}'.")
                continue
            valid_secs = set(categories[ck].get("sections", []))
            for sec in (secmap or {}).keys():
                if sec not in valid_secs:
                    errs.append(f"Questions for '{ck}' reference unknown section '{sec}'.")
        if errs:
            st.error("\n".join(errs))
        else:
            st.success("All references valid.")

    st.divider()
    c1, c2 = st.columns([1, 1])
    with c1:
        if wide_button("🚀 Publish / Apply Changes", type="primary"):
            v = bump_data_version()
            st.success(f"Published (v{v['v']}). All caches cleared.")
    with c2:
        if wide_button("🧹 Clear Caches"):
            try:
                st.cache_data.clear()
            except Exception:
                pass
            st.success("Cleared Streamlit data caches.")
    st.caption("Tip: Commit the ./data folder to version control to track admin edits.")

    st.divider()
    st.markdown("### Export / Backup data folder")

    data_zip_bytes = build_data_bundle_zip()
    st.download_button(
        "📦 Download data.zip (catalog + questions + media)",
        data=data_zip_bytes,
        file_name="site_survey_data_bundle.zip",
        mime="application/zip",
    )
