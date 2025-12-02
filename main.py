import os
import datetime
import json
from typing import Any, Dict, List, Optional

import streamlit as st

from data_loader import (
    load_catalog,
    load_questions,
    load_lang,
    get_data_version,
    load_media_index,
)
from overrides import merge_overrides
from form_renderer import (
    apply_overrides as apply_field_overrides,
    render_section,
    seed_defaults,
    normalize_admin_fields,
)
from visible_if import is_visible as visible_if_field, evaluate as visible_if_eval
from pdf_builder import build_survey_pdf
from utils.images import process_survey_image
from questions import get_questions_for

# ---------------- App Config ----------------

# st.set_page_config(page_title="Site Survey Form", layout="centered")
st.set_page_config(
    page_title="Site Survey Form",
    layout="wide",
    initial_sidebar_state="expanded",
)
st.title("📋 Site Survey Form")

# --- Global session state initialization for survey answers + flags ---
if "form_data" not in st.session_state:
    st.session_state["form_data"] = {}
if "_current_model_key" not in st.session_state:
    st.session_state["_current_model_key"] = None
if "_show_required_errors" not in st.session_state:
    st.session_state["_show_required_errors"] = False
# For normalized + optimized photos used across UI + PDF
if "uploaded_photos" not in st.session_state:
    st.session_state["uploaded_photos"] = []

# Load data-driven resources
version = get_data_version()

# 🔁 Always rebuild media index so index.json matches assets/ + data/media
media_index = load_media_index()

catalog = load_catalog(version)
qdef = load_questions(version)
lang_map = load_lang("en", version)

# --- Load Settings (branding + logo) ---
SETTINGS_FP = os.path.join("data", "settings.json")


def load_settings():
    try:
        with open(SETTINGS_FP, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"branding": {}, "media": {}}


def _hero_path(filename: str | None):
    """
    Resolve a hero image filename to an absolute OS path.
    Works locally AND on Streamlit Cloud.
    """
    if not filename:
        return None

    filename = filename.strip()
    base = os.path.basename(filename)

    # Local dev paths
    local_paths = [
        os.path.join("data", "media", base),
        os.path.join("assets", base),
    ]

    # Streamlit Cloud mount paths
    cloud_paths = [
        os.path.join("/mount/src/site_survey/data/media", base),
        os.path.join("/mount/src/site_survey/assets", base),
        os.path.join("/mount/src/data/media", base),
    ]

    # Direct path provided?
    if os.path.isabs(filename) and os.path.exists(filename):
        return filename

    # Try Local
    for p in local_paths:
        if os.path.exists(p):
            return p

    # Try Cloud-mounted paths
    for p in cloud_paths:
        if os.path.exists(p):
            return p

    # Not found — still return local path where it SHOULD be
    return local_paths[0]


settings = load_settings()

# Extract the selected hero/logo file
settings_logo = settings.get("media", {}).get("hero_image", "")
settings_logo_path = _hero_path(settings_logo)

# --- Equipment Selection (Make → Model; Category derived from model) ---
st.subheader(f"1. {lang_map.get('section.site_info', 'Site Information')}")

# New admin structure: catalog["makes"][make_key] -> {"label", "models": {...}}
makes_map: Dict[str, Dict[str, Any]] = catalog.get("makes", {}) or {}


def make_label(k: str) -> str:
    return (makes_map.get(k) or {}).get("label", k)


def model_label(mk: str, mdk: str) -> str:
    return ((makes_map.get(mk) or {}).get("models", {}).get(mdk) or {}).get(
        "label", mdk
    )


def normalize_category(c: str) -> str:
    if not c:
        return ""
    slug = str(c).strip().lower().replace("-", "_")
    mapping = {
        "smart_safe": "Smart Safe",
        "smart safe": "Smart Safe",
        "recycler": "Recycler",
        "dispenser": "Dispenser",
        "note_sorter": "Note Sorter",
        "note sorter": "Note Sorter",
    }
    if slug in mapping:
        return mapping[slug]
    # Fallback: Title Case derived from slug
    return " ".join(w.capitalize() for w in slug.replace("_", " ").split())


# Make selector
make_key = (
    st.selectbox(
        "Make",
        options=list(makes_map.keys()),
        format_func=lambda k: make_label(k),
        key="make_sel",
    )
    if makes_map
    else None
)

# Model selector scoped to make
models_map_for_make: Dict[str, Dict[str, Any]] = (
    makes_map.get(make_key) or {}
).get("models", {}) if make_key else {}
model_key = (
    st.selectbox(
        "Model",
        options=list(models_map_for_make.keys()),
        format_func=lambda k: model_label(make_key, k),
        key="model_sel",
    )
    if models_map_for_make
    else None
)

# Pull selected model meta + derive category
selected_model: Dict[str, Any] = (
    models_map_for_make.get(model_key) or {} if model_key else {}
)
# e.g., "smart_safe", "recycler", etc.
category = normalize_category(selected_model.get("category", ""))
make = make_label(make_key) if make_key else None
model = model_label(make_key, model_key) if model_key else None
model_meta: Dict[str, Any] = selected_model

# Guard against None selections
if not (make and model):
    st.info("Select a Make, then Model. Category is derived automatically.")
    model_key = None
    model_meta = {}
else:
    # model_key and model_meta already set above
    pass

# Dimensions and hero image
model_dims = model_meta.get("dimensions", {}) if model_meta else {}
model_weight = model_dims.get("weight", "")
model_width = model_dims.get("width", "")
model_depth = model_dims.get("depth", "")
model_height = model_dims.get("height", "")
# New admin media placement:
media = model_meta.get("media", {}) or {}
hero_image = media.get("hero_image") or model_meta.get(
    "hero_image"
)  # support legacy field if present

image_path = _hero_path(hero_image)

# Equipment info display
st.markdown(f"**Weight:** {model_weight}")
st.markdown(f"**Width:** {model_width}")
st.markdown(f"**Depth:** {model_depth}")
st.markdown(f"**Height:** {model_height}")

# ✅ Responsive hero image without breaking st.image
st.markdown(
    """
<style>
.hero-wrap {
  display: flex;
  justify-content: center;
  margin: 1rem 0;
}
.hero-wrap img {
  display: block;
  width: 100% !important;
  height: auto !important;
  max-width: 600px !important;  /* hard cap on desktop */
}

/* Phone */
@media (max-width: 480px) {
  .hero-wrap img {
    max-width: 95vw !important;
  }
}

/* Tablet */
@media (min-width: 481px) and (max-width: 1024px) {
  .hero-wrap img {
    max-width: 480px !important;
  }
}
</style>
""",
    unsafe_allow_html=True,
)

if image_path and os.path.exists(image_path):
    st.markdown('<div class="hero-wrap">', unsafe_allow_html=True)
    # hard cap the width; Streamlit will scale down, not up
    st.image(image_path, caption=f"{make} {model}", width=600)
    st.markdown("</div>", unsafe_allow_html=True)

# Prepare composed sections for current selection
base_sections = qdef.get("base_sections", [])
category_sections = (qdef.get("category_packs", {}) or {}).get(category, []) or []
sections_composed = base_sections + category_sections

# Merge overrides and apply to sections
merged = merge_overrides(qdef, category=category, make=make, model=model)
sections_used = apply_field_overrides(sections_composed, merged)

# ---- Inject Admin-defined fields (Category -> "Delivery") into the composed sections ----


def _to_cat_key(label: str, model_meta: Dict[str, Any]) -> str:
    # Prefer the original model-provided category slug if present (e.g., "smart_safe")
    raw = (model_meta or {}).get("category")
    if isinstance(raw, str) and raw.strip():
        return raw.strip().lower().replace("-", "_")
    # Fallback from normalized Category label ("Smart Safe" -> "smart_safe")
    return (label or "").strip().lower().replace("-", "_").replace(" ", "_")


cat_key = _to_cat_key(category, model_meta)

# -------------------------
# Inject Admin-defined fields per section
# -------------------------

# 1) Delivery: combine category + model-specific admin questions
admin_questions_delivery = get_questions_for(
    qdef,
    category_key=cat_key,
    section_name="Delivery",
    make_key=make_key,
    model_key=model_key,
)
admin_fields_delivery = normalize_admin_fields(cat_key, "Delivery", admin_questions_delivery)

if admin_fields_delivery:
    # For Smart Safe we prefer "smart_safe_additions"; otherwise fall back to delivery_base.
    target = None
    for sec in sections_used:
        if sec.get("key") == "smart_safe_additions":
            target = sec
            break
    if target is None:
        for sec in sections_used:
            if (
                sec.get("key") == "delivery_base"
                or sec.get("title_key") == "section.delivery"
            ):
                target = sec
                break
    if target is not None:
        target.setdefault("fields", []).extend(admin_fields_delivery)

# 2) Installation: attach to the Installation Location section
admin_questions_install = get_questions_for(
    qdef,
    category_key=cat_key,
    section_name="Installation",
    make_key=make_key,
    model_key=model_key,
)
admin_fields_install = normalize_admin_fields(cat_key, "Installation", admin_questions_install)

if admin_fields_install:
    for sec in sections_used:
        if (
            sec.get("key") == "installation_location"
            or sec.get("title_key") == "section.installation_location"
        ):
            sec.setdefault("fields", []).extend(admin_fields_install)
            break

# On model change, seed defaults
curr_model_key = st.session_state.get("_current_model_key")
if curr_model_key != model_key:
    # reset error flag on model change
    st.session_state["_show_required_errors"] = False
    st.session_state["_current_model_key"] = model_key
    # seed defaults from overrides into canonical form_data
    seed_defaults(
        st.session_state["form_data"],
        merged.get("defaults", {}),
        overwrite_empty_only=True,
    )

# Working answers dict view backed by session_state.form_data
answers: Dict[str, Any] = st.session_state["form_data"]

def _normalize_exts(exts: list[str] | None) -> list[str]:
    """
    Normalize a list of file extensions:

    - Lowercase
    - Ensure each starts with '.'
    - De-duplicate
    """
    if not exts:
        return []
    seen = set()
    norm: list[str] = []
    for ext in exts:
        if not ext:
            continue
        e = ext.lower().strip()
        if not e:
            continue
        if not e.startswith("."):
            e = "." + e
        if e not in seen:
            seen.add(e)
            norm.append(e)
    return norm


# --- Upload Site Photos with rules ---
st.subheader("2. Upload Site Photos")

# Determine photo rules: use model.photo_rules, fallback to conservative defaults
rules = dict(model_meta.get("photo_rules", {}) or {})

max_count: int = int(rules.get("max_count", 20))
max_mb_each: float = float(rules.get("max_mb_each", 8))

raw_allowed_exts = rules.get("allowed_ext")
if not raw_allowed_exts:
    # Default: jpg + jpeg + png
    allowed_exts: List[str] = [".jpg", ".jpeg", ".png"]
else:
    # Normalize whatever was provided in config
    if isinstance(raw_allowed_exts, str):
        raw_allowed_exts = [raw_allowed_exts]
    allowed_exts = _normalize_exts(raw_allowed_exts)

# Convert to streamlit extension list without dot
st_types = [ext[1:] for ext in allowed_exts]

allowed_label = ", ".join(ext.lstrip(".").upper() for ext in allowed_exts)

photos_all = st.file_uploader(
    f"Upload up to {max_count} site photos",
    type=st_types,
    accept_multiple_files=True,
    help=f"Limit {max_mb_each:.0f}MB per file \u2022 {allowed_label}",
)

accepted_photos: List[Any] = []
optimized_photos: List[Dict[str, Any]] = []

if photos_all:
    too_many = len(photos_all) > max_count
    if too_many:
        st.error(
            f"Too many photos. {len(photos_all)} uploaded; maximum is {max_count}. Extra files will be ignored."
        )
    for photo in photos_all[:max_count]:
        # Validate extension
        name_lower = photo.name.lower()
        if not any(name_lower.endswith(ext) for ext in allowed_exts):
            st.error(
                f"File {photo.name} has an invalid extension. Allowed: {', '.join(allowed_exts)}"
            )
            continue
        # Validate size
        size_mb = (photo.size or 0) / (1024 * 1024)
        if size_mb > max_mb_each:
            st.error(
                f"File {photo.name} exceeds max size of {max_mb_each} MB (got {size_mb:.1f} MB)."
            )
            continue

        # Keep original upload reference for count/metadata
        accepted_photos.append(photo)

        # One-time orientation + resize + JPEG compression for storage/PDF.
        try:
            jpeg_bytes = process_survey_image(photo)
        except Exception:
            # If processing fails, fall back to raw bytes where possible so we still render something
            try:
                jpeg_bytes = photo.getvalue()  # type: ignore[assignment]
            except Exception:
                try:
                    jpeg_bytes = photo.read()  # type: ignore[assignment]
                except Exception:
                    jpeg_bytes = b""

        optimized_photos.append({"name": photo.name, "data": jpeg_bytes})
else:
    # If user clears the uploader, reset state
    accepted_photos = []
    optimized_photos = []

# Persist optimized photos (already oriented + compressed) in session state
st.session_state["uploaded_photos"] = optimized_photos

# Keep a simple reference in form_data answers (e.g., for names/metadata)
answers["photos"] = [p.get("name") for p in optimized_photos]

st.caption(f"{len(accepted_photos)} / {max_count} photos uploaded")

# Preview thumbnails using optimized images (JPEG bytes)
if optimized_photos:
    cols = st.columns(5)
    for i, photo_entry in enumerate(optimized_photos):
        img_bytes = photo_entry.get("data") or b""
        if not img_bytes:
            continue
        with cols[i % 5]:
            try:
                st.image(img_bytes, caption=photo_entry.get("name", ""), width=140)
            except Exception:
                # If preview fails for a specific image, just skip it
                pass

# --- Site Information ---
st.subheader(f"3. {lang_map.get('section.site_info', 'Site Information')}")
for _sec in sections_used:
    if _sec.get("key") == "site_info":
        # Remove any "Store Hours" style field from this section
        def _skip_store_hours(f):
            name = (f.get("name") or "").strip().lower()
            label = (
                lang_map.get(f.get("label_key") or "", f.get("label") or "") or ""
            ).strip().lower()
            return (
                name not in {"store_hours", "hours", "storehours"}
                and "store hours" not in label
            )

        sec_no_hours = dict(_sec)
        sec_no_hours["fields"] = [
            f for f in (_sec.get("fields") or []) if _skip_store_hours(f)
        ]

        render_section(
            sec_no_hours,
            answers,
            lang=lang_map,
            category=category,
            make=make,
            model=model,
            show_required_errors=bool(st.session_state.get("_show_required_errors")),
        )
        break

# --- Contact Info ---
st.subheader(f"4. {lang_map.get('section.contact_info', 'Contact Information')}")
for _sec in sections_used:
    if _sec.get("key") == "contact_info":
        render_section(
            _sec,
            answers,
            lang=lang_map,
            category=category,
            make=make,
            model=model,
            show_required_errors=bool(st.session_state.get("_show_required_errors")),
        )
        break

# --- Hours of Operation ---
st.subheader("5. Hours of Operation")

days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

# Default times and step for the time picker
DEFAULT_OPEN_TIME = datetime.time(8, 0)  # 08:00
DEFAULT_CLOSE_TIME = datetime.time(20, 0)  # 20:00 (8 PM)
TIME_STEP = datetime.timedelta(minutes=30)  # 30-minute increments

# ---------- Quick presets (optional) ----------
st.markdown("**Quick Setup (optional)**")

qp_cols = st.columns([1.3, 1.3, 1, 1])
with qp_cols[0]:
    same_weekdays = st.checkbox("Same hours Mon–Fri", key="same_weekdays")
with qp_cols[1]:
    weekend_closed = st.checkbox("Closed Sat & Sun", key="weekend_closed")
with qp_cols[2]:
    weekday_open = st.time_input(
        "Weekday open",
        value=DEFAULT_OPEN_TIME,
        key="weekday_open_preset",
        step=TIME_STEP,
    )
with qp_cols[3]:
    weekday_close = st.time_input(
        "Weekday close",
        value=datetime.time(17, 0),  # 5 PM typical
        key="weekday_close_preset",
        step=TIME_STEP,
    )

if st.button("Apply to selected days", key="apply_hours_presets"):
    # Apply Mon–Fri block
    if same_weekdays:
        for d in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]:
            st.session_state[f"open_{d}"] = weekday_open
            st.session_state[f"close_{d}"] = weekday_close
            st.session_state[f"closed_{d}"] = False
    # Close weekend
    if weekend_closed:
        for d in ["Saturday", "Sunday"]:
            st.session_state[f"closed_{d}"] = True

st.markdown("---")

# ---------- Per-day hours w/ Closed checkbox ----------
hours: Dict[str, Any] = {}

for day in days:
    open_key = f"open_{day}"
    close_key = f"close_{day}"
    closed_key = f"closed_{day}"

    # Seed defaults only once per session
    if open_key not in st.session_state:
        st.session_state[open_key] = DEFAULT_OPEN_TIME
    if close_key not in st.session_state:
        st.session_state[close_key] = DEFAULT_CLOSE_TIME
    # Default weekends to closed, weekdays to open
    if closed_key not in st.session_state:
        st.session_state[closed_key] = day in {"Saturday", "Sunday"}

    cols = st.columns([1.1, 0.9, 1.5, 1.5])

    with cols[0]:
        st.markdown(f"**{day}**")

    with cols[1]:
        closed = st.checkbox("Closed", key=closed_key)

    with cols[2]:
        open_time = st.time_input(
            f"Open {day}",
            key=open_key,
            step=TIME_STEP,
            disabled=closed,
        )

    with cols[3]:
        close_time = st.time_input(
            f"Close {day}",
            key=close_key,
            step=TIME_STEP,
            disabled=closed,
        )

    # Store a richer structure so PDF knows about "closed"
    hours[day] = {
        "open": None if closed else open_time,
        "close": None if closed else close_time,
        "closed": closed,
    }

answers["hours"] = hours

# --- Delivery Instructions ---
st.subheader(f"6. {lang_map.get('section.delivery', 'Delivery Instructions')}")
for _sec in sections_used:
    if _sec.get("key") in ("delivery_base", "smart_safe_additions"):
        render_section(
            _sec,
            answers,
            lang=lang_map,
            category=category,
            make=make,
            model=model,
            show_required_errors=bool(st.session_state.get("_show_required_errors")),
        )

# --- Additional Category Sections ---
for _sec in sections_used:
    if _sec.get("key") not in (
        "contact_info",
        "installation_location",
        "site_info",
        "delivery_base",
        "smart_safe_additions",
    ):
        sec_title = lang_map.get(_sec.get("title_key", ""), _sec.get("title", ""))
        if sec_title:
            st.subheader(sec_title)
        render_section(
            _sec,
            answers,
            lang=lang_map,
            category=category,
            make=make,
            model=model,
            show_required_errors=bool(st.session_state.get("_show_required_errors")),
        )

# --- Installation Location ---
st.subheader(
    f"7. {lang_map.get('section.installation_location', 'Installation Location')}"
)
for _sec in sections_used:
    if _sec.get("key") == "installation_location":
        render_section(
            _sec,
            answers,
            lang=lang_map,
            category=category,
            make=make,
            model=model,
            show_required_errors=bool(st.session_state.get("_show_required_errors")),
        )
        break

# ---------------- Submit -> Validate -> Build PDF ----------------


def _collect_missing_required(
    sections: List[Dict[str, Any]], state: Dict[str, Any]
) -> List[str]:
    missing: List[str] = []
    for sec in sections:
        for fld in sec.get("fields", []) or []:
            if not fld.get("required"):
                continue
            if not visible_if_field(fld, state, category, make, model):
                continue
            v = state.get(fld.get("name"))
            is_empty = (v is None) or (
                isinstance(v, str) and v.strip() == ""
            ) or (isinstance(v, list) and len(v) == 0)
            if is_empty:
                missing.append(fld.get("name"))
    return missing


if st.button("📄 Generate PDF"):
    # Merge collected inputs into session_state-based answers for validation
    validate_state = dict(st.session_state)
    validate_state.update(answers)

    missing_fields = _collect_missing_required(sections_used, validate_state)
    # Non-blocking: highlight missing but continue generating the report
    st.session_state["_show_required_errors"] = True if missing_fields else False
    if missing_fields:
        st.warning(
            "Some recommended fields are missing. The report will still be generated."
        )

    # Delegate PDF construction + filename logic to dedicated builder
    pdf_bytes, file_name = build_survey_pdf(
        answers=answers,
        sections_used=sections_used,
        hours=hours,
        validate_state=validate_state,
        make=make,
        model=model,
        model_weight=model_weight,
        model_width=model_width,
        model_depth=model_depth,
        model_height=model_height,
        image_path=image_path,
        settings_logo_path=settings_logo_path,
        # Use optimized photos (already oriented + resized + compressed)
        accepted_photos=st.session_state.get("uploaded_photos", []),
        max_count=max_count,
        lang_map=lang_map,
        category=category,
    )

    st.success(
        "PDF generated successfully. Please download it below and, once confirmed, email the PDF to your Area Manager."
    )
    st.download_button(
        label="📄 Download PDF Report",
        data=pdf_bytes,
        file_name=file_name,
        mime="application/pdf",
    )
