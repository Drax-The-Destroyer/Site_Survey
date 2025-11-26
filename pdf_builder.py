import datetime
import os
from io import BytesIO
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image
from fpdf import FPDF
from fpdf.enums import XPos, YPos

from visible_if import is_visible as visible_if_field, evaluate as visible_if_eval


def sanitize(text: Any) -> str:
    """
    Normalize text for PDF output, stripping unsupported characters and
    normalizing common punctuation.
    """
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


def normalize_model_for_filename(text: str) -> str:
    """
    Clean up model text for filenames:
    - expand w/ and w/o
    - collapse extra spaces
    """
    txt = (text or "").strip()
    if not txt:
        return ""
    txt = txt.replace("w/o", "without")
    txt = txt.replace("w/", "with")
    return " ".join(txt.split())


def make_filename_safe(text: str) -> str:
    """
    Remove characters that are illegal/annoying in filenames and normalize spaces.
    """
    txt = (text or "").strip()
    if not txt:
        return ""
    bad_chars = '<>:"/\\|?*'
    for ch in bad_chars:
        txt = txt.replace(ch, " ")
    # collapse multiple spaces
    txt = " ".join(txt.split())
    return txt


def truncate_for_filename(text: str, max_len: int = 40) -> str:
    """
    Truncate text for filenames to a max length.
    Tries to cut at a word boundary and adds '...' if truncated.
    """
    txt = (text or "").strip()
    if len(txt) <= max_len:
        return txt
    cut = txt[:max_len]
    # Try to cut on a space so we don't chop mid-word
    last_space = cut.rfind(" ")
    if last_space > 10:
        cut = cut[:last_space]
    return cut + "..."


def get_store_name(state: Dict[str, Any]) -> str:
    """
    Prefer the explicit store_name field (it's required in questions.json).
    Keep a tiny fallback just in case the schema changes later.
    """
    val = state.get("store_name")
    if isinstance(val, str) and val.strip():
        return val.strip()

    # Tiny fallback if config ever changes
    for key in ("site_name", "location_name", "store"):
        v = state.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()

    return ""


def fmt_time_or_dash(t: Any) -> str:
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


# ---------------- PDF Layout Constants ----------------

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


def set_text_color(pdf: FPDF, rgb: Tuple[int, int, int]) -> None:
    r, g, b = rgb
    pdf.set_text_color(r, g, b)


def set_fill_color(pdf: FPDF, rgb: Tuple[int, int, int]) -> None:
    r, g, b = rgb
    pdf.set_fill_color(r, g, b)


def usable_width(pdf: FPDF) -> float:
    return pdf.w - pdf.l_margin - pdf.r_margin


def remaining_height(pdf: FPDF) -> float:
    return (pdf.h - pdf.b_margin) - pdf.get_y()


def ensure_space_for(pdf: FPDF, height_needed: float) -> None:
    if remaining_height(pdf) < height_needed:
        pdf.add_page()


def ensure_space(pdf: FPDF, needed: float) -> None:
    if remaining_height(pdf) < needed:
        pdf.add_page()


def ensure_glue(pdf: FPDF, min_after: float = 22) -> None:
    if remaining_height(pdf) < min_after:
        pdf.add_page()


def _measure_lines(pdf: FPDF, w: float, h: float, text: str):
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


def draw_hr(pdf: FPDF, y: Optional[float] = None, thickness: Optional[float] = None) -> None:
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


def page_title(pdf: FPDF, title: str, date_str: str, logo_path: Optional[str] = None) -> None:
    """
    Draw page title + date, with optional company logo in the top-right.
    """
    # Draw logo top-right
    if logo_path and os.path.exists(logo_path):
        try:
            logo_w = 32  # adjust as needed
            x_pos = pdf.w - pdf.r_margin - logo_w
            y_pos = pdf.get_y() + 2
            pdf.image(logo_path, x=x_pos, y=y_pos, w=logo_w)
        except Exception as e:  # pragma: no cover - defensive logging
            print("Logo draw error:", e)

    # Title text aligned left (not centered)
    pdf.set_font("Helvetica", "B", 17)
    set_text_color(pdf, DARK)
    pdf.cell(
        0,
        10,
        text=sanitize(title),
        new_x=XPos.LMARGIN,
        new_y=YPos.NEXT,
        align="L",
    )

    # Date under it
    pdf.set_font("Helvetica", "", 11)
    set_text_color(pdf, LIGHT)
    pdf.cell(
        0,
        7,
        text=sanitize(date_str),
        new_x=XPos.LMARGIN,
        new_y=YPos.NEXT,
        align="L",
    )

    pdf.ln(2)
    draw_hr(pdf)


def section_header(pdf: FPDF, text: str) -> None:
    ensure_glue(pdf, min_after=24)
    set_fill_color(pdf, GRAY)
    set_text_color(pdf, DARK)
    pdf.set_font("Helvetica", "B", 12.5)
    pdf.cell(
        0,
        H_SECTION,
        text=sanitize(text),
        new_x=XPos.LMARGIN,
        new_y=YPos.NEXT,
        align="L",
        fill=True,
    )
    pdf.ln(SPACE_AFTER_SEC)


def para(pdf: FPDF, label: str, text: Any, line_h: float = H_ROW) -> None:
    ensure_space_for(pdf, line_h * 2)
    pdf.set_font("Helvetica", "B", 11)
    set_text_color(pdf, DARK)
    pdf.cell(
        0,
        line_h,
        text=sanitize(f"{label.rstrip(':')}:"),
        new_x=XPos.LMARGIN,
        new_y=YPos.NEXT,
        align="L",
    )
    pdf.set_font("Helvetica", "", 11)
    set_text_color(pdf, (0, 0, 0))
    pdf.multi_cell(
        usable_width(pdf),
        line_h,
        text=sanitize("" if text is None else str(text)),
        new_x=XPos.LMARGIN,
        new_y=YPos.NEXT,
        align="L",
    )


def hours_table(pdf: FPDF, hours_dict: Dict[str, Any]) -> None:
    def _header() -> Tuple[float, float, float]:
        set_fill_color(pdf, GRAY)
        set_text_color(pdf, DARK)
        pdf.set_font("Helvetica", "B", 11)
        day_w, open_w, close_w = 40, 35, 35
        pdf.cell(day_w, H_TABLE, text="Day")
        pdf.cell(open_w, H_TABLE, text="Open")
        pdf.cell(
            close_w,
            H_TABLE,
            text="Close",
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )
        return day_w, open_w, close_w

    ensure_space_for(pdf, H_TABLE * 2)
    day_w, open_w, close_w = _header()

    pdf.set_font("Helvetica", "", 11)
    set_text_color(pdf, (0, 0, 0))

    for day, val in hours_dict.items():
        # Support both legacy (open_t, close_t) tuple and new dict structure
        if isinstance(val, dict):
            closed = bool(val.get("closed", False))
            open_t = val.get("open")
            close_t = val.get("close")
        else:
            # Old style: (open, close)
            try:
                open_t, close_t = val
            except Exception:
                open_t, close_t = None, None
            closed = not (open_t or close_t)

        if remaining_height(pdf) < (H_TABLE + 2):
            pdf.add_page()
            day_w, open_w, close_w = _header()

        if closed:
            o = "Closed"
            c = "Closed"
        else:
            o = fmt_time_or_dash(open_t)
            c = fmt_time_or_dash(close_t)

        pdf.cell(day_w, H_TABLE, text=sanitize(day))
        pdf.cell(open_w, H_TABLE, text=sanitize(o))
        pdf.cell(
            close_w,
            H_TABLE,
            text=sanitize(c),
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )


def center_image(
    pdf: FPDF,
    path: str,
    max_w: Optional[float] = None,
    max_h: Optional[float] = None,
    y_top: Optional[float] = None,
) -> Tuple[float, float]:
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


# ---------- Two-cell Q/A helpers ----------


def _label_with_punct(s: str) -> str:
    s = (s or "").rstrip()
    return s if s.endswith((":", "?")) else s + ":"


def kv_row_fixed_two_cells(
    pdf: FPDF,
    label: str,
    value: Any,
    label_w: float = 100,
    line_h: float = H_ROW,
    gap: float = 4,
) -> None:
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
    pdf.multi_cell(
        label_w,
        line_h,
        text=label_text,
        new_x=XPos.LEFT,
        new_y=YPos.NEXT,
        align="L",
    )

    # Draw value
    pdf.set_font("Helvetica", "", 11)
    set_text_color(pdf, (0, 0, 0))
    pdf.set_xy(x0 + label_w + gap, y0)
    pdf.multi_cell(
        val_w,
        line_h,
        text=value_text,
        new_x=XPos.LEFT,
        new_y=YPos.NEXT,
        align="L",
    )

    # Lock the cursor to the calculated row height
    pdf.set_xy(x0, y0 + row_h)


def kv_row_two_col(
    pdf: FPDF,
    label: str,
    value: Any,
    col_w_label: float,
    col_w_value: float,
    line_h: float = 5,
    gutter: float = 4,
) -> None:
    # Save original position
    x0, y0 = pdf.get_x(), pdf.get_y()

    # --- Use identical fonts for measure + draw ---
    label_txt = sanitize("" if label is None else str(label))

    # Format values nicely:
    if isinstance(value, (list, tuple, set)):
        value_txt = ", ".join(sanitize(str(v)) for v in value)
    else:
        value_txt = sanitize("" if value is None else str(value))


    # Measure with the SAME fonts you will draw with
    pdf.set_font("Helvetica", "B", 10)
    try:
        label_lines = pdf.multi_cell(
            col_w_label, line_h, label_txt, dry_run=True, output="LINES"
        )
    except TypeError:
        label_lines = pdf.multi_cell(
            col_w_label, line_h, label_txt, split_only=True
        )

    pdf.set_font("Helvetica", "", 10)
    try:
        value_lines = pdf.multi_cell(
            col_w_value, line_h, value_txt, dry_run=True, output="LINES"
        )
    except TypeError:
        value_lines = pdf.multi_cell(
            col_w_value, line_h, value_txt, split_only=True
        )

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


def _pair_block(
    pdf: FPDF,
    x: float,
    y: float,
    col_w: float,
    label: str,
    value: Any,
    label_w: float,
    line_h: float = H_ROW,
    gap: float = 4,
) -> float:
    """Draw one label/value pair inside a column at (x,y) and return end y."""
    pdf.set_xy(x, y)
    pdf.set_font("Helvetica", "B", 11)
    set_text_color(pdf, DARK)
    pdf.multi_cell(
        label_w,
        line_h,
        text=sanitize(f"{label.rstrip(':')}:"),
        new_x=XPos.LEFT,
        new_y=YPos.NEXT,
        align="L",
    )
    y_label_end = pdf.get_y()

    pdf.set_xy(x + label_w + gap, y)
    pdf.set_font("Helvetica", "", 11)
    set_text_color(pdf, (0, 0, 0))
    pdf.multi_cell(
        col_w - label_w - gap,
        line_h,
        text=sanitize("" if value is None else str(value)),
        new_x=XPos.LEFT,
        new_y=YPos.NEXT,
        align="L",
    )
    y_value_end = pdf.get_y()

    return max(y_label_end, y_value_end)


def kv_row_two_pairs_wrapped(
    pdf: FPDF,
    l1: str,
    v1: Any,
    l2: str,
    v2: Any,
    label_w: float = 28,
    gap_between_cols: float = 10,
    inner_gap: float = 4,
) -> None:
    """
    Render two label/value pairs on one line (left and right columns),
    each pair wraps within its own half of the page.
    """
    x_left = pdf.l_margin
    y_top = pdf.get_y()
    total_w = usable_width(pdf)
    col_w = (total_w - gap_between_cols) / 2.0
    x_right = x_left + col_w + gap_between_cols

    y_end_left = _pair_block(
        pdf, x_left, y_top, col_w, l1, v1, label_w, gap=inner_gap
    )
    y_end_right = _pair_block(
        pdf, x_right, y_top, col_w, l2, v2, label_w, gap=inner_gap
    )

    pdf.set_xy(pdf.l_margin, max(y_end_left, y_end_right))


def field_visible(field: Dict[str, Any], answers: Dict[str, Any]) -> bool:
    cond = field.get("visible_if")
    if not cond:
        return True
    # Legacy support (kept for PDF logic that may still consult this)
    dep_name = cond.get("field")
    expected = cond.get("equals")
    return answers.get(dep_name) == expected


def write_section_to_pdf_QA(
    pdf: FPDF,
    section: Dict[str, Any],
    answers: Dict[str, Any],
    lang_map: Dict[str, str],
    category: str,
    make: Optional[str],
    model: Optional[str],
    title_override: Optional[str] = None,
    label_w: float = 100,
    render_header: bool = True,
) -> None:
    """
    Render a section as a sequence of two-column Q/A rows (or full-width textareas
    when a field has layout == "full"). This function reserves space at the end of
    the section for the trailing spacer + horizontal rule and will page-break
    beforehand if that block wouldn't fit.
    """
    if render_header:
        section_header(
            pdf,
            title_override
            or section.get(
                "title", lang_map.get(section.get("title_key", ""), "")
            ),
        )
    # Precompute two-column widths
    total_w = usable_width(pdf)
    gutter = 4
    col_w_label = label_w
    col_w_value = max(0, total_w - col_w_label - gutter)
    for field in section.get("fields", []):
        # Use new DSL visibility if present, fallback to legacy
        vis = (
            visible_if_eval(field.get("visible_if"), answers, category, make, model)
            if field.get("visible_if")
            else field_visible(field, answers)
        )
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
            kv_row_two_col(
                pdf,
                label,
                val,
                col_w_label,
                col_w_value,
                line_h=H_ROW,
                gutter=gutter,
            )

    thickness = HR_THICK
    need = SPACE_AFTER_BLOCK + HR_PAD + thickness + HR_PAD
    if pdf.get_y() + need > (pdf.h - pdf.b_margin):
        pdf.add_page()

    pdf.ln(SPACE_AFTER_BLOCK)
    draw_hr(pdf)


def write_site_info(
    pdf: FPDF,
    sections: List[Dict[str, Any]],
    answers: Dict[str, Any],
    lang_map: Dict[str, str],
    category: str,
    make: Optional[str],
    model: Optional[str],
) -> None:
    """
    Render the 'site_info' section into the PDF as a Site Information block.
    Skips any Store Hours-style field; hours are rendered separately.
    """
    for sec in sections:
        if sec.get("key") != "site_info":
            continue

        section_header(pdf, "Site Information")

        total_w = usable_width(pdf)
        gutter = 4
        col_w_label = 90
        col_w_value = max(0, total_w - col_w_label - gutter)

        for field in sec.get("fields", []):
            vis = (
                visible_if_eval(
                    field.get("visible_if"), answers, category, make, model
                )
                if field.get("visible_if")
                else field_visible(field, answers)
            )
            if not vis:
                continue

            name = field.get("name") or ""
            name_low = name.strip().lower()

            # Skip any Store Hours-style field
            raw_label = lang_map.get(
                field.get("label_key") or "", field.get("label") or ""
            )
            raw_label_low = (raw_label or "").strip().lower()
            if name_low in {"store_hours", "hours", "storehours"} or "store hours" in raw_label_low:
                continue

            label = lang_map.get(
                field.get("label_key"), field.get("label", name)
            )
            ftype = field.get("type", "text")
            val = answers.get(name)

            if ftype == "textarea":
                if val not in (None, "", []):
                    para(pdf, label, val)
            else:
                kv_row_two_col(
                    pdf,
                    label,
                    val,
                    col_w_label,
                    col_w_value,
                    line_h=H_ROW,
                    gutter=gutter,
                )

        pdf.ln(SPACE_AFTER_BLOCK)
        draw_hr(pdf)
        break


def write_contact_info(
    pdf: FPDF,
    sections: List[Dict[str, Any]],
    answers: Dict[str, Any],
    lang_map: Dict[str, str],
    category: str,
    make: Optional[str],
    model: Optional[str],
) -> None:
    for sec in sections:
        if sec.get("key") == "contact_info":
            section_header(pdf, "Contact Info")
            total_w = usable_width(pdf)
            gutter = 4
            col_w_label = 90
            col_w_value = max(0, total_w - col_w_label - gutter)
            for field in sec.get("fields", []):
                vis = (
                    visible_if_eval(
                        field.get("visible_if"), answers, category, make, model
                    )
                    if field.get("visible_if")
                    else field_visible(field, answers)
                )
                if not vis:
                    continue
                name = field.get("name") or ""
                label = lang_map.get(
                    field.get("label_key"), field.get("label", name)
                )
                ftype = field.get("type", "text")
                val = answers.get(name)
                if ftype == "textarea":
                    if val not in (None, "", []):
                        para(pdf, label, val)
                else:
                    kv_row_two_col(
                        pdf,
                        label,
                        val,
                        col_w_label,
                        col_w_value,
                        line_h=H_ROW,
                        gutter=gutter,
                    )
            pdf.ln(SPACE_AFTER_BLOCK)
            draw_hr(pdf)
            break


def build_survey_pdf(
    *,
    answers: Dict[str, Any],
    sections_used: List[Dict[str, Any]],
    hours: Dict[str, Any],
    validate_state: Dict[str, Any],
    make: Optional[str],
    model: Optional[str],
    model_weight: str,
    model_width: str,
    model_depth: str,
    model_height: str,
    image_path: Optional[str],
    settings_logo_path: Optional[str],
    accepted_photos: List[Any],
    max_count: int,
    lang_map: Dict[str, str],
    category: str,
) -> Tuple[bytes, str]:
    """
    Build the Site Survey PDF for the current answers and return (bytes, filename).

    This implementation is a direct extraction of the previous inline PDF logic
    from main.py, preserving layout, content, and filename behavior.
    """
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # --------------------------------------------------
    #  TITLE + TOP-RIGHT COMPANY LOGO
    # --------------------------------------------------
    pdf.set_title("Site Survey Report")
    page_title(
        pdf,
        "Site Survey Report",
        f"Date: {datetime.date.today()}",
        logo_path=settings_logo_path,
    )

    # Smaller hero image
    try:
        if image_path and os.path.exists(image_path):
            center_image(pdf, image_path, max_w=85)
    except Exception:
        # Keep behavior: silently ignore image errors
        pass

    # --- Equipment Info (wrapped two-pair rows) ---
    section_header(pdf, "Equipment Info")
    dims = f"{model_width} x {model_depth} x {model_height}"
    dims = nbsp_units(dims)
    kv_row_two_pairs_wrapped(pdf, "Make", make, "Model", model, label_w=28)
    kv_row_two_pairs_wrapped(
        pdf,
        "Weight",
        nbsp_units(model_weight),
        "Dimensions",
        dims,
        label_w=28,
    )
    pdf.ln(SPACE_AFTER_BLOCK)
    draw_hr(pdf)

    # --- Site Information ---
    write_site_info(pdf, sections_used, answers, lang_map, category, make, model)

    # --- Contact Info ---
    write_contact_info(pdf, sections_used, answers, lang_map, category, make, model)

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
                pdf,
                _sec,
                answers,
                lang_map,
                category,
                make,
                model,
                title_override="Delivery Instructions",
                label_w=100,
                render_header=(not printed_delivery_header),
            )
            printed_delivery_header = True

    # --- Installation Details (clean fixed two-cell Q/A rows) ---
    ensure_glue(pdf, min_after=26)
    for _sec in sections_used:
        if _sec.get("key") == "installation_location":
            write_section_to_pdf_QA(
                pdf,
                _sec,
                answers,
                lang_map,
                category,
                make,
                model,
                title_override="Installation Details",
                label_w=100,
            )
            break

    # --- Photos: one per page ---
    if accepted_photos:
        for photo in accepted_photos[: max_count]:
            temp_path: Optional[str] = None
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
                center_image(pdf, temp_path, max_w=max_w, max_h=max_h, y_top=y_top)
            except Exception:
                pdf.set_font("Helvetica", "B", 11)
                set_text_color(pdf, (200, 0, 0))
                pdf.cell(
                    0,
                    H_ROW,
                    text=sanitize(f"Error displaying image {photo.name}"),
                    new_x=XPos.LMARGIN,
                    new_y=YPos.NEXT,
                )
            finally:
                if temp_path and os.path.exists(temp_path):
                    os.remove(temp_path)

    # Footer
    pdf.set_y(-18)
    draw_hr(pdf, thickness=0.2)
    pdf.set_font("Helvetica", "I", 8)
    set_text_color(pdf, (90, 90, 90))
    pdf.cell(
        0,
        8,
        text=sanitize(
            "Generated by Site Survey App - Version 1.0 - © 2025"
        ),
        align="C",
        new_x=XPos.LMARGIN,
        new_y=YPos.NEXT,
    )

    # Streamlit download payload
    buf = BytesIO()
    pdf.output(buf)
    pdf_bytes = buf.getvalue()

    # -------- Dynamic PDF filename --------
    # Use Company Name and Site ID from the answers/validate_state
    company_raw = validate_state.get("company") or ""
    site_id_raw = validate_state.get("site_id") or ""

    # Fallback: if company is blank, use store_name so we don't end up with
    # "Site Survey -  - 1234"
    if not company_raw:
        company_raw = get_store_name(validate_state)

    # Truncate long pieces for filename friendliness
    company_part = (
        truncate_for_filename(company_raw, max_len=40) if company_raw else ""
    )
    site_id_part = (
        truncate_for_filename(site_id_raw, max_len=40) if site_id_raw else ""
    )

    parts = ["Site Survey"]

    if company_part:
        parts.append(company_part)
    if site_id_part:
        parts.append(site_id_part)

    filename_base = " - ".join(parts)
    filename_safe = make_filename_safe(filename_base) or "Site Survey"
    file_name = f"{filename_safe}.pdf"


    return pdf_bytes, file_name
