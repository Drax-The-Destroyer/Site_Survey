import os
import datetime
from io import BytesIO

import streamlit as st
from PIL import Image
from fpdf import FPDF
from fpdf.enums import XPos, YPos
from questions import FORM_DEFINITION
from form_renderer import apply_overrides, render_section

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


# ---------------- App Config ----------------
EQUIPMENT_CATALOG = {
    "TiDel": {
        "D3 w/Storage Vault": {
            "weight": "40 kg / 88 lbs",
            "width": "259 mm / 10.2 in",
            "depth": "482 mm / 19 in",
            "height": "705 mm / 27.75 in",
            "photo": "tidel_d3.png"
        },
        "D4": {
            "weight": "50 kg / 110 lbs",
            "width": "275 mm / 10.8 in",
            "depth": "500 mm / 19.7 in",
            "height": "730 mm / 28.7 in",
            "photo": "tidel_d4.png"
        }
    }
}

st.set_page_config(page_title="Site Survey Form", layout="centered")
st.title("📋 Site Survey Form")

# --- Equipment Selection ---
st.subheader("1. Select Equipment")
make = st.selectbox("Select Make", list(EQUIPMENT_CATALOG.keys()))
model = st.selectbox("Select Model", list(EQUIPMENT_CATALOG[make].keys()))
model_info = EQUIPMENT_CATALOG[make][model]
st.markdown(f"**Weight:** {model_info['weight']}")
st.markdown(f"**Width:** {model_info['width']}")
st.markdown(f"**Depth:** {model_info['depth']}")
st.markdown(f"**Height:** {model_info['height']}")
image_path = os.path.join("images", model_info["photo"])
if os.path.exists(image_path):
    st.image(image_path, caption=f"{make} {model}", width=480)

# Prepare data-driven sections and answers store
sections_used = apply_overrides(FORM_DEFINITION, make, model)
answers = {}

# --- Upload Site Photos ---
st.subheader("2. Upload Site Photos")
photos = st.file_uploader(
    "Upload up to 20 site photos",
    type=["jpg", "jpeg", "png"],
    accept_multiple_files=True
)
answers["photos"] = photos
if photos:
    for photo in photos[:20]:
        st.image(photo, caption=photo.name, width=140)

# --- Contact Info ---
st.subheader("3. Contact Information")
for _sec in sections_used:
    if _sec.get("title") == "Contact Information":
        render_section(_sec, answers)
        break

# --- Hours of Operation ---
st.subheader("4. Hours of Operation")
days = ["Monday", "Tuesday", "Wednesday",
        "Thursday", "Friday", "Saturday", "Sunday"]
hours = {}
for day in days:
    cols = st.columns(3)
    with cols[0]:
        st.markdown(f"**{day}**")
    with cols[1]:
        open_time = st.time_input(f"Open {day}", key=f"open_{day}")
    with cols[2]:
        close_time = st.time_input(f"Close {day}", key=f"close_{day}")
    hours[day] = (open_time, close_time)
answers["hours"] = hours

# --- Delivery Instructions ---
st.subheader("5. Delivery Instructions")
for _sec in sections_used:
    if _sec.get("title") == "Delivery Instructions":
        render_section(_sec, answers)
        break

# --- Installation Location ---
st.subheader("6. Installation Location")
for _sec in sections_used:
    if _sec.get("title") == "Installation Location":
        render_section(_sec, answers)
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
    # Use default thickness when not explicitly provided
    thickness = HR_THICK if thickness is None else thickness
    pad = HR_PAD

    if y is not None:
        pdf.set_y(y)

    # Proposed Y where the rule would be drawn (after top pad)
    y_pos = pdf.get_y() + pad
    bottom = pdf.h - pdf.b_margin

    # If the rule + bottom pad would exceed the usable page area, add a page first
    if y_pos + thickness + pad > bottom:
        pdf.add_page()
        y_pos = pdf.get_y() + pad

    x1 = pdf.l_margin
    x2 = pdf.w - pdf.r_margin
    r, g, b = LINE_GRAY
    pdf.set_draw_color(r, g, b)
    pdf.set_line_width(thickness)
    pdf.line(x1, y_pos, x2, y_pos)

    # Move cursor to just after the bottom pad so subsequent content starts below the rule
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
        o = fmt_time(open_t)
        c = fmt_time(close_t)
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

    # Measure (no drawing) so we can page-break cleanly if needed
    label_lines = _measure_lines(pdf, label_w, line_h, label_text)
    value_lines = _measure_lines(pdf, val_w, line_h, value_text)
    n_label = max(1, len(label_lines))
    n_value = max(1, len(value_lines))
    row_h = max(n_label, n_value) * line_h

    # Page break BEFORE drawing if the row won’t fit
    if y0 + row_h > (pdf.h - pdf.b_margin):
        pdf.add_page()
        x0 = pdf.l_margin
        y0 = pdf.get_y()

    # Draw LABEL
    pdf.set_font("Helvetica", "B", 11)
    set_text_color(pdf, DARK)
    pdf.set_xy(x0, y0)
    pdf.multi_cell(label_w, line_h, text=label_text,
                   new_x=XPos.LEFT, new_y=YPos.NEXT, align="L")

    # Draw VALUE at the same top Y
    pdf.set_font("Helvetica", "", 11)
    set_text_color(pdf, (0, 0, 0))
    pdf.set_xy(x0 + label_w + gap, y0)
    pdf.multi_cell(val_w, line_h, text=value_text,
                   new_x=XPos.LEFT, new_y=YPos.NEXT, align="L")

    # Advance to next row start
    pdf.set_xy(x0, y0 + row_h)


# ---------- Two pairs per line (for Equipment Info) with wrapping ----------


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
    dep_name = cond.get("field")
    expected = cond.get("equals")
    return answers.get(dep_name) == expected


def write_section_to_pdf_QA(pdf, section, answers, title_override=None, label_w=100):
    """
    Render a section as a sequence of two-column Q/A rows (or full-width textareas
    when a field has layout == "full"). This function reserves space at the end of
    the section for the trailing spacer + horizontal rule and will page-break
    beforehand if that block wouldn't fit.
    """
    section_header(pdf, title_override or section.get("title", ""))
    for field in section.get("fields", []):
        if not field_visible(field, answers):
            continue
        name = field.get("name") or ""
        label = field.get("label", name)
        ftype = field.get("type", "text")
        val = answers.get(name)

        # Allow a per-field flag to force full-width rendering (e.g., textareas)
        force_full = field.get("layout") == "full"

        if ftype == "textarea" and force_full:
            if val not in (None, "", []):
                para(pdf, label, val)
        else:
            kv_row_fixed_two_cells(pdf, label, val, label_w=label_w)

    # Reserve space for the spacer + rule; page-break first if needed
    thickness = HR_THICK
    need = SPACE_AFTER_BLOCK + HR_PAD + thickness + HR_PAD
    if pdf.get_y() + need > (pdf.h - pdf.b_margin):
        pdf.add_page()

    pdf.ln(SPACE_AFTER_BLOCK)
    draw_hr(pdf)


def write_contact_info(pdf, sections, answers):
    for sec in sections:
        if sec.get("title") == "Contact Information":
            section_header(pdf, "Contact Info")
            for field in sec.get("fields", []):
                if not field_visible(field, answers):
                    continue
                name = field.get("name") or ""
                label = field.get("label", name)
                ftype = field.get("type", "text")
                val = answers.get(name)
                if ftype == "textarea":
                    if val not in (None, "", []):
                        para(pdf, label, val)
                else:
                    kv_row_fixed_two_cells(pdf, label, val, label_w=90)
            pdf.ln(SPACE_AFTER_BLOCK)
            draw_hr(pdf)
            break


def render_debug_layout_demo(pdf):
    """
    Dev-only helper: render the 'Delivery/Installation QA – Stress' test section
    which contains a mix of short and long labels/values repeated to force page
    breaks. Use this to visually verify:
      - No row crosses a page boundary mid-row
      - HR lines never overlap content
      - Two-column rows align their values to the top of the label
    """
    # Build the stress section
    stress_section = {
        "title": "Delivery/Installation QA – Stress",
        "fields": []
    }

    # One group of fields as specified in the acceptance tests
    long_label = "This is a VERY long label intended to force wrapping across multiple lines to exercise label wrapping behaviour in the two-column layout"
    short_para = "This is a long paragraph answer intended to wrap across several lines so we can verify vertical alignment between the label and the value column. " \
                 "Repeat content to increase length. " * 3
    long_textarea = "Textarea content: " + \
        ("Lorem ipsum dolor sit amet, consectetur adipiscing elit. " * 6)

    # Create a single group
    group = [
        {"name": "s_short_1", "label": "Short A", "type": "text"},
        {"name": "s_short_2", "label": "Short B", "type": "text"},
        {"name": "s_short_3", "label": "Short C", "type": "text"},
        {"name": "s_long_label", "label": long_label, "type": "text"},
        {"name": "s_short_label_long_value", "label": "Notes", "type": "text"},
        {"name": "s_textarea_long", "label": "Comments",
            "type": "textarea", "layout": "full"},
    ]

    # Add multiple copies to force multiple pages
    copies = 6
    for i in range(copies):
        for fld in group:
            # clone with unique name/label to avoid collisions if desired
            fld_copy = fld.copy()
            fld_copy["name"] = f"{fld['name']}_{i}"
            stress_section["fields"].append(fld_copy)

    # Build answers to match the fields (mix short and long)
    answers = {}
    for i in range(copies):
        answers[f"s_short_1_{i}"] = "One"
        answers[f"s_short_2_{i}"] = "Two"
        answers[f"s_short_3_{i}"] = "Three"
        answers[f"s_long_label_{i}"] = "X"  # one-word answer for long label
        answers[f"s_short_label_long_value_{i}"] = short_para
        answers[f"s_textarea_long_{i}"] = long_textarea

    # Render the stress section using the existing writer (will respect full-width textareas)
    write_section_to_pdf_QA(pdf, stress_section, answers, label_w=100)


# ---------------- Submit -> Build PDF ----------------
if st.button("✅ Submit Survey"):
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # Title
    page_title(pdf, "Site Survey Report", f"Date: {datetime.date.today()}")

    # Smaller hero image
    try:
        if os.path.exists(image_path):
            center_image(pdf, image_path, max_w=85)
    except Exception:
        pass

    # --- Equipment Info (wrapped two-pair rows) ---
    section_header(pdf, "Equipment Info")
    dims = f"{model_info['width']} x {model_info['depth']} x {model_info['height']}"
    kv_row_two_pairs_wrapped(pdf, "Make", make, "Model", model, label_w=28)
    kv_row_two_pairs_wrapped(pdf, "Weight", model_info.get(
        "weight", ""), "Dimensions", dims, label_w=28)
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
    for _sec in sections_used:
        if _sec.get("title") == "Delivery Instructions":
            write_section_to_pdf_QA(
                pdf, _sec, answers, title_override="Delivery Instructions", label_w=100)
            break

    # --- Installation Details (clean fixed two-cell Q/A rows) ---
    ensure_glue(pdf, min_after=26)
    for _sec in sections_used:
        if _sec.get("title") == "Installation Location":
            write_section_to_pdf_QA(
                pdf, _sec, answers, title_override="Installation Details", label_w=100)
            break

    # --- Photos: one per page ---
    if photos:
        for photo in photos[:20]:
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
