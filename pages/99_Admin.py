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


# File: pages/10_Admin.py
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
from dataclasses import dataclass, asdict
from typing import Dict, List, Any, Optional, Tuple

import pandas as pd
import streamlit as st
from app.ui import wide_button


# Simple password (can be overridden by secrets or env later if you want)
def _get_admin_password(default="CashTech"):
    # Prefer env var (never throws)
    pwd = os.getenv("ADMIN_PASSWORD")
    if pwd:
        return pwd
    # Try Streamlit secrets, but guard to avoid StreamlitSecretNotFoundError
    try:
        return st.secrets["ADMIN_PASSWORD"]
    except Exception:
        return default

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
MEDIA_INDEX_FP = os.path.join(MEDIA_DIR, "index.json")
VERSION_FP = os.path.join(DATA_DIR, "version.json")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(MEDIA_DIR, exist_ok=True)

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


def ensure_unique(seq: List[str]) -> Tuple[bool, Optional[str]]:
    seen = set()
    for x in seq:
        if x in seen:
            return False, x
        seen.add(x)
    return True, None


def _as_str(x) -> str:
    try:
        return str(x).strip()
    except Exception:
        return ""


def _coerce_models_map(models_in) -> dict:
    """
    Accepts list|dict|None and returns dict: {model_key: {label, category, dimensions{...}}}
    """
    if isinstance(models_in, dict):
        return models_in
    out = {}
    if isinstance(models_in, list):
        for item in models_in:
            if isinstance(item, dict):
                label = _as_str(item.get("label") or item.get(
                    "name") or item.get("model") or "model")
                key = slugify(item.get("key") or label)
                category = _as_str(item.get("category")
                                   or item.get("cat") or "")
                dims_in = item.get("dimensions") or {}
                if not isinstance(dims_in, dict):
                    dims_in = {}
                out[key] = {
                    "label": label,
                    "category": category,
                    "dimensions": {
                        "weight": _as_str(dims_in.get("weight", "")),
                        "width":  _as_str(dims_in.get("width", "")),
                        "depth":  _as_str(dims_in.get("depth", "")),
                        "height": _as_str(dims_in.get("height", "")),
                    },
                }
            elif isinstance(item, str):
                key = slugify(item)
                out[key] = {"label": item, "category": "", "dimensions": {}}
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
        .setdefault(model_key, {"label": model_key, "category": "", "dimensions": {}})
    )


def _ensure_media(model_obj: dict) -> dict:
    media = model_obj.setdefault("media", {})
    media.setdefault("hero_image", "")
    media.setdefault("gallery", [])
    media.setdefault("brochures", [])
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

# --- NEW: normalize catalog.makes shape (list → dict) ---
original_makes = catalog.get("makes", {})
coerced_makes = _coerce_makes_map(original_makes)
if coerced_makes != original_makes:
    catalog["makes"] = coerced_makes
    catalog = rebuild_derived_catalog_structures(catalog, categories)
    _write_json(CATALOG_FP, catalog)
else:
    # Defensive: ensure legacy fields exist even if shape was already correct
    catalog = rebuild_derived_catalog_structures(catalog, categories)

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

TAB = st.tabs([
    "Catalog",
    "Categories & Sections",
    "Question Sets",
    "Media Library",
    "Imports",
    "Settings",
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
                        models[mkey] = {
                            "label": mdl_name.strip(),
                            "category": mdl_category,
                            "dimensions": {
                                "weight": fmt_weight(kg, lb),
                                "width": fmt_length(w_mm, w_in),
                                "depth": fmt_length(d_mm, d_in),
                                "height": fmt_length(h_mm, h_in),
                            },
                        }
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
                            new_models[key] = {
                                "label": label, "category": cat, "dimensions": dims}
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
# Categories & Sections Tab
# -----------------------------
with TAB[1]:
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
with TAB[2]:
    st.subheader("Question Sets Builder")
    st.write("Define fields by Category → Section. Types: text, textarea, number, select, multiselect, radio, time, checkbox, file. Use visible_if to show conditionally.")

    cat_keys = list(categories.keys())
    if not cat_keys:
        st.info("Create at least one category first.")
    else:
        c1, c2 = st.columns(2)
        with c1:
            cat_sel = st.selectbox(
                "Category", options=cat_keys, format_func=lambda k: categories[k]["label"])
        with c2:
            sec_options = categories[cat_sel].get("sections", [])
            sec_sel = st.selectbox("Section", options=sec_options)

        q_list: List[Dict[str, Any]] = questions.setdefault(
            cat_sel, {}).setdefault(sec_sel, [])

        # New question form
        with st.form("add_q"):
            q_label = st.text_input("Question label")
            q_key = st.text_input("Key", value=slugify(q_label))
            q_type = st.selectbox("Type", options=[
                                  "text", "textarea", "number", "select", "multiselect", "radio", "time", "checkbox", "file"])
            q_required = st.checkbox("Required", value=False)
            colx, coly = st.columns(2)
            with colx:
                q_options = st.text_input(
                    "Options (comma-separated, for select/radio/multiselect)")
            with coly:
                q_visible_if = st.text_input(
                    "visible_if (JSON; e.g., {\"field\":\"dock\",\"equals\":\"Yes\"})")
            q_submit = st.form_submit_button("➕ Add Field", type="primary")
        if q_submit:
            if not q_key:
                st.warning("Key is required.")
            elif any(q.get("key") == q_key for q in q_list):
                st.error("Key already exists in this section.")
            else:
                new_q = {
                    "key": q_key,
                    "label": q_label or q_key,
                    "type": q_type,
                    "required": q_required,
                }
                if q_options.strip():
                    new_q["options"] = [o.strip()
                                        for o in q_options.split(",") if o.strip()]
                if q_visible_if.strip():
                    try:
                        new_q["visible_if"] = json.loads(q_visible_if)
                    except Exception as e:
                        st.error(f"Invalid JSON for visible_if: {e}")
                q_list.append(new_q)
                _write_json(QUESTIONS_FP, questions)
                bump_data_version()
                st.success("Field added.")

        # Editor
        if q_list:
            q_rows = []
            for it in q_list:
                q_rows.append({
                    "key": it.get("key", ""),
                    "Label": it.get("label", ""),
                    "Type": it.get("type", "text"),
                    "Required": bool(it.get("required", False)),
                    "Options (comma)": ", ".join(it.get("options", [])) if isinstance(it.get("options"), list) else "",
                    "visible_if (JSON)": json.dumps(it.get("visible_if")) if isinstance(it.get("visible_if"), dict) else "",
                })
            df = pd.DataFrame(q_rows)
            edited = st.data_editor(
                df,
                **editor_width_kwargs(width='stretch'),
                hide_index=True,
                column_config={
                    "Type": st.column_config.SelectboxColumn(options=["text", "textarea", "number", "select", "multiselect", "radio", "time", "checkbox", "file"]),
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
                            r.get("Label", "field"))
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
                            item["options"] = [o.strip()
                                               for o in opts.split(",") if o.strip()]
                        vis = str(r.get("visible_if (JSON)", "")).strip()
                        if vis:
                            try:
                                item["visible_if"] = json.loads(vis)
                            except Exception as e:
                                st.error(
                                    f"Invalid visible_if JSON on {k}: {e}")
                                st.stop()
                        new_list.append(item)
                    questions.setdefault(cat_sel, {})[sec_sel] = new_list
                    _write_json(QUESTIONS_FP, questions)
                    bump_data_version()
                    st.success("Saved.")
            with c2:
                if wide_button("🧪 Validate Section"):
                    st.success(
                        "Basic validation OK (unique keys & JSON parse).")
        else:
            st.info("No fields yet for this section.")

# -----------------------------
# Media Library Tab
# -----------------------------
with TAB[3]:
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
            if hero:
                st.caption("Hero preview:")
                try:
                    st.image(os.path.join(MEDIA_DIR, hero))
                except Exception:
                    st.warning(
                        "Hero image not found on disk; it is in index but missing on filesystem.")

            # --- Gallery thumbnails preview ---
            if gallery:
                st.caption("Gallery preview:")
                # up to 4 across
                cols = st.columns(min(4, max(1, len(gallery))))
                for i, fname in enumerate(gallery):
                    fpath = os.path.join(MEDIA_DIR, fname)
                    with cols[i % len(cols)]:
                        try:
                            with open(fpath, "rb") as f:
                                img_bytes = f.read()
                            # omit width/use_container_width to avoid deprecation warnings
                            st.image(img_bytes, caption=fname)
                            st.download_button(
                                "Download",
                                data=img_bytes,
                                file_name=fname,
                                key=f"dl_img_{fname}",
                            )
                        except Exception:
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
with TAB[4]:
    st.subheader("Imports & Normalization")
    st.write(
        "Drop CSV/JSON lists of models with free-text dimensions; we will normalize to app schema.")

    uploaded = st.file_uploader(
        "CSV or JSON", type=["csv", "json"], accept_multiple_files=False)
    if uploaded is not None:
        # Try to display raw
        if uploaded.type.endswith("json"):
            raw = json.load(uploaded)
            st.code(json.dumps(raw, indent=2)[:2000])
        else:
            df = pd.read_csv(uploaded)
            st.dataframe(df, **editor_width_kwargs(width='stretch'))

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
                "Update existing if keys match", value=True)

    if wide_button("📥 Import to Catalog", type="primary"):
        if uploaded is None:
            st.warning("Upload a file first.")
        else:
            try:
                if uploaded.type.endswith("json"):
                    data = raw if isinstance(
                        raw, list) else raw.get("items", [])
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
                mm[mdlk] = {
                    "label": model,
                    "category": cat if cat in categories else "smart_safe",
                    "dimensions": {
                        "weight": fmt_weight(kg, lb),
                        "width": fmt_length(w_mm, w_in),
                        "depth": fmt_length(d_mm, d_in),
                        "height": fmt_length(h_mm, h_in),
                    }
                }
                imp_count += 1
            catalog = rebuild_derived_catalog_structures(catalog, categories)
            _write_json(CATALOG_FP, catalog)
            bump_data_version()
            st.success(f"Imported {imp_count} rows.")

# -----------------------------
# Settings Tab
# -----------------------------
with TAB[5]:
    st.subheader("System Settings")
    st.write("Branding, PDF header/footer, and media defaults.")

    s = settings

    # --- Load media index (image filenames) ---
    media_index_path = os.path.join("data", "media", "index.json")
    try:
        with open(media_index_path, "r") as f:
            media_index = json.load(f)
    except:
        media_index = {"images": {}}

    image_files = list(media_index.get("images", {}).keys())

    with st.form("settings_form"):
        c1, c2 = st.columns(2)
        with c1:
            s["branding"]["company_name"] = st.text_input(
                "Company name", value=s.get("branding", {}).get("company_name", "")
            )
            s["branding"]["pdf_header"] = st.text_input(
                "PDF Header", value=s.get("branding", {}).get("pdf_header", "")
            )
        with c2:
            s["branding"]["pdf_footer"] = st.text_input(
                "PDF Footer", value=s.get("branding", {}).get("pdf_footer", "")
            )

            # NEW: Dropdown from Media Library images
            s["media"]["hero_image"] = st.selectbox(
                "Hero image (optional)",
                options=[""] + image_files,
                index=([""] + image_files).index(
                    s.get("media", {}).get("hero_image", "")
                ),
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



# -----------------------------
# Maintenance Tab
# -----------------------------
with TAB[6]:
    st.subheader("Maintenance")

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
        QUESTIONS_META_KEYS = {"base_sections", "category_packs", "overrides"}
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







