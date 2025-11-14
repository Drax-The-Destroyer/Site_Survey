from collections import defaultdict
import os
import datetime
from io import BytesIO
from typing import Any, Dict, List, Optional

import streamlit as st
from PIL import Image
from fpdf import FPDF
from fpdf.enums import XPos, YPos

from data_loader import (
    load_catalog,
    load_questions,
    load_lang,
    get_data_version,
)
from overrides import merge_overrides
from form_renderer import apply_overrides as apply_field_overrides, render_section, seed_defaults, normalize_admin_fields  # newly added helper
from visible_if import is_visible as visible_if_field, evaluate as visible_if_eval

# ---------------- Utilities ----------------


def sanitize(text):
    if not isinstance(text, str):
        text = "" if text is None else str(text)
    return (
        text.replace("–", "-")
        .replace("—", "-")
        .replace("“", "\"")
        .replace("”", "\"")
        .replace("’", "'")
        .encode("latin-1", errors="ignore")
        .decode("latin-1")
    )


def fmt_time(t):
    """Return HH:MM (no seconds) or '' if None/empty."""
    if not t:
        return ""
    try:
        return t.strftime("%H:%M")
    except Exception:
        s = str(t)
        return s[:5] if len(s) >= 5 else s


def fmt_time_or_dash(t):
    """Return HH:MM or '—' if empty/invalid."""
    try:
        if not t:
            return "—"
        return t.strftime("%H:%M")
    except Exception:
        return "—"


def nbsp_units(s: str) -> str:
    """
    Ensure units stay with their numbers by inserting non-breaking spaces (U+00A0).
    Applies to inches and pounds.
    """
    txt = (s or "")
    nbsp = "\u00A0"
    # Common units
    txt = txt.replace(" in", f"{nbsp}in")
    txt = txt.replace(" lb", f"{nbsp}lb")
    txt = txt.replace(" lbs", f"{nbsp}lbs")
    # Also handle uppercase variants
    txt = txt.replace(" IN", f"{nbsp}IN")
    txt = txt.replace(" LB", f"{nbsp}LB")
    txt = txt.replace(" LBS", f"{nbsp}LBS")
    return txt


# ---------------- App Config ----------------

# st.set_page_config(page_title="Site Survey Form", layout="centered")
st.set_page_config(page_title="Site Survey Form", layout="wide", initial_sidebar_state="expanded")
st.title("📋 Site Survey Form")

# Load data-driven resources
version = get_data_version()
catalog = load_catalog(version)
qdef = load_questions(version)
lang_map = load_lang("en", version)

# Language toggle (scaffold for future FR)
st.selectbox("Language", ["English"], index=0)

# --- Equipment Selection (Make → Model; Category derived from model) ---
st.subheader(f"1. {lang_map.get('section.site_info', 'Site Information')}")

# New admin structure: catalog["makes"][make_key] -> {"label", "models": {...}}
makes_map: Dict[str, Dict[str, Any]] = catalog.get("makes", {}) or {}


def make_label(k: str) -> str:
    return (makes_map.get(k) or {}).get("label", k)


def model_label(mk: str, mdk: str) -> str:
    return ((makes_map.get(mk) or {}).get("models", {}).get(mdk) or {}).get("label", mdk)


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
make_key = st.selectbox(
    "Make",
    options=list(makes_map.keys()),
    format_func=lambda k: make_label(k),
    key="make_sel",
) if makes_map else None

# Model selector scoped to make
models_map_for_make: Dict[str, Dict[str, Any]] = (
    makes_map.get(make_key) or {}).get("models", {}) if make_key else {}
model_key = st.selectbox(
    "Model",
    options=list(models_map_for_make.keys()),
    format_func=lambda k: model_label(make_key, k),
    key="model_sel",
) if models_map_for_make else None

# Pull selected model meta + derive category
selected_model: Dict[str, Any] = (
    models_map_for_make.get(model_key) or {}) if model_key else {}
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
    "hero_image")  # support legacy field if present


def _hero_path(h):
    if not h:
        return None
    h = str(h).replace("\\", "/")

    # Absolute path as-is if it exists
    if os.path.isabs(h) and os.path.exists(h):
        return h

    # If JSON already provides a rooted relative like assets/... or data/media/...
    rooted = h.lstrip("./")
    rooted_path = os.path.join(os.getcwd(), rooted)
    if h.startswith("assets/") or h.startswith("data/media/"):
        return rooted_path if os.path.exists(rooted_path) else rooted_path

    # Try common locations for bare filenames
    base = os.path.basename(h)
    candidates = [
        os.path.join("assets", base),
        os.path.join("data", "media", base),
    ]
    for p in candidates:
        if os.path.exists(p):
            return p

    # Fallback to first candidate (assets) even if missing, to keep previous behavior
    return candidates[0]


image_path = _hero_path(hero_image)


# Equipment info display
st.markdown(f"**Weight:** {model_weight}")
st.markdown(f"**Width:** {model_width}")
st.markdown(f"**Depth:** {model_depth}")
st.markdown(f"**Height:** {model_height}")

# (already resolved above)

# ✅ Responsive hero image without breaking st.image
st.markdown("""
<style>
.hero-wrap { display:flex; justify-content:center; }
.hero-wrap img {
  width: 100% !important;
  height: auto !important;
  display: block;
}
/* Phone */
@media (max-width: 480px) {
  .hero-wrap img { max-width: 95vw !important; }
}
/* Tablet */
@media (min-width: 481px) and (max-width: 1024px) {
  .hero-wrap img { max-width: 720px !important; }
}
/* Desktop+ */
@media (min-width: 1025px) {
  .hero-wrap img { max-width: 820px !important; }
}
</style>
""", unsafe_allow_html=True)

if image_path and os.path.exists(image_path):
    st.markdown('<div class="hero-wrap">', unsafe_allow_html=True)
    st.image(image_path, caption=f"{make} {model}")
    st.markdown('</div>', unsafe_allow_html=True)

# Prepare composed sections for current selection
base_sections = qdef.get("base_sections", [])
category_sections = (qdef.get("category_packs", {})
                     or {}).get(category, []) or []
sections_composed = base_sections + category_sections

# Merge overrides and apply to sections
merged = merge_overrides(qdef, category=category, make=make, model=model)
sections_used = apply_field_overrides(sections_composed, merged)

# ---- Inject Admin-defined fields (Category -> "Delivery") into the composed sections ----
# Derive cat_key in the same shape Admin uses as a top-level key in questions.json.
# Admin saves under lowercase slug with underscores (e.g., "smart_safe").
def _to_cat_key(label: str, model_meta: Dict[str, Any]) -> str:
    # Prefer the original model-provided category slug if present (e.g., "smart_safe")
    raw = (model_meta or {}).get("category")
    if isinstance(raw, str) and raw.strip():
        return raw.strip().lower().replace("-", "_")
    # Fallback from normalized Category label ("Smart Safe" -> "smart_safe")
    return (label or "").strip().lower().replace("-", "_").replace(" ", "_")

cat_key = _to_cat_key(category, model_meta)
admin_fields_delivery = normalize_admin_fields(cat_key, "Delivery", qdef)

if admin_fields_delivery:
    # Find a target section to receive these. For Smart Safe we prefer "smart_safe_additions",
    # otherwise we fall back to the base delivery block.
    target = None
    for sec in sections_used:
        if sec.get("key") == "smart_safe_additions":
            target = sec
            break
    if target is None:
        for sec in sections_used:
            if sec.get("key") == "delivery_base" or sec.get("title_key") == "section.delivery":
                target = sec
                break
    if target is not None:
        target.setdefault("fields", []).extend(admin_fields_delivery)

# On model change, seed defaults
curr_model_key = st.session_state.get("_current_model_key")
if curr_model_key != model_key:
    # reset error flag on model change
    st.session_state["_show_required_errors"] = False
    st.session_state["_current_model_key"] = model_key
    # seed defaults from overrides
    seed_defaults(st.session_state, merged.get(
        "defaults", {}), overwrite_empty_only=True)

# Working answers dict view on top of session_state
answers: Dict[str, Any] = {}

# --- Upload Site Photos with rules ---
st.subheader("2. Upload Site Photos")

# Determine photo rules: use model.photo_rules, fallback to conservative defaults
rules = dict(model_meta.get("photo_rules", {}) or {})

max_count: int = int(rules.get("max_count", 20))
max_mb_each: float = float(rules.get("max_mb_each", 8))
allowed_exts: List[str] = rules.get("allowed_ext", [".jpg", ".png"]) or []

# Convert to streamlit extension list without dot
st_types = [ext[1:] if ext.startswith(".") else ext for ext in allowed_exts]

photos_all = st.file_uploader(
    f"Upload up to {max_count} site photos",
    type=st_types,
    accept_multiple_files=True
)

accepted_photos: List[Any] = []
if photos_all:
    too_many = len(photos_all) > max_count
    if too_many:
        st.error(
            f"Too many photos. {len(photos_all)} uploaded; maximum is {max_count}. Extra files will be ignored.")
    for photo in photos_all[:max_count]:
        # Validate extension
        name_lower = photo.name.lower()
        if not any(name_lower.endswith(ext) for ext in allowed_exts):
            st.error(
                f"File {photo.name} has an invalid extension. Allowed: {', '.join(allowed_exts)}")
            continue
        # Validate size
        size_mb = (photo.size or 0) / (1024 * 1024)
        if size_mb > max_mb_each:
            st.error(
                f"File {photo.name} exceeds max size of {max_mb_each} MB (got {size_mb:.1f} MB).")
            continue
        accepted_photos.append(photo)

answers["photos"] = accepted_photos
st.caption(f"{len(accepted_photos)} / {max_count} photos uploaded")

# Preview thumbnails
if accepted_photos:
    cols = st.columns(5)
    for i, photo in enumerate(accepted_photos):
        with cols[i % 5]:
            try:
                st.image(photo, caption=photo.name, width=140)
            except Exception:
                pass

# --- Site Information ---
st.subheader(f"3. {lang_map.get('section.site_info', 'Site Information')}")
for _sec in sections_used:
    if _sec.get("key") == "site_info":
        # Remove any "Store Hours" style field from this section
        def _skip_store_hours(f):
            name = (f.get("name") or "").strip().lower()
            label = (lang_map.get(f.get("label_key") or "",
                     f.get("label") or "") or "").strip().lower()
            return name not in {"store_hours", "hours", "storehours"} and "store hours" not in label

        sec_no_hours = dict(_sec)
        sec_no_hours["fields"] = [f for f in (
            _sec.get("fields") or []) if _skip_store_hours(f)]

        render_section(
            sec_no_hours, answers, lang=lang_map, category=category, make=make, model=model,
            show_required_errors=bool(
                st.session_state.get('_show_required_errors'))
        )
        break


# --- Contact Info ---
st.subheader(
    f"4. {lang_map.get('section.contact_info', 'Contact Information')}")
for _sec in sections_used:
    if _sec.get("key") == "contact_info":
        render_section(_sec, answers, lang=lang_map, category=category, make=make, model=model,
                       show_required_errors=bool(st.session_state.get('_show_required_errors')))
        break

# --- Hours of Operation ---
st.subheader("5. Hours of Operation")

days = ["Monday", "Tuesday", "Wednesday",
        "Thursday", "Friday", "Saturday", "Sunday"]

# Default times and step for the time picker
DEFAULT_OPEN_TIME = datetime.time(8, 0)   # 08:00
DEFAULT_CLOSE_TIME = datetime.time(20, 0) # 20:00 (8 PM)
TIME_STEP = datetime.timedelta(minutes=30)  # 30-minute increments

hours: Dict[str, Any] = {}
for day in days:
    open_key = f"open_{day}"
    close_key = f"close_{day}"

    # Seed defaults only once per session
    if open_key not in st.session_state:
        st.session_state[open_key] = DEFAULT_OPEN_TIME
    if close_key not in st.session_state:
        st.session_state[close_key] = DEFAULT_CLOSE_TIME

    cols = st.columns(3)
    with cols[0]:
        st.markdown(f"**{day}**")
    with cols[1]:
        open_time = st.time_input(
            f"Open {day}",
            key=open_key,
            step=TIME_STEP,  # 30-min increments
        )
    with cols[2]:
        close_time = st.time_input(
            f"Close {day}",
            key=close_key,
            step=TIME_STEP,  # 30-min increments
        )

    hours[day] = (open_time, close_time)

answers["hours"] = hours


# --- Delivery Instructions ---
st.subheader(f"6. {lang_map.get('section.delivery', 'Delivery Instructions')}")
for _sec in sections_used:
    if _sec.get("key") in ("delivery_base", "smart_safe_additions"):
        render_section(_sec, answers, lang=lang_map, category=category, make=make, model=model,
                       show_required_errors=bool(st.session_state.get('_show_required_errors')))

# --- Additional Category Sections ---
for _sec in sections_used:
    if _sec.get("key") not in ("contact_info", "installation_location", "site_info", "delivery_base", "smart_safe_additions"):
        sec_title = lang_map.get(
            _sec.get("title_key", ""), _sec.get("title", ""))
        if sec_title:
            st.subheader(sec_title)
        render_section(_sec, answers, lang=lang_map, category=category, make=make, model=model,
                       show_required_errors=bool(st.session_state.get('_show_required_errors')))

# --- Installation Location ---
st.subheader(
    f"7. {lang_map.get('section.installation_location', 'Installation Location')}")
for _sec in sections_used:
    if _sec.get("key") == "installation_location":
        render_section(_sec, answers, lang=lang_map, category=category, make=make, model=model,
                       show_required_errors=bool(st.session_state.get('_show_required_errors')))
        break

# ---------------- PDF Helpers ----------------
GRAY = (230, 230, 230)
DARK = (60, 60, 60)
LIGHT = (120, 120, 120)
LINE_GRAY = (200, 200, 200)

H_SECTION = 8
H_ROW = 6.5
H_TABLE = 7
SPACE_AFTER_SEC = 1.2
SPACE_AFTER_BLOCK = 1.2
# Horizontal rule defaults (used by draw_hr and spacing checks)
HR_THICK = 0.4
HR_PAD = 2


def set_text_color(pdf, rgb):
    r, g, b = rgb
    pdf.set_text_color(r, g, b)


def set_fill_color(pdf, rgb):
    r, g, b = rgb
    pdf.set_fill_color(r, g, b)


def usable_width(pdf):
    return pdf.w - pdf.l_margin - pdf.r_margin


def remaining_height(pdf):
    return (pdf.h - pdf.b_margin) - pdf.get_y()


def ensure_space_for(pdf, height_needed: float):
    if remaining_height(pdf) < height_needed:
        pdf.add_page()


def ensure_space(pdf, needed):
    if remaining_height(pdf) < needed:
        pdf.add_page()


def ensure_glue(pdf, min_after=22):
    if remaining_height(pdf) < min_after:
        pdf.add_page()


def _measure_lines(pdf, w, h, text):
    """
    Return the lines that would be produced by multi_cell without drawing.

    Uses the modern fpdf2 API (dry_run=True, output="LINES") when available and
    falls back to the older split_only=True argument for compatibility with
    older fpdf2 releases.
    """
    try:
        return pdf.multi_cell(w, h, text=text, dry_run=True, output="LINES")
    except TypeError:
        # Older fpdf versions that still expect split_only
        return pdf.multi_cell(w, h, text=text, split_only=True)


def draw_hr(pdf, y=None, thickness=None):
    """
    Draw a horizontal rule, but guard against page-bottom collisions by
    pre-checking available vertical space and forcing a page-break if needed.

    - thickness: optional line thickness; if None the default HR_THICK is used.
    - HR_PAD is applied above and below the rule to avoid collisions.
    """
    thickness = HR_THICK if thickness is None else thickness
    pad = HR_PAD

    if y is not None:
        pdf.set_y(y)

    y_pos = pdf.get_y() + pad
    bottom = pdf.h - pdf.b_margin

    if y_pos + thickness + pad > bottom:
        pdf.add_page()
        y_pos = pdf.get_y() + pad

    x1 = pdf.l_margin
    x2 = pdf.w - pdf.r_margin
    r, g, b = LINE_GRAY
    pdf.set_draw_color(r, g, b)
    pdf.set_line_width(thickness)
    pdf.line(x1, y_pos, x2, y_pos)
    pdf.set_y(y_pos + pad)


def page_title(pdf, title, date_str):
    pdf.set_font("Helvetica", "B", 17)
    set_text_color(pdf, DARK)
    pdf.cell(0, 10, text=sanitize(title),
             new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
    pdf.set_font("Helvetica", "", 11)
    set_text_color(pdf, LIGHT)
    pdf.cell(0, 7, text=sanitize(date_str),
             new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
    pdf.ln(2)
    draw_hr(pdf)


def section_header(pdf, text):
    ensure_glue(pdf, min_after=24)
    set_fill_color(pdf, GRAY)
    set_text_color(pdf, DARK)
    pdf.set_font("Helvetica", "B", 12.5)
    pdf.cell(0, H_SECTION, text=sanitize(text), new_x=XPos.LMARGIN,
             new_y=YPos.NEXT, align="L", fill=True)
    pdf.ln(SPACE_AFTER_SEC)


def para(pdf, label, text, line_h=H_ROW):
    ensure_space_for(pdf, line_h * 2)
    pdf.set_font("Helvetica", "B", 11)
    set_text_color(pdf, DARK)
    pdf.cell(0, line_h, text=sanitize(f"{label.rstrip(':')}:"),
             new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="L")
    pdf.set_font("Helvetica", "", 11)
    set_text_color(pdf, (0, 0, 0))
    pdf.multi_cell(usable_width(pdf), line_h, text=sanitize("" if text is None else str(text)),
                   new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="L")


def hours_table(pdf, hours_dict):
    def _header():
        set_fill_color(pdf, GRAY)
        set_text_color(pdf, DARK)
        pdf.set_font("Helvetica", "B", 11)
        day_w, open_w, close_w = 40, 35, 35
        pdf.cell(day_w, H_TABLE, text="Day")
        pdf.cell(open_w, H_TABLE, text="Open")
        pdf.cell(close_w, H_TABLE, text="Close",
                 new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        return day_w, open_w, close_w

    ensure_space_for(pdf, H_TABLE * 2)
    day_w, open_w, close_w = _header()

    pdf.set_font("Helvetica", "", 11)
    set_text_color(pdf, (0, 0, 0))
    for day, (open_t, close_t) in hours_dict.items():
        if remaining_height(pdf) < (H_TABLE + 2):
            pdf.add_page()
            day_w, open_w, close_w = _header()
        o = fmt_time_or_dash(open_t)
        c = fmt_time_or_dash(close_t)
        pdf.cell(day_w, H_TABLE, text=sanitize(day))
        pdf.cell(open_w, H_TABLE, text=sanitize(o))
        pdf.cell(close_w, H_TABLE, text=sanitize(c),
                 new_x=XPos.LMARGIN, new_y=YPos.NEXT)


def center_image(pdf: FPDF, path: str, max_w: float = None, max_h: float = None, y_top: float = None):
    if not os.path.exists(path):
        return (0, 0)
    with Image.open(path) as img:
        w_img, h_img = img.size

    page_w, page_h = pdf.w, pdf.h
    usable_w = page_w - pdf.l_margin - pdf.r_margin

    if max_w is None:
        max_w = usable_w
    if max_h is None:
        max_h = page_h - pdf.t_margin - pdf.b_margin - 10

    scale = min(max_w / w_img, max_h / h_img)
    draw_w, draw_h = w_img * scale, h_img * scale

    if y_top is None:
        y_top = pdf.get_y()
    if y_top + draw_h > (page_h - pdf.b_margin):
        pdf.add_page()
        y_top = pdf.get_y()

    x = (page_w - draw_w) / 2.0
    pdf.image(path, x=x, y=y_top, w=draw_w, h=draw_h)
    pdf.ln(draw_h + 3)
    return (draw_w, draw_h)

# ---------- Two-cell Q/A row with fixed label column (LEFT aligned) ----------


def _label_with_punct(s: str) -> str:
    s = (s or "").rstrip()
    return s if s.endswith((':', '?')) else s + ':'


def kv_row_fixed_two_cells(pdf, label, value, label_w=100, line_h=H_ROW, gap=4):
    total_w = usable_width(pdf)
    x0 = pdf.l_margin
    y0 = pdf.get_y()
    val_w = max(0, total_w - label_w - gap)

    label_text = sanitize(_label_with_punct(label))
    value_text = sanitize("" if value is None else str(value))

    # Measure with the SAME fonts you will draw with
    pdf.set_font("Helvetica", "B", 11)
    label_lines = _measure_lines(pdf, label_w, line_h, label_text)

    pdf.set_font("Helvetica", "", 11)
    value_lines = _measure_lines(pdf, val_w, line_h, value_text)

    n_label = max(1, len(label_lines))
    n_value = max(1, len(value_lines))
    row_h = max(n_label, n_value) * line_h

    if y0 + row_h > (pdf.h - pdf.b_margin):
        pdf.add_page()
        x0 = pdf.l_margin
        y0 = pdf.get_y()

    # Draw label
    pdf.set_font("Helvetica", "B", 11)
    set_text_color(pdf, DARK)
    pdf.set_xy(x0, y0)
    pdf.multi_cell(label_w, line_h, text=label_text,
                   new_x=XPos.LEFT, new_y=YPos.NEXT, align="L")

    # Draw value
    pdf.set_font("Helvetica", "", 11)
    set_text_color(pdf, (0, 0, 0))
    pdf.set_xy(x0 + label_w + gap, y0)
    pdf.multi_cell(val_w, line_h, text=value_text,
                   new_x=XPos.LEFT, new_y=YPos.NEXT, align="L")

    # Lock the cursor to the calculated row height
    pdf.set_xy(x0, y0 + row_h)


def kv_row_two_col(pdf, label, value, col_w_label, col_w_value, line_h=5, gutter=4):
    # Save original position
    x0, y0 = pdf.get_x(), pdf.get_y()

    # --- Use identical fonts for measure + draw ---
    label_txt = sanitize("" if label is None else str(label))
    value_txt = sanitize("" if value is None else str(value))

    # Measure with the SAME fonts you will draw with
    pdf.set_font("Helvetica", "B", 10)
    try:
        label_lines = pdf.multi_cell(
            col_w_label, line_h, label_txt, dry_run=True, output="LINES")
    except TypeError:
        label_lines = pdf.multi_cell(
            col_w_label, line_h, label_txt, split_only=True)

    pdf.set_font("Helvetica", "", 10)
    try:
        value_lines = pdf.multi_cell(
            col_w_value, line_h, value_txt, dry_run=True, output="LINES")
    except TypeError:
        value_lines = pdf.multi_cell(
            col_w_value, line_h, value_txt, split_only=True)

    row_h = max(len(label_lines) or 1, len(value_lines) or 1) * line_h

    # Page-break BEFORE drawing if needed
    if y0 + row_h > pdf.h - pdf.b_margin:
        pdf.add_page()
        x0, y0 = pdf.get_x(), pdf.get_y()

    # Draw label
    pdf.set_xy(x0, y0)
    pdf.set_font("Helvetica", "B", 10)
    pdf.multi_cell(col_w_label, line_h, label_txt, align="L")

    # Draw value
    pdf.set_xy(x0 + col_w_label + gutter, y0)
    pdf.set_font("Helvetica", "", 10)
    pdf.multi_cell(col_w_value, line_h, value_txt, align="L")

    # Advance the cursor exactly one row
    pdf.set_xy(x0, y0 + row_h)


def _pair_block(pdf, x, y, col_w, label, value, label_w, line_h=H_ROW, gap=4):
    """Draw one label/value pair inside a column at (x,y) and return end y."""
    pdf.set_xy(x, y)
    pdf.set_font("Helvetica", "B", 11)
    set_text_color(pdf, DARK)
    pdf.multi_cell(label_w, line_h, text=sanitize(f"{label.rstrip(':')}:"),
                   new_x=XPos.LEFT, new_y=YPos.NEXT, align="L")
    y_label_end = pdf.get_y()

    pdf.set_xy(x + label_w + gap, y)
    pdf.set_font("Helvetica", "", 11)
    set_text_color(pdf, (0, 0, 0))
    pdf.multi_cell(col_w - label_w - gap, line_h,
                   text=sanitize("" if value is None else str(value)),
                   new_x=XPos.LEFT, new_y=YPos.NEXT, align="L")
    y_value_end = pdf.get_y()

    return max(y_label_end, y_value_end)


def kv_row_two_pairs_wrapped(pdf, l1, v1, l2, v2, label_w=28, gap_between_cols=10, inner_gap=4):
    """
    Render two label/value pairs on one line (left and right columns),
    each pair wraps within its own half of the page.
    """
    x_left = pdf.l_margin
    y_top = pdf.get_y()
    total_w = usable_width(pdf)
    col_w = (total_w - gap_between_cols) / 2.0
    x_right = x_left + col_w + gap_between_cols

    y_end_left = _pair_block(pdf, x_left, y_top, col_w,
                             l1, v1, label_w, gap=inner_gap)
    y_end_right = _pair_block(
        pdf, x_right, y_top, col_w, l2, v2, label_w, gap=inner_gap)

    pdf.set_xy(pdf.l_margin, max(y_end_left, y_end_right))


def field_visible(field, answers):
    cond = field.get("visible_if")
    if not cond:
        return True
    # Legacy support (kept for PDF logic that may still consult this)
    dep_name = cond.get("field")
    expected = cond.get("equals")
    return answers.get(dep_name) == expected


def write_section_to_pdf_QA(pdf, section, answers, title_override=None, label_w=100, render_header=True):
    """
    Render a section as a sequence of two-column Q/A rows (or full-width textareas
    when a field has layout == "full"). This function reserves space at the end of
    the section for the trailing spacer + horizontal rule and will page-break
    beforehand if that block wouldn't fit.
    """
    if render_header:
        section_header(pdf, title_override or section.get(
            "title", lang_map.get(section.get("title_key", ""), "")))
    # Precompute two-column widths
    total_w = usable_width(pdf)
    gutter = 4
    col_w_label = label_w
    col_w_value = max(0, total_w - col_w_label - gutter)
    for field in section.get("fields", []):
        # Use new DSL visibility if present, fallback to legacy
        vis = visible_if_eval(field.get("visible_if"), answers, category, make, model) if field.get(
            "visible_if") else field_visible(field, answers)
        if not vis:
            continue
        name = field.get("name") or ""
        label = lang_map.get(field.get("label_key"), field.get("label", name))
        ftype = field.get("type", "text")
        val = answers.get(name)

        force_full = field.get("layout") == "full"

        if ftype == "textarea" and force_full:
            if val not in (None, "", []):
                para(pdf, label, val)
        else:
            kv_row_two_col(pdf, label, val, col_w_label,
                           col_w_value, line_h=H_ROW, gutter=gutter)

    thickness = HR_THICK
    need = SPACE_AFTER_BLOCK + HR_PAD + thickness + HR_PAD
    if pdf.get_y() + need > (pdf.h - pdf.b_margin):
        pdf.add_page()

    pdf.ln(SPACE_AFTER_BLOCK)
    draw_hr(pdf)


def write_contact_info(pdf, sections, answers):
    for sec in sections:
        if sec.get("key") == "contact_info":
            section_header(pdf, "Contact Info")
            total_w = usable_width(pdf)
            gutter = 4
            col_w_label = 90
            col_w_value = max(0, total_w - col_w_label - gutter)
            for field in sec.get("fields", []):
                vis = visible_if_eval(field.get("visible_if"), answers, category, make, model) if field.get(
                    "visible_if") else field_visible(field, answers)
                if not vis:
                    continue
                name = field.get("name") or ""
                label = lang_map.get(field.get("label_key"),
                                     field.get("label", name))
                ftype = field.get("type", "text")
                val = answers.get(name)
                if ftype == "textarea":
                    if val not in (None, "", []):
                        para(pdf, label, val)
                else:
                    kv_row_two_col(pdf, label, val, col_w_label,
                                   col_w_value, line_h=H_ROW, gutter=gutter)
            pdf.ln(SPACE_AFTER_BLOCK)
            draw_hr(pdf)
            break


# ---------------- Submit -> Validate -> Build PDF ----------------

def _collect_missing_required(sections: List[Dict[str, Any]], state: Dict[str, Any]) -> List[str]:
    missing: List[str] = []
    for sec in sections:
        for fld in sec.get("fields", []) or []:
            if not fld.get("required"):
                continue
            if not visible_if_field(fld, state, category, make, model):
                continue
            v = state.get(fld.get("name"))
            is_empty = (v is None) or (isinstance(v, str) and v.strip() == "") or (
                isinstance(v, list) and len(v) == 0)
            if is_empty:
                missing.append(fld.get("name"))
    return missing


if st.button("✅ Submit Survey"):
    # Merge collected inputs into session_state-based answers for validation
    validate_state = dict(st.session_state)
    validate_state.update(answers)

    missing_fields = _collect_missing_required(sections_used, validate_state)
    # Non-blocking: highlight missing but continue generating the report
    st.session_state["_show_required_errors"] = True if missing_fields else False
    if missing_fields:
        st.warning(
            "Some recommended fields are missing. The report will still be generated.")

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    
    # --------------------------------------------------
    #  TOP-RIGHT LOGO
    # --------------------------------------------------
    try:
        if image_path and os.path.exists(image_path):
            # Position: 170mm from left (adjust for your page width)
            pdf.image(image_path, x=170, y=10, w=30)  # w=30 = good size for logo
    except Exception as e:
        print("Logo error:", e)
    
    # --------------------------------------------------
    #  TITLE (Centered)
    # --------------------------------------------------
    pdf.set_title("Site Survey Report")
    page_title(pdf, "Site Survey Report", f"Date: {datetime.date.today()}")


    # Smaller hero image
    try:
        if image_path and os.path.exists(image_path):
            center_image(pdf, image_path, max_w=85)
    except Exception:
        pass

    # Report body
    if True:
        # --- Equipment Info (wrapped two-pair rows) ---
        section_header(pdf, "Equipment Info")
        dims = f"{model_width} x {model_depth} x {model_height}"
        dims = nbsp_units(dims)
        kv_row_two_pairs_wrapped(pdf, "Make", make, "Model", model, label_w=28)
        kv_row_two_pairs_wrapped(
            pdf, "Weight", nbsp_units(model_weight), "Dimensions", dims, label_w=28)
        pdf.ln(SPACE_AFTER_BLOCK)
        draw_hr(pdf)

        # --- Contact Info ---
        write_contact_info(pdf, sections_used, answers)

        # --- Hours of Operation (no seconds) ---
        ensure_space(pdf, needed=90)
        section_header(pdf, "Hours of Operation")
        hours_table(pdf, hours)
        pdf.ln(SPACE_AFTER_BLOCK)
        draw_hr(pdf)

        # --- Delivery Instructions (clean fixed two-cell Q/A rows) ---
        ensure_glue(pdf, min_after=26)
        printed_delivery_header = False
        for _sec in sections_used:
            if _sec.get("key") in ("delivery_base", "smart_safe_additions"):
                write_section_to_pdf_QA(
                    pdf, _sec, answers, title_override="Delivery Instructions", label_w=100, render_header=(not printed_delivery_header)
                )
                printed_delivery_header = True
        # --- Installation Details (clean fixed two-cell Q/A rows) ---
        ensure_glue(pdf, min_after=26)
        for _sec in sections_used:
            if _sec.get("key") == "installation_location":
                write_section_to_pdf_QA(
                    pdf, _sec, answers, title_override="Installation Details", label_w=100
                )
                break

        # --- Photos: one per page ---
        if accepted_photos:
            for photo in accepted_photos[:max_count]:
                temp_path = None
                try:
                    pdf.add_page()
                    section_header(pdf, "Site Survey Photo")
                    img = Image.open(photo).convert("RGB")
                    temp_path = f"temp_{photo.name}.jpg"
                    img.save(temp_path, format="JPEG")
                    img.close()

                    y_top = pdf.get_y()
                    max_w = pdf.w - pdf.l_margin - pdf.r_margin
                    max_h = pdf.h - y_top - pdf.b_margin - 5
                    center_image(pdf, temp_path, max_w=max_w,
                                 max_h=max_h, y_top=y_top)
                except Exception:
                    pdf.set_font("Helvetica", "B", 11)
                    set_text_color(pdf, (200, 0, 0))
                    pdf.cell(0, H_ROW, text=sanitize(f"Error displaying image {photo.name}"),
                             new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                finally:
                    if temp_path and os.path.exists(temp_path):
                        os.remove(temp_path)

        # Footer
        pdf.set_y(-18)
        draw_hr(pdf, thickness=0.2)
        pdf.set_font("Helvetica", "I", 8)
        set_text_color(pdf, (90, 90, 90))
        pdf.cell(0, 8, text=sanitize("Generated by Site Survey App - Version 1.0 - © 2025"),
                 align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        # Streamlit download
        buf = BytesIO()
        pdf.output(buf)
        pdf_bytes = buf.getvalue()

        st.success("Survey submitted successfully! PDF is ready below.")
        st.download_button(
            label="📄 Download PDF Report",
            data=pdf_bytes,
            file_name="site_survey_report.pdf",
            mime="application/pdf",
        )




