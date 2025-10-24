import streamlit as st
from PIL import Image
import io
import os
from fpdf import FPDF
import datetime


def _ensure_bytes(data):
    # fpdf2 may return bytes or bytearray; fpdf v1 returns str (latin-1)
    if isinstance(data, bytes):
        return data
    if isinstance(data, bytearray):
        return bytes(data)
    if isinstance(data, memoryview):
        return data.tobytes()
    if isinstance(data, str):
        return data.encode("latin-1")
    return bytes(data)


# -- CONFIG --
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

# ---------------- PDF HELPERS (Centered layout) ----------------


def section_header(pdf: FPDF, title: str):
    pdf.ln(4)
    pdf.set_font("Arial", "B", 14)
    pdf.cell(0, 10, txt=sanitize(title), ln=True, align="C")
    pdf.set_font("Arial", size=12)


def one_col_row(pdf: FPDF, label: str, value):
    text = f"{label.rstrip(':')}: {sanitize('' if value is None else str(value))}"
    pdf.cell(0, 8, txt=sanitize(text), ln=True, align="C")


def two_col_row(pdf: FPDF, l1: str, v1, l2: str, v2):
    left = f"{l1.rstrip(':')}: {sanitize('' if v1 is None else str(v1))}"
    right = f"{l2.rstrip(':')}: {sanitize('' if v2 is None else str(v2))}"
    pdf.cell(0, 8, txt=sanitize(f"{left}     {right}"), ln=True, align="C")


def center_image(pdf: FPDF, path: str, max_w: float = None, max_h: float = None, y_top: float = None):
    """
    Centers an image within the page while preserving aspect ratio.
    If max_w/h omitted, they respect page margins.
    Returns (draw_w, draw_h).
    """
    if not os.path.exists(path):
        return 0, 0

    with Image.open(path) as img:
        w_img, h_img = img.size

    page_w, page_h = pdf.w, pdf.h
    left_margin = pdf.l_margin
    right_margin = pdf.r_margin
    usable_w = page_w - left_margin - right_margin

    if max_w is None:
        max_w = usable_w
    if max_h is None:
        max_h = page_h - pdf.t_margin - pdf.b_margin - 10

    scale_w = max_w / w_img
    scale_h = max_h / h_img
    scale = min(scale_w, scale_h)

    draw_w = w_img * scale
    draw_h = h_img * scale

    if y_top is None:
        y_top = pdf.get_y()

    # If remaining space is too small, move to next page
    if y_top + draw_h > (page_h - pdf.b_margin):
        pdf.add_page()
        y_top = pdf.get_y()

    x = (page_w - draw_w) / 2.0
    pdf.image(path, x=x, y=y_top, w=draw_w, h=draw_h)
    pdf.ln(draw_h + 4)
    return draw_w, draw_h


# ---------------- SUBMIT ----------------
if st.button("✅ Submit Survey"):
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # Title & date (centered)
    pdf.set_font("Arial", "B", 16)
    pdf.cell(0, 12, txt=sanitize("Site Survey Report"), ln=True, align="C")
    pdf.set_font("Arial", size=12)
    pdf.cell(0, 8, txt=sanitize(
        f"Date: {datetime.date.today()}"), ln=True, align="C")
    pdf.ln(5)

    # Centered model image
    try:
        if os.path.exists(image_path):
            center_image(pdf, image_path, max_w=120)  # nice header size
    except Exception:
        pass

    # Sections
    section_header(pdf, "Equipment Info")
    dims = f"{model_info['width']} x {model_info['depth']} x {model_info['height']}"
    two_col_row(pdf, "Make", make, "Model", model)
    two_col_row(pdf, "Weight", model_info.get(
        "weight", ""), "Dimensions", dims)

    section_header(pdf, "Contact Info")
    one_col_row(pdf, "Company", company)
    one_col_row(pdf, "Contact", contact)
    one_col_row(pdf, "Address", address)
    one_col_row(pdf, "Phone", phone)
    one_col_row(pdf, "Email", email)

    section_header(pdf, "Hours of Operation")
    for day, times in hours.items():
        open_t = "" if times[0] is None else str(times[0])
        close_t = "" if times[1] is None else str(times[1])
        pdf.cell(0, 8, txt=sanitize(
            f"{day}: {open_t} - {close_t}"), ln=1, align="C")

    section_header(pdf, "Delivery Instructions")
    one_col_row(pdf, "Days Prior", days_prior)
    one_col_row(pdf, "Storage Space", storage_space)
    one_col_row(pdf, "Loading Dock", loading_dock)
    one_col_row(pdf, "Delivery Hours", delivery_hours)
    one_col_row(pdf, "Location", delivery_loc)

    if path_desc:
        pdf.cell(0, 8, txt=sanitize("Path:"), ln=1, align="C")
        pdf.multi_cell(0, 8, sanitize(path_desc), align="C")
    if staircase_notes:
        pdf.cell(0, 8, txt=sanitize("Stairs:"), ln=1, align="C")
        pdf.multi_cell(0, 8, sanitize(staircase_notes), align="C")
    if elevator_notes:
        pdf.cell(0, 8, txt=sanitize("Elevators:"), ln=1, align="C")
        pdf.multi_cell(0, 8, sanitize(elevator_notes), align="C")
    if delivery_notes:
        pdf.cell(0, 8, txt=sanitize("Other Notes:"), ln=1, align="C")
        pdf.multi_cell(0, 8, sanitize(delivery_notes), align="C")

    section_header(pdf, "Installation Details")
    one_col_row(pdf, "Floor Scan", floor_scan)
    one_col_row(pdf, "Speedtest", f"{download_speed} Down / {upload_speed} Up")
    one_col_row(pdf, "Door Size", door_size)
    one_col_row(pdf, "Room Size", room_size)
    one_col_row(pdf, "Space Available", sufficient_space)
    two_col_row(pdf, "Floor", floor_type, "Other Floor Type", other_floor_type)
    two_col_row(pdf, "Other Safe", other_safe, "Type", safe_type)
    two_col_row(pdf, "Network", network, "Distance", network_distance)
    two_col_row(pdf, "Water Distance", water_distance, "Power Nearby", power)
    if install_notes:
        pdf.cell(0, 8, txt=sanitize("Notes:"), ln=1, align="C")
        pdf.multi_cell(0, 8, sanitize(install_notes), align="C")

    # Photos: one per page, centered and fit-to-page
    if photos:
        for i, photo in enumerate(photos[:20]):
            temp_path = None
            try:
                pdf.add_page()
                pdf.set_font("Arial", "B", 14)
                pdf.cell(0, 10, txt=sanitize(
                    "Site Survey Photo"), ln=True, align="C")
                pdf.ln(3)

                # Convert to RGB -> temp JPEG (fpdf likes JPEG best)
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
                pdf.cell(0, 8, txt=sanitize(
                    f"Error displaying image {photo.name}"), ln=1, align="C")
            finally:
                if temp_path and os.path.exists(temp_path):
                    os.remove(temp_path)

    # Footer (centered)
    pdf.set_y(-15)
    pdf.set_font("Arial", "I", 8)
    pdf.cell(0, 10, txt=sanitize(
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
