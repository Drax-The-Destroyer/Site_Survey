import streamlit as st
from PIL import Image
import io
import os
from fpdf import FPDF
import datetime

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
photos = st.file_uploader("Upload up to 20 site photos", type=[
                          "jpg", "jpeg", "png"], accept_multiple_files=True)
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


# -- Submit --
if st.button("✅ Submit Survey"):
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Arial", "B", 16)
    pdf.cell(0, 12, txt=sanitize("Site Survey Report"), ln=True, align="C")
    pdf.set_font("Arial", size=12)
    pdf.cell(0, 8, txt=sanitize(
        f"Date: {datetime.date.today()}"), ln=True, align="R")
    pdf.ln(5)

    try:
        if os.path.exists(image_path):
            pdf.image(image_path, x=10, w=80)
            pdf.ln(5)
    except Exception:
        pass

    def s(val):
        return sanitize("" if val is None else str(val))

    def section_header(title):
        pdf.ln(5)
        pdf.set_font("Arial", "B", 14)
        pdf.cell(0, 10, txt=sanitize(title), ln=True)
        pdf.set_font("Arial", size=12)

    def one_col_row(label, value, w_label=60, w_value=120):
        pdf.set_font("Arial", size=12)
        pdf.cell(w_label, 8, txt=sanitize(label), ln=0)
        pdf.cell(w_value, 8, txt=s(value), ln=1)

    def two_col_row(l1, v1, l2, v2, w_label=30, w_value=60):
        pdf.cell(w_label, 8, txt=sanitize(l1), ln=0)
        pdf.cell(w_value, 8, txt=s(v1), ln=0)
        pdf.cell(w_label, 8, txt=sanitize(l2), ln=0)
        pdf.cell(w_value, 8, txt=s(v2), ln=1)

    section_header("Equipment Info")
    dims = f"{model_info['width']} x {model_info['depth']} x {model_info['height']}"
    two_col_row("Make:", make, "Model:", model)
    two_col_row("Weight:", model_info.get("weight", ""), "Dimensions:", dims)

    section_header("Contact Info")
    one_col_row("Company:", company)
    one_col_row("Contact:", contact)
    one_col_row("Address:", address)
    one_col_row("Phone:", phone)
    one_col_row("Email:", email)

    section_header("Hours of Operation")
    for day, times in hours.items():
        open_t = s(times[0])
        close_t = s(times[1])
        pdf.cell(0, 8, txt=sanitize(f"{day}: {open_t} - {close_t}"), ln=1)

    section_header("Delivery Instructions")
    one_col_row("Days Prior:", days_prior)
    one_col_row("Storage Space:", storage_space)
    one_col_row("Loading Dock:", loading_dock)
    one_col_row("Delivery Hours:", delivery_hours)
    one_col_row("Location:", delivery_loc)

    if path_desc:
        pdf.cell(0, 8, txt=sanitize("Path:"), ln=1)
        pdf.multi_cell(0, 8, s(path_desc))
    if staircase_notes:
        pdf.cell(0, 8, txt=sanitize("Stairs:"), ln=1)
        pdf.multi_cell(0, 8, s(staircase_notes))
    if elevator_notes:
        pdf.cell(0, 8, txt=sanitize("Elevators:"), ln=1)
        pdf.multi_cell(0, 8, s(elevator_notes))
    if delivery_notes:
        pdf.cell(0, 8, txt=sanitize("Other Notes:"), ln=1)
        pdf.multi_cell(0, 8, s(delivery_notes))

    section_header("Installation Details")
    one_col_row("Floor Scan:", floor_scan)
    one_col_row("Speedtest:", f"{download_speed} Down / {upload_speed} Up")
    one_col_row("Door Size:", door_size)
    one_col_row("Room Size:", room_size)
    one_col_row("Space Available:", sufficient_space)
    two_col_row("Floor:", floor_type, "Other Floor Type:", other_floor_type)
    two_col_row("Other Safe:", other_safe, "Type:", safe_type)
    two_col_row("Network:", network, "Distance:", network_distance)
    two_col_row("Water Distance:", water_distance, "Power Nearby:", power)
    if install_notes:
        pdf.cell(0, 8, txt=sanitize("Notes:"), ln=1)
        pdf.multi_cell(0, 8, s(install_notes))

    if photos:
        # One photo per page, fit to page
        for i, photo in enumerate(photos[:20]):
            temp_path = None
            try:
                # New page and heading for each photo
                pdf.add_page()
                pdf.set_font("Arial", "B", 14)
                pdf.cell(0, 10, txt=sanitize("Site Survey Photo"), ln=True)
                pdf.ln(5)

                # Open and convert to RGB, then save temporarly as JPEG
                img = Image.open(photo).convert("RGB")
                w_img, h_img = img.size
                temp_path = f"temp_{photo.name}.jpg"
                img.save(temp_path, format="JPEG")

                # Fit-to-page: max width 190mm, max height based on page height and header offset
                max_w = 190
                y_top = 30
                max_h = pdf.h - y_top - 15  # bottom margin
                drawn_h = (max_w / w_img) * h_img

                if drawn_h <= max_h:
                    # Width-constrained
                    pdf.image(temp_path, x=10, y=y_top, w=max_w)
                else:
                    # Height-constrained
                    fit_h = max_h
                    fit_w = (fit_h / h_img) * w_img
                    pdf.image(temp_path, x=10, y=y_top, h=fit_h, w=fit_w)
            except Exception:
                pdf.cell(0, 8, txt=sanitize(
                    f"Error displaying image {photo.name}"), ln=1)
            finally:
                if temp_path and os.path.exists(temp_path):
                    os.remove(temp_path)

    # --- Footer ---
    pdf.set_y(-15)
    pdf.set_font("Arial", "I", 8)
    pdf.cell(0, 10, txt=sanitize(
        "Generated by Site Survey App - Version 1.0 - © 2025"), align="C")

    # --- Output to bytes (fpdf2 returns bytes; fpdf1 returns str) ---
    pdf_bytes = pdf.output(dest="S")
    if isinstance(pdf_bytes, str):
        # backward compatibility for fpdf v1
        pdf_bytes = pdf_bytes.encode("latin-1")

    st.success("Survey submitted successfully!")
    st.download_button(
        "📄 Download PDF Report",
        data=pdf_bytes,
        file_name="site_survey_report.pdf",
        mime="application/pdf",
    )
