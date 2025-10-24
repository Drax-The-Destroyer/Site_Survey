import streamlit as st
from PIL import Image
import os
from fpdf import FPDF
import datetime

# ---------------- Utilities ----------------


def _ensure_bytes(data):
    if isinstance(data, bytes):
        return data
    if isinstance(data, bytearray):
        return bytes(data)
    if isinstance(data, memoryview):
        return data.tobytes()
    if isinstance(data, str):
        return data.encode("latin-1")
    return bytes(data)


def sanitize(text):
    if not isinstance(text, str):
        return text
    return (
        text.replace("–", "-")
            .replace("—", "-")
            .replace("“", "\"")
            .replace("”", "\"")
            .replace("’", "'")
            .replace("↓", "Down")
            .replace("↑", "Up")
            .encode("latin-1", errors="ignore")
            .decode("latin-1")
    )


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
    st.image(image_path, caption=f"{make} {model}", width=600)

# --- Upload Site Photos ---
st.subheader("2. Upload Site Photos")
photos = st.file_uploader(
    "Upload up to 20 site photos",
    type=["jpg", "jpeg", "png"],
    accept_multiple_files=True
)
if photos:
    for photo in photos[:20]:
        st.image(photo, caption=photo.name, width=150)

# --- Contact Info ---
st.subheader("3. Contact Information")
company = st.text_input("Company Name")
contact = st.text_input("Contact Name")
address = st.text_input("Address")
phone = st.text_input("Contact Phone #")
email = st.text_input("Contact Email")

# --- Days and Hours of Operation ---
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

# --- Delivery Instructions ---
st.subheader("5. Delivery Instructions")
days_prior = st.text_input(
    "How many days prior to installation can the safe be delivered?")
storage_space = st.radio(
    "Is there space to store the Tidel safe?", ["Yes", "No"])
loading_dock = st.radio("Is there a loading dock?", ["Yes", "No"])
delivery_hours = st.text_input("Delivery Hours")
delivery_loc = st.radio("Delivery Location", [
                        "Front of store", "Back of store"])
path_desc = st.text_area(
    "Describe the equipment path from the entry point to the final location")
use_dolly = st.radio(
    "Can a dolly be used to move the equipment?", ["Yes", "No"])
staircase_notes = st.text_area(
    "Describe door sizes, staircases (steps, turns, landings), etc.")
elevator_notes = st.text_area("Elevators (capacity, door size, dimensions)")
delivery_notes = st.text_area("Additional delivery instructions or comments")

# --- Installation Location ---
st.subheader("6. Installation Location")
floor_scan = st.radio("Is a Floor Scan required?", ["Yes", "No"])
download_speed = st.text_input("Speedtest Download (turn off 5G, use Bell)")
upload_speed = st.text_input("Speedtest Upload")
door_size = st.text_input("Door size")
room_size = st.text_input("Room size (Length x Width x Height)")
sufficient_space = st.radio(
    "Is there sufficient space for the safe? (Need 30 inches height)", ["Yes", "No"])
floor_type = st.radio("Floor/Subfloor type",
                      ["Concrete", "Wood", "Raised floor", "Other"])
other_floor_type = st.text_input("Other floor type (if applicable)")
other_safe = st.radio("Is there another safe in the same room?", ["Yes", "No"])
safe_type = st.text_input("If yes, what kind?")
network = st.radio("Is there a network connection available?", ["Yes", "No"])
network_distance = st.text_input("If yes, how far from the install location?")
water_distance = st.radio(
    "Is the safe being installed 6 feet away from water?", ["Yes", "No"])
power = st.radio(
    "Is there a power outlet within 4 feet of the unit?", ["Yes", "No"])
install_notes = st.text_area("Describe the installation and include any notes")

# ---------------- PDF Helpers (Pro look: centered headers, left-aligned content) ----------------
GRAY = (230, 230, 230)
DARK = (60, 60, 60)
LIGHT = (120, 120, 120)
LINE_GRAY = (200, 200, 200)


def set_text_color(pdf, rgb):
    r, g, b = rgb
    pdf.set_text_color(r, g, b)


def set_fill_color(pdf, rgb):
    r, g, b = rgb
    pdf.set_fill_color(r, g, b)


def draw_hr(pdf, y=None, thickness=0.3):
    if y is not None:
        pdf.set_y(y)
    x1 = pdf.l_margin
    x2 = pdf.w - pdf.r_margin
    y = pdf.get_y()
    r, g, b = LINE_GRAY
    pdf.set_draw_color(r, g, b)
    pdf.set_line_width(thickness)
    pdf.line(x1, y, x2, y)
    pdf.ln(3)


def page_title(pdf, title, date_str):
    pdf.set_font("Arial", "B", 18)
    set_text_color(pdf, DARK)
    pdf.cell(0, 12, txt=sanitize(title), ln=True, align="C")
    pdf.set_font("Arial", "", 12)
    set_text_color(pdf, LIGHT)
    pdf.cell(0, 8, txt=sanitize(date_str), ln=True, align="C")
    pdf.ln(3)
    draw_hr(pdf)


def section_header(pdf, text):
    pdf.ln(2)
    set_fill_color(pdf, GRAY)
    pdf.set_font("Arial", "B", 13)
    set_text_color(pdf, DARK)
    pdf.cell(0, 9, txt=sanitize(text), ln=True, align="L", fill=True)
    pdf.ln(2)


def kv_row(pdf, label, value, w_label=42, height=8):
    """
    Safer key/value row:
    - Resets X if we run out of space on the current line
    - Uses explicit remaining width (not 0) for multi_cell
    """
    # Move to a new line if we're too close to the right margin
    usable_w = pdf.w - pdf.l_margin - pdf.r_margin
    # If current X is beyond the left margin (e.g., after a previous cell),
    # compute remaining width for the value cell.
    cur_x = pdf.get_x()
    if cur_x < pdf.l_margin or cur_x > (pdf.w - pdf.r_margin - 1):
        pdf.ln(height)
        pdf.set_x(pdf.l_margin)

    # Draw label
    pdf.set_font("Arial", "B", 12)
    pdf.set_text_color(60, 60, 60)
    pdf.cell(w_label, height, txt=sanitize(f"{label.rstrip(':')}: "), ln=0)

    # Compute remaining width for the value cell
    cur_x = pdf.get_x()
    remaining_w = (pdf.w - pdf.r_margin) - cur_x
    if remaining_w <= 1:
        # No space left on this line; wrap to a new line and use full width
        pdf.ln(height)
        pdf.set_x(pdf.l_margin)
        remaining_w = usable_w

    # Draw value as a multi_cell with explicit width
    pdf.set_font("Arial", "", 12)
    pdf.set_text_color(0, 0, 0)
    txt = "" if value is None else str(value)
    pdf.multi_cell(remaining_w, height, sanitize(txt))


def kv_row_two_col(pdf, l1, v1, l2, v2, w_label=28, w_value=60, height=8, gap=6):
    # Left column
    pdf.set_font("Arial", "B", 12)
    set_text_color(pdf, DARK)
    pdf.cell(w_label, height, txt=sanitize(f"{l1.rstrip(':')}:"))
    pdf.set_font("Arial", "", 12)
    set_text_color(pdf, (0, 0, 0))
    pdf.cell(w_value, height, txt=sanitize(
        "" if v1 is None else str(v1)), ln=0)

    # Gap
    pdf.cell(gap, height, txt="")

    # Right column
    pdf.set_font("Arial", "B", 12)
    set_text_color(pdf, DARK)
    pdf.cell(w_label, height, txt=sanitize(f"{l2.rstrip(':')}:"))
    pdf.set_font("Arial", "", 12)
    set_text_color(pdf, (0, 0, 0))
    pdf.cell(w_value, height, txt=sanitize(
        "" if v2 is None else str(v2)), ln=1)


def para(pdf, label, text, height=7):
    pdf.set_font("Arial", "B", 12)
    pdf.set_text_color(60, 60, 60)
    pdf.cell(0, height, txt=sanitize(f"{label.rstrip(':')}: "), ln=True)
    pdf.set_font("Arial", "", 12)
    pdf.set_text_color(0, 0, 0)
    usable_w = pdf.w - pdf.l_margin - pdf.r_margin
    pdf.multi_cell(usable_w, height, sanitize(
        "" if text is None else str(text)))
    pdf.ln(1)


def hours_table(pdf, hours_dict):
    # Header
    set_fill_color(pdf, GRAY)
    set_text_color(pdf, DARK)
    pdf.set_font("Arial", "B", 12)
    day_w, open_w, close_w = 40, 35, 35
    pdf.cell(day_w, 8, "Day", border=0, fill=True)
    pdf.cell(open_w, 8, "Open", border=0, fill=True)
    pdf.cell(close_w, 8, "Close", border=0, fill=True, ln=1)
    # Rows
    pdf.set_font("Arial", "", 12)
    set_text_color(pdf, (0, 0, 0))
    for day, (open_t, close_t) in hours_dict.items():
        o = "" if open_t is None else str(open_t)
        c = "" if close_t is None else str(close_t)
        pdf.cell(day_w, 8, sanitize(day))
        pdf.cell(open_w, 8, sanitize(o))
        pdf.cell(close_w, 8, sanitize(c), ln=1)


def center_image(pdf: FPDF, path: str, max_w: float = None, max_h: float = None, y_top: float = None):
    if not os.path.exists(path):
        return (0, 0)
    with Image.open(path) as img:
        w_img, h_img = img.size

    page_w, page_h = pdf.w, pdf.h
    left_margin, right_margin = pdf.l_margin, pdf.r_margin
    usable_w = page_w - left_margin - right_margin

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
    pdf.ln(draw_h + 4)
    return (draw_w, draw_h)


# ---------------- Submit -> Build PDF ----------------
if st.button("✅ Submit Survey"):
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # Title block (centered), divider, then content left-aligned
    page_title(pdf, "Site Survey Report", f"Date: {datetime.date.today()}")

    # Equipment image (centered but modest)
    try:
        if os.path.exists(image_path):
            center_image(pdf, image_path, max_w=120)
    except Exception:
        pass

    # Equipment Info
    section_header(pdf, "Equipment Info")
    dims = f"{model_info['width']} x {model_info['depth']} x {model_info['height']}"
    kv_row_two_col(pdf, "Make", make, "Model", model)
    kv_row_two_col(pdf, "Weight", model_info.get(
        "weight", ""), "Dimensions", dims)
    pdf.ln(2)
    draw_hr(pdf)

    # Contact Info
    section_header(pdf, "Contact Info")
    kv_row(pdf, "Company", company)
    kv_row(pdf, "Contact", contact)
    kv_row(pdf, "Address", address)
    kv_row(pdf, "Phone", phone)
    kv_row(pdf, "Email", email)
    pdf.ln(2)
    draw_hr(pdf)

    # Hours of Operation
    section_header(pdf, "Hours of Operation")
    hours_table(pdf, hours)
    pdf.ln(2)
    draw_hr(pdf)

    # Delivery Instructions
    section_header(pdf, "Delivery Instructions")
    kv_row(pdf, "Days Prior", days_prior)
    kv_row(pdf, "Storage Space", storage_space)
    kv_row(pdf, "Loading Dock", loading_dock)
    kv_row(pdf, "Delivery Hours", delivery_hours)
    kv_row(pdf, "Location", delivery_loc)

    if path_desc:
        para(pdf, "Path", path_desc)
    if staircase_notes:
        para(pdf, "Stairs", staircase_notes)
    if elevator_notes:
        para(pdf, "Elevators", elevator_notes)
    if delivery_notes:
        para(pdf, "Other Notes", delivery_notes)
    pdf.ln(2)
    draw_hr(pdf)

    # Installation Details
    section_header(pdf, "Installation Details")
    kv_row(pdf, "Floor Scan", floor_scan)
    kv_row(pdf, "Speedtest", f"{download_speed} Down / {upload_speed} Up")
    kv_row(pdf, "Door Size", door_size)
    kv_row(pdf, "Room Size", room_size)
    kv_row(pdf, "Space Available", sufficient_space)
    kv_row_two_col(pdf, "Floor", floor_type,
                   "Other Floor Type", other_floor_type)
    kv_row_two_col(pdf, "Other Safe", other_safe, "Type", safe_type)
    kv_row_two_col(pdf, "Network", network, "Distance", network_distance)
    kv_row_two_col(pdf, "Water Distance",
                   water_distance, "Power Nearby", power)

    if install_notes:
        para(pdf, "Notes", install_notes)

    # Photos: one per page, with a centered image and left-aligned caption
    if photos:
        for photo in photos[:20]:
            temp_path = None
            try:
                pdf.add_page()
                section_header(pdf, "Site Survey Photo")

                # Convert for FPDF
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
                pdf.set_font("Arial", "B", 12)
                set_text_color(pdf, (200, 0, 0))
                pdf.cell(0, 8, txt=sanitize(
                    f"Error displaying image {photo.name}"), ln=1)
            finally:
                if temp_path and os.path.exists(temp_path):
                    os.remove(temp_path)

    # Footer line + centered footer text
    pdf.set_y(-18)
    draw_hr(pdf, thickness=0.2)
    pdf.set_font("Arial", "I", 8)
    set_text_color(pdf, (90, 90, 90))
    pdf.cell(0, 8, txt=sanitize(
        "Generated by Site Survey App - Version 1.0 - © 2025"), align="C")

    # Streamlit download
    _out = pdf.output(dest="S")
    pdf_bytes = _ensure_bytes(_out)
    st.success("Survey submitted successfully! PDF is ready below.")
    st.download_button(
        label="📄 Download PDF Report",
        data=pdf_bytes,
        file_name="site_survey_report.pdf",
        mime="application/pdf",
    )
