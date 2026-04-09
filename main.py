import os
import datetime
import json
import random
import time
import uuid
from typing import Any, Dict, List, Optional

import streamlit as st

from utils.logger import setup_logger
from utils.database import SurveyDatabase
from utils.draft_state import (
    default_hours_template,
    deserialize_draft_value,
    extract_safe_draft_payload,
    has_meaningful_draft_data,
)
from config import Config
from data_loader import (
    load_catalog,
    load_questions,
    load_lang,
    get_data_version,
    load_media_index, 
)
from overrides import merge_overrides
from form_renderer import apply_overrides as apply_field_overrides, render_section, seed_defaults
from visible_if import is_visible as visible_if_field, evaluate as visible_if_eval
from pdf_builder import build_survey_pdf
from question_profiles import (
    always_included_sections,
    build_sections_for_profile,
    get_default_profile_id,
    get_profile_by_id,
    get_profiles_for_category,
    normalize_category_key,
    section_field_names,
)
from questions import get_questions_for

# Setup logger
logger = setup_logger(__name__)

# Initialize database
db = SurveyDatabase(Config.DATABASE_PATH)

# ==================== Helper: Deserialize Draft Data ====================
def deserialize_draft_data(data: Dict[str, Any]) -> Dict[str, Any]:
    return deserialize_draft_value(data)


TECH_ID_NAMES = [
    "Peter Parker", "Bruce Wayne", "Clark Kent", "Diana Prince", "Steve Rogers",
    "Tony Stark", "Bruce Banner", "Natasha Romanoff", "Matt Murdock", "Wade Wilson",
    "Logan Howlett", "Barry Allen", "Hal Jordan", "Arthur Curry", "Victor Stone",
    "Reed Richards", "Sue Storm", "Johnny Storm", "Ben Grimm", "Scott Summers",
    "Jean Grey", "Ororo Munroe", "Kurt Wagner", "Kitty Pryde", "Emma Frost",
    "Remy LeBeau", "Anna Marie", "Bobby Drake", "Hank McCoy", "Jubilation Lee",
    "Cable Summers", "Hope Summers", "Laura Kinney", "Piotr Rasputin", "Illyana Rasputina",
    "Stephen Strange", "Scott Lang", "Carol Danvers", "Kamala Khan", "Monica Rambeau",
    "Sam Wilson", "Bucky Barnes", "Clint Barton", "Kate Bishop", "Jennifer Walters",
    "Marc Spector", "Danny Rand", "Luke Cage", "Jessica Jones", "Frank Castle",
    "Elektra Natchios", "Misty Knight", "Colleen Wing", "Shang Chi", "Black Panther",
    "Princess Shuri", "Riri Williams", "Miles Morales", "Gwen Stacy", "Cindy Moon",
    "Miguel OHara", "Mayday Parker", "Billy Kaplan", "Tommy Shepherd", "Victor Shade",
    "Wanda Maximoff", "Pietro Maximoff", "Billy Batson", "Mary Batson", "Freddy Freeman",
    "Barbara Gordon", "Dick Grayson", "Jason Todd", "Tim Drake", "Damian Wayne",
    "Selina Kyle", "Oswald Cobblepot", "Harleen Quinzel", "Pamela Isley", "Edward Nygma",
    "Slade Wilson", "Dinah Lance", "Oliver Queen", "Roy Harper", "John Diggle",
    "Kara Danvers", "Jonn Jonnz", "Lois Lane", "Lex Luthor", "Jimmy Olsen",
    "John Stewart", "Guy Gardner", "Kyle Rayner", "Jessica Cruz", "Simon Baz",
    "Wally West", "Bart Allen", "Jay Garrick", "Ted Kord", "Michael Carter",
    "Kendra Saunders", "Carter Hall", "Rex Mason", "Garfield Logan", "Rachel Roth",
    "Kori Anders", "Donna Troy", "Conner Kent", "Cassie Sandsmark", "Jaime Reyes",
    "Billy Cranston", "Trini Kwan", "Zack Taylor", "Kimberly Hart", "Tommy Oliver",
    "April ONeil", "Casey Jones", "Leonardo Hamato", "Raphael Hamato", "Donatello Hamato",
    "Michelangelo Hamato", "Al Simmons", "Eric Brooks", "Mattie Franklin", "Terry McGinnis",
    "Helena Bertinelli", "Cassandra Cain", "Stephanie Brown", "Renee Montoya", "Booster Gold",
    "Zatanna Zatara", "John Constantine", "Swamp Thing", "Alec Holland", "Mera Curry",
    "Norrin Radd", "Adam Warlock", "Richard Rider", "Sam Alexander", "Rocket Raccoon",
    "Gamora Zen", "Drax Douglas", "Jessica Drew", "Peter Quill", "Silver Surfer",
    "Blackagar Boltagon", "Medusa Boltagon", "Crystal Amaquelin", "Karnak Mander", "Gorgon Petragon",
    "Maximus Boltagon", "Loki Laufeyson", "Thor Odinson", "Jane Foster", "Sif Asgard",
    "Balder Odinson", "Amadeus Cho", "Doreen Green", "Robbie Reyes", "Johnny Blaze",
    "Danny Ketch", "Marc Grayson", "Samantha Eve", "Nolan Grayson", "Allen Alien",
    "Atom Eve", "Rex Splode", "Dupli Kate", "Cecil Stedman", "Debbie Grayson",
]


def _generate_tech_id() -> str:
    return random.choice(TECH_ID_NAMES)


def _ensure_tech_id() -> None:
    if st.session_state.get("tech_id"):
        return
    tech_param = str(st.query_params.get("tech") or "").strip()
    st.session_state["tech_id"] = tech_param or _generate_tech_id()


def _validate_session_state() -> None:
    """
    Debug helper to ensure no orphaned widget keys.
    Checks that form data is properly centralized in form_data dict.
    """
    if "form_data" not in st.session_state:
        return
    
    form_data_keys = set(st.session_state["form_data"].keys())
    
    # Known non-form keys that should exist in session_state
    known_system_keys = {
        "form_data", "survey_id", "last_autosave", "show_drafts", 
        "_show_required_errors", "_current_model_key",
        "make_sel", "model_sel", "profile_id",
        "same_weekdays", "weekend_closed", "apply_hours_presets",
        "apply_hours_all_days", "weekday_open_preset", "weekday_close_preset",
        "hours_quick_template"
    }
    
    # Check for orphaned widget keys (form fields that aren't in form_data)
    orphaned = []
    for key in st.session_state.keys():
        # Skip internal Streamlit keys
        if key.startswith("_") and key not in {"_show_required_errors", "_current_model_key"}:
            continue
        # Skip known system keys
        if key in known_system_keys:
            continue
        # Skip button/form submission keys
        if key.startswith(("FormSubmitter:", "load_", "del_", "download_")):
            continue
        # Skip hours of operation keys (managed separately)
        if key.startswith(("open_", "close_", "closed_")):
            continue
        # If it's not in form_data, it might be orphaned
        if key not in form_data_keys:
            orphaned.append(key)
    
    if orphaned:
        logger.warning(f"Orphaned session keys found: {orphaned}")
        # In development, you might want to see this:
        # st.warning(f"Debug: Found {len(orphaned)} orphaned keys: {orphaned[:5]}")

# ---------------- App Config ----------------

# st.set_page_config(page_title="Site Survey Form", layout="centered")
st.set_page_config(page_title="Site Survey Form", layout="wide", initial_sidebar_state="auto")

st.markdown(
    """
<style>
@media (max-width: 768px) {
  .block-container {
    padding-left: 1rem !important;
    padding-right: 1rem !important;
    padding-top: 1rem !important;
  }

  [data-testid="column"] {
    min-width: 100% !important;
    flex: 1 1 100% !important;
  }

  div.stButton > button,
  div.stDownloadButton > button,
  div[data-testid="stFormSubmitButton"] button {
    width: 100% !important;
  }

  .stTextInput input,
  .stTextArea textarea,
  .stSelectbox,
  .stNumberInput,
  .stDateInput,
  .stTimeInput {
    font-size: 16px !important;
  }
}
</style>
""",
    unsafe_allow_html=True,
)

# Load data-driven resources
version = get_data_version()
_ensure_tech_id()

# Always rebuild media index so index.json matches assets/ + data/media
media_index = load_media_index()

catalog = load_catalog(version)
qdef = load_questions(version)
lang_map = load_lang("en", version)


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
    return " ".join(w.capitalize() for w in slug.replace("_", " ").split())


def _selected_model_context(source: Dict[str, Any]) -> Dict[str, Any]:
    makes_map: Dict[str, Dict[str, Any]] = catalog.get("makes", {}) or {}
    make_key = source.get("make_sel")
    model_key = source.get("model_sel")

    make_obj = makes_map.get(make_key) or {}
    model_obj = (make_obj.get("models") or {}).get(model_key) or {}

    return {
        "make_key": make_key,
        "model_key": model_key,
        "make_obj": make_obj,
        "model_obj": model_obj,
        "make_label": make_obj.get("label", make_key) if make_key else "",
        "model_label": model_obj.get("label", model_key) if model_key else "",
        "category": normalize_category(model_obj.get("category", "")),
    }


def _merge_runtime_questions_into_sections(
    sections: List[Dict[str, Any]],
    *,
    qdef: Dict[str, Any],
    category_key: str,
    make_key: Optional[str],
    model_key: Optional[str],
    customer_id: Optional[str],
) -> List[Dict[str, Any]]:
    merged_sections: List[Dict[str, Any]] = []
    for section in sections or []:
        section_key = str(section.get("key") or "").strip()
        if not section_key:
            merged_sections.append(section)
            continue

        extra_questions = get_questions_for(
            qdef,
            category_key=category_key,
            section_name=section_key,
            make_key=make_key,
            model_key=model_key,
            customer_id=customer_id,
        )

        if not extra_questions:
            merged_sections.append(section)
            continue

        updated_section = dict(section)
        existing_fields = list(updated_section.get("fields", []) or [])
        field_records: Dict[str, Dict[str, Any]] = {}
        next_sequence = 1
        highest_order = 0
        for default_order, field in enumerate(existing_fields, start=1):
            if not isinstance(field, dict):
                continue
            field_name = str(field.get("name") or field.get("id") or "").strip()
            if not field_name:
                continue
            try:
                sort_order = int(field.get("order", default_order))
            except Exception:
                sort_order = default_order
            field_records[field_name] = {
                "field": dict(field),
                "order": sort_order,
                "sequence": next_sequence,
            }
            next_sequence += 1
            highest_order = max(highest_order, sort_order)

        for question in extra_questions:
            if not isinstance(question, dict):
                continue
            field_name = str(question.get("name") or question.get("id") or question.get("key") or "").strip()
            if not field_name:
                continue

            include = bool(question.get("include", True))
            existing_record = field_records.get(field_name)
            try:
                order_value = int(
                    question.get(
                        "order",
                        existing_record["order"] if existing_record else highest_order + 1,
                    )
                )
            except Exception:
                order_value = existing_record["order"] if existing_record else highest_order + 1

            if existing_record:
                if not include:
                    field_records.pop(field_name, None)
                    continue

                merged_field = dict(existing_record["field"])
                for key, value in question.items():
                    if key in {"include", "key"}:
                        continue
                    if key == "visible_if" and value is None:
                        merged_field.pop("visible_if", None)
                        continue
                    merged_field[key] = value
                merged_field["name"] = field_name
                merged_field.pop("key", None)
                field_records[field_name] = {
                    "field": merged_field,
                    "order": order_value if "order" in question else existing_record["order"],
                    "sequence": existing_record["sequence"],
                }
                highest_order = max(highest_order, field_records[field_name]["order"])
                continue

            if not include:
                continue

            field = dict(question)
            field["name"] = field_name
            field.pop("key", None)
            field.pop("include", None)
            field_records[field_name] = {
                "field": field,
                "order": order_value,
                "sequence": next_sequence,
            }
            next_sequence += 1
            highest_order = max(highest_order, order_value)

        updated_fields = []
        for record in sorted(field_records.values(), key=lambda item: (item["order"], item["sequence"])):
            field = dict(record["field"])
            field.pop("order", None)
            field.pop("include", None)
            updated_fields.append(field)

        updated_section["fields"] = updated_fields
        merged_sections.append(updated_section)

    return merged_sections


def _sync_form_data_from_widget_state() -> None:
    if "form_data" not in st.session_state or not isinstance(st.session_state["form_data"], dict):
        st.session_state["form_data"] = {}

    form_data = st.session_state["form_data"]

    for key, value in st.session_state.items():
        if "__" not in key:
            continue
        _section_key, field_name = key.split("__", 1)
        if not field_name:
            continue
        form_data[field_name] = value

    hours = {}
    has_hours_state = False
    for day in ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"):
        open_key = f"open_{day}"
        close_key = f"close_{day}"
        closed_key = f"closed_{day}"
        if open_key not in st.session_state and close_key not in st.session_state and closed_key not in st.session_state:
            continue
        has_hours_state = True
        closed = bool(st.session_state.get(closed_key, False))
        hours[day] = {
            "open": None if closed else st.session_state.get(open_key),
            "close": None if closed else st.session_state.get(close_key),
            "closed": closed,
        }
    if has_hours_state:
        form_data["hours"] = hours

    if isinstance(st.session_state.get("uploaded_photos"), list):
        form_data["photos"] = st.session_state["uploaded_photos"]


def build_current_draft_payload() -> Dict[str, Any]:
    _sync_form_data_from_widget_state()
    context = _selected_model_context(st.session_state)
    payload = extract_safe_draft_payload(
        st.session_state,
        make=context["make_label"] or None,
        model=context["model_label"] or None,
        category=context["category"] or None,
        profile_id=st.session_state.get("profile_id"),
    )
    payload["tech_id"] = st.session_state.get("tech_id", "")
    return payload


def _clear_form_widget_state() -> None:
    to_clear = []
    for key in list(st.session_state.keys()):
        if "__" in key or key.startswith(("FormSubmitter:", "photo_uploader_key")):
            to_clear.append(key)
    for key in to_clear:
        st.session_state.pop(key, None)


def _coerce_time_for_widget(value: Any) -> Any:
    if isinstance(value, datetime.time) or value is None:
        return value
    if isinstance(value, str):
        try:
            parts = value.split(":")
            hour = int(parts[0])
            minute = int(parts[1])
            second = int(parts[2]) if len(parts) > 2 else 0
            return datetime.time(hour, minute, second)
        except Exception:
            return None
    return None


def _restore_hours_state(form_data: Dict[str, Any]) -> None:
    default_hours = default_hours_template()
    default_open_widget = datetime.time(8, 0)
    default_close_widget = datetime.time(20, 0)
    restored_hours = form_data.get("hours")
    if not isinstance(restored_hours, dict):
        restored_hours = default_hours

    for day, defaults in default_hours.items():
        entry = restored_hours.get(day) if isinstance(restored_hours, dict) else None
        if not isinstance(entry, dict):
            entry = defaults

        open_value = _coerce_time_for_widget(entry.get("open", defaults["open"])) or default_open_widget
        close_value = _coerce_time_for_widget(entry.get("close", defaults["close"])) or default_close_widget

        st.session_state[f"open_{day}"] = open_value
        st.session_state[f"close_{day}"] = close_value
        st.session_state[f"closed_{day}"] = bool(entry.get("closed", defaults["closed"]))


def apply_draft_payload_to_session(
    raw_payload: Dict[str, Any],
    *,
    survey_id_override: Optional[str] = None,
    restore_selection: bool = True,
) -> bool:
    safe_payload = extract_safe_draft_payload(deserialize_draft_data(raw_payload or {}))

    if restore_selection:
        context = _selected_model_context(safe_payload)
        if not (context["make_obj"] and context["model_obj"]):
            st.error("This draft references a make/model that no longer exists in the catalog.")
            return False

    form_data = deserialize_draft_data(safe_payload.get("form_data", {}))
    if not isinstance(form_data, dict):
        form_data = {}

    _clear_form_widget_state()

    if restore_selection and safe_payload.get("make_sel"):
        st.session_state["make_sel"] = safe_payload["make_sel"]
    if restore_selection and safe_payload.get("model_sel"):
        st.session_state["model_sel"] = safe_payload["model_sel"]
    if safe_payload.get("profile_id"):
        st.session_state["profile_id"] = safe_payload["profile_id"]
    if safe_payload.get("tech_id"):
        st.session_state["tech_id"] = safe_payload["tech_id"]

    st.session_state["form_data"] = form_data
    st.session_state["uploaded_photos"] = list(form_data.get("photos", [])) if isinstance(form_data.get("photos"), list) else []
    st.session_state["survey_id"] = survey_id_override or safe_payload.get("survey_id") or st.session_state.get("survey_id") or str(uuid.uuid4())
    st.session_state["last_autosave"] = 0
    st.session_state["_show_required_errors"] = False
    _restore_hours_state(form_data)
    return True


def _visibility_state_for_sections(
    state: Dict[str, Any],
    sections: List[Dict[str, Any]],
) -> Dict[str, Any]:
    names = section_field_names(sections)
    return {
        name: state.get(name)
        for name in names
        if name in state
    }

# ==================== Sidebar: Draft Management & Export ====================
with st.sidebar:
    st.title("Survey Management")
    st.caption(f"Session: {str(st.session_state.get('tech_id', ''))[:8]}")
    tech_id_input = st.text_input("Your name / tech ID", value=st.session_state.get("tech_id", ""), key="tech_id_input")
    if tech_id_input.strip() and tech_id_input.strip() != st.session_state.get("tech_id"):
        st.session_state["tech_id"] = tech_id_input.strip()
        if st.session_state.get("survey_id"):
            db.save_draft(
                st.session_state["survey_id"],
                build_current_draft_payload(),
                user_id=st.session_state.get("tech_id", ""),
            )
        st.rerun()
    
    # Initialize show_drafts flag if not present
    if "show_drafts" not in st.session_state:
        st.session_state["show_drafts"] = False
    
    if st.button("View My Drafts"):
        st.session_state["show_drafts"] = not st.session_state["show_drafts"]
    
    if st.session_state.get("show_drafts"):
        drafts = db.list_drafts(limit=20, user_id=st.session_state.get("tech_id", ""))
        
        if drafts:
            st.markdown("### Recent Drafts")
            for survey_id, store, make_draft, model_draft, updated_at, tech in drafts:
                # Format timestamp
                try:
                    dt = datetime.datetime.fromisoformat(updated_at)
                    time_ago = dt.strftime("%b %d, %I:%M %p")
                except:
                    time_ago = updated_at[:16] if updated_at else "Unknown"
                
                # Display draft info
                draft_label = f"{store or 'Unnamed Store'} - {make_draft} {model_draft}"
                st.markdown(f"**{draft_label}**")
                st.caption(f"Last saved: {time_ago}")
                
                col1, col2 = st.columns(2)
                with col1:
                    if st.button("Load", key=f"load_{survey_id}"):
                        loaded_data = db.load_draft(survey_id)
                        if loaded_data and apply_draft_payload_to_session(loaded_data, survey_id_override=survey_id):
                            logger.info(f"Draft loaded from sidebar", extra={"survey_id": survey_id})
                            st.success("Draft loaded!")
                            st.rerun()
                with col2:
                    if st.button("Delete", key=f"del_{survey_id}"):
                        if db.delete_draft(survey_id):
                            st.success("Draft deleted")
                            st.rerun()
                
                st.divider()
        else:
            st.info("No drafts found")
    
    # Export current draft as JSON
    st.markdown("---")
    st.markdown("### Export Current Survey")

    current_export_payload = build_current_draft_payload()
    if st.session_state.get("survey_id"):
        st.download_button(
            "Export Draft (JSON)",
            data=json.dumps(current_export_payload, indent=2),
            file_name=f"survey_draft_{st.session_state['survey_id']}.json",
            mime="application/json",
            key="download_json_btn",
            disabled=not has_meaningful_draft_data(current_export_payload),
        )

        if has_meaningful_draft_data(current_export_payload):
            st.caption("Tip: Download your draft before closing the browser to avoid data loss on Streamlit Cloud.")
        else:
            st.caption("Enter at least one real survey value before exporting a draft.")
    else:
        st.caption("Start a survey to enable export")

    st.markdown("### Import Draft (JSON)")
    import_file = st.file_uploader("Upload exported draft JSON", type=["json"], key="import_draft_json")
    if st.button("Import Draft", key="import_draft_btn"):
        if import_file is None:
            st.warning("Choose a JSON file first.")
        else:
            try:
                import_file.seek(0)
                imported_payload = json.load(import_file)
            except json.JSONDecodeError:
                st.error("That file is not valid JSON.")
            except Exception as exc:
                st.error(f"Unable to read that file: {exc}")
            else:
                if not isinstance(imported_payload, dict):
                    st.error("Draft import expects a JSON object at the top level.")
                else:
                    safe_payload = extract_safe_draft_payload(imported_payload)
                    if not has_meaningful_draft_data(safe_payload):
                        st.error("This JSON file does not contain any meaningful survey draft data.")
                    elif apply_draft_payload_to_session(safe_payload):
                        logger.info("Draft imported from JSON", extra={"survey_id": st.session_state.get("survey_id")})
                        st.success("Draft imported.")
                        st.rerun()
    
    # NOTE about Streamlit Cloud ephemeral storage
    st.markdown("---")
    st.caption("Note: On Streamlit Cloud, the database is temporary and resets on app restart. Export important drafts before closing.")

st.title("Site Survey Form")

# --- Load Settings (branding + logo) ---
SETTINGS_FP = os.path.join("data", "settings.json")

def load_settings():
    try:
        with open(SETTINGS_FP, "r", encoding="utf-8") as f:
            settings = json.load(f)
            if not isinstance(settings, dict):
                settings = {}
    except:
        settings = {}

    settings.setdefault("branding", {})
    settings.setdefault("media", {})
    settings.pop("email", None)
    settings.pop("smtp", None)
    return settings

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

    # Not found - still return local path where it SHOULD be
    return local_paths[0]
    
settings = load_settings()

# Extract the selected hero/logo file
settings_logo = settings.get("media", {}).get("hero_image", "")
settings_logo_path = _hero_path(settings_logo)
# st.write("DEBUG: settings_logo =", settings_logo)
# st.write("DEBUG: settings_logo_path =", settings_logo_path)

# if isinstance(settings_logo_path, str):
#     st.write("Exists on disk? ->", os.path.exists(settings_logo_path))
# else:
#     st.write("Exists on disk? ->", False)


# Language toggle (scaffold for future FR)
# lang_choice = st.selectbox("Language", ["English"], index=0)
# TODO: When adding French or other locales:
# - replace hardcoded "en" in load_lang("en", version)
# - map lang_choice -> "en", "fr_qc", etc.


def _apply_prefill_query_params() -> None:
    if st.session_state.get("_params_applied"):
        return

    customer_param = str(st.query_params.get("customer") or "").strip()
    make_param = str(st.query_params.get("make") or "").strip()
    model_param = str(st.query_params.get("model") or "").strip()

    if customer_param:
        for customer in load_customers():
            if str(customer.get("id") or "").strip() == customer_param:
                st.session_state["customer_id"] = customer_param
                make_key = find_make_key_by_label(customer.get("make"))
                model_key = find_model_key_by_label(make_key, customer.get("model"))
                if make_key:
                    st.session_state["make_sel"] = make_key
                if model_key:
                    st.session_state["model_sel"] = model_key
                st.session_state["_params_applied"] = True
                return

    if make_param and model_param:
        make_key = find_make_key_by_label(make_param)
        model_key = find_model_key_by_label(make_key, model_param)
        st.session_state["customer_id"] = "__manual__"
        if make_key:
            st.session_state["make_sel"] = make_key
        if model_key:
            st.session_state["model_sel"] = model_key
        st.session_state["_params_applied"] = True
        return

    st.session_state["_params_applied"] = True


# --- Equipment Selection (Customer -> Make/Model; Category derived from model) ---
st.subheader(f"1. {lang_map.get('section.site_info', 'Site Information')}")

# New admin structure: catalog["makes"][make_key] -> {"label", "models": {...}}
makes_map: Dict[str, Dict[str, Any]] = catalog.get("makes", {}) or {}
CUSTOMERS_FP = os.path.join("data", "customers.json")


def make_label(k: str) -> str:
    return (makes_map.get(k) or {}).get("label", k)


def model_label(mk: str, mdk: str) -> str:
    return ((makes_map.get(mk) or {}).get("models", {}).get(mdk) or {}).get("label", mdk)


def load_customers() -> List[Dict[str, Any]]:
    try:
        with open(CUSTOMERS_FP, "r", encoding="utf-8") as f:
            payload = json.load(f)
        customers = payload.get("customers", [])
        return customers if isinstance(customers, list) else []
    except Exception:
        return []


def find_make_key_by_label(label: Optional[str]) -> Optional[str]:
    if not label:
        return None
    wanted = str(label).strip().lower()
    for mk in makes_map.keys():
        if make_label(mk).strip().lower() == wanted:
            return mk
    return None


def find_model_key_by_label(mk: Optional[str], label: Optional[str]) -> Optional[str]:
    if not mk or not label:
        return None
    wanted = str(label).strip().lower()
    for model_k in ((makes_map.get(mk) or {}).get("models", {}) or {}).keys():
        if model_label(mk, model_k).strip().lower() == wanted:
            return model_k
    return None


customers = load_customers()
customer_options = ["__none__"] + [customer.get("id") for customer in customers if customer.get("id")] + ["__manual__"]
customer_lookup = {customer.get("id"): customer for customer in customers if customer.get("id")}

_apply_prefill_query_params()

if st.session_state.get("customer_id") not in customer_options:
    st.session_state["customer_id"] = "__none__"

selected_customer_id = st.selectbox(
    "Customer",
    options=customer_options,
    format_func=lambda cid: (
        "Select a customer" if cid == "__none__"
        else "Other / Manual Entry" if cid == "__manual__"
        else (customer_lookup.get(cid) or {}).get("name", cid)
    ),
    key="customer_id",
)

selected_customer = customer_lookup.get(selected_customer_id) if selected_customer_id not in {"__none__", "__manual__"} else None
manual_entry = selected_customer_id == "__manual__"

resolved_make_key = None
resolved_model_key = None

if selected_customer:
    resolved_make_key = find_make_key_by_label(selected_customer.get("make"))
    resolved_model_key = find_model_key_by_label(resolved_make_key, selected_customer.get("model"))
    st.session_state["make_sel"] = resolved_make_key
    st.session_state["model_sel"] = resolved_model_key
elif manual_entry:
    # Make selector
    resolved_make_key = st.selectbox(
        "Make",
        options=list(makes_map.keys()),
        format_func=lambda k: make_label(k),
        key="make_sel",
    ) if makes_map else None

    # Model selector scoped to make
    models_map_for_make: Dict[str, Dict[str, Any]] = (
        makes_map.get(resolved_make_key) or {}).get("models", {}) if resolved_make_key else {}
    resolved_model_key = st.selectbox(
        "Model",
        options=list(models_map_for_make.keys()),
        format_func=lambda k: model_label(resolved_make_key, k),
        key="model_sel",
    ) if models_map_for_make else None

make_key = resolved_make_key
models_map_for_make: Dict[str, Dict[str, Any]] = (
    makes_map.get(make_key) or {}).get("models", {}) if make_key else {}
model_key = resolved_model_key

# Pull selected model meta + derive category
selected_model: Dict[str, Any] = (
    models_map_for_make.get(model_key) or {}) if model_key else {}
# e.g., "smart_safe", "recycler", etc.
category = normalize_category(selected_model.get("category", ""))
category_key = normalize_category_key(selected_model.get("category", ""))
make = make_label(make_key) if make_key else None
model = model_label(make_key, model_key) if model_key else None
model_meta: Dict[str, Any] = selected_model

st.session_state["resolved_make"] = make
st.session_state["resolved_model"] = model
st.session_state["resolved_make_key"] = make_key
st.session_state["resolved_model_key"] = model_key

# Guard against None selections
if not (make and model):
    if selected_customer_id == "__none__":
        st.info("Select a customer, or choose Other / Manual Entry.")
    else:
        st.info("Select a Make, then Model. Category is derived automatically.")
    model_key = None
    model_meta = {}
else:
    # model_key and model_meta already set above
    logger.info(f"Equipment selected - Make: {make}, Model: {model}, Category: {category}")
    
    # ==================== Survey Session Management ====================
    # Check if survey_id exists, otherwise look for recent draft or create new
    if "survey_id" not in st.session_state:
        # Check for recent draft matching this make/model
        recent_draft_id = db.find_recent_draft(make, model, limit_hours=24, user_id=st.session_state.get("tech_id", ""))
        
        if recent_draft_id:
            # Offer to resume draft
            st.info(f"Found a recent draft for {make} {model}")
            col1, col2 = st.columns(2)
            with col1:
                if st.button("Resume Draft"):
                    loaded_data = db.load_draft(recent_draft_id)
                    if loaded_data and apply_draft_payload_to_session(
                        loaded_data,
                        survey_id_override=recent_draft_id,
                        restore_selection=False,
                    ):
                        logger.info(f"Resumed draft", extra={"survey_id": recent_draft_id})
                        st.success("Draft loaded! Scroll down to continue.")
                        st.rerun()
            with col2:
                if st.button("Start Fresh"):
                    st.session_state["survey_id"] = str(uuid.uuid4())
                    st.session_state["last_autosave"] = 0
                    logger.info(f"Started new survey", extra={"survey_id": st.session_state["survey_id"]})
                    st.rerun()
        else:
            # No recent draft, create new survey ID
            st.session_state["survey_id"] = str(uuid.uuid4())
            st.session_state["last_autosave"] = 0
            logger.info(f"Created new survey", extra={"survey_id": st.session_state["survey_id"]})

profile_options = get_profiles_for_category(qdef, category_key) if category_key else []
if profile_options:
    available_profile_ids = [profile["id"] for profile in profile_options]
    default_profile = get_default_profile_id(qdef, category_key)
    if st.session_state.get("profile_id") not in available_profile_ids:
        st.session_state["profile_id"] = (
            default_profile if default_profile in available_profile_ids else available_profile_ids[0]
        )
    profile_id = st.session_state["profile_id"]
    active_profile = get_profile_by_id(qdef, category_key, profile_id)
else:
    profile_id = None
    active_profile = {}

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

image_path = _hero_path(hero_image)


# Equipment info display - mobile-friendly layout
st.markdown("### Equipment Specifications")

col1, col2 = st.columns([1, 1])

with col1:
    st.markdown(f"**Weight:** {model_weight}")
    st.markdown(f"**Width:** {model_width}")

with col2:
    st.markdown(f"**Depth:** {model_depth}")
    st.markdown(f"**Height:** {model_height}")

# Mobile-responsive styling for dimensions
st.markdown("""
<style>
/* Stack columns on mobile for better readability */
@media (max-width: 480px) {
  .stColumn {
    width: 100% !important;
    flex: 1 1 100% !important;
  }
  
  /* Make text larger and more readable on mobile */
  .stMarkdown p {
    font-size: 16px !important;
    line-height: 1.6 !important;
  }
}
</style>
""", unsafe_allow_html=True)

# Responsive hero image - prevents horizontal scrolling on mobile
st.markdown("""
<style>
.hero-wrap {
  display: flex;
  justify-content: center;
  margin: 1rem 0;
  width: 100%;
  overflow: hidden;  /* Prevent horizontal scroll */
}

.hero-wrap img {
  display: block;
  width: 100% !important;
  height: auto !important;
  object-fit: contain;
}

/* Mobile Portrait: phones up to 480px */
@media (max-width: 480px) {
  .hero-wrap {
    margin: 0.5rem 0;
  }
  .hero-wrap img {
    max-width: 100% !important;  /* Fill screen width */
    max-height: 60vh !important;  /* Limit height to 60% of viewport */
  }
}

/* Mobile Landscape: phones 481px - 767px */
@media (min-width: 481px) and (max-width: 767px) {
  .hero-wrap {
    max-width: 90vw !important;
  }
}

/* Tablet: 768px - 1024px */
@media (min-width: 768px) and (max-width: 1024px) {
  .hero-wrap {
    max-width: 500px !important;
  }
}

/* Desktop: 1025px and up */
@media (min-width: 1025px) {
  .hero-wrap {
    max-width: 500px !important;
  }
}
</style>
""", unsafe_allow_html=True)

if image_path and os.path.exists(image_path):
    # On desktop, use narrow columns to constrain image width
    # On mobile, columns auto-adjust
    col1, col2 = st.columns([1, 3])
    with col1:
        st.image(image_path, caption=f"{make} {model}")


# Prepare composed sections for current selection
base_sections = always_included_sections(qdef)
profile_sections, _ = build_sections_for_profile(qdef, category_key, profile_id)
sections_composed = base_sections + profile_sections
sections_composed = _merge_runtime_questions_into_sections(
    sections_composed,
    qdef=qdef,
    category_key=category_key,
    make_key=make_key,
    model_key=model_key,
    customer_id=st.session_state.get("customer_id") if st.session_state.get("customer_id") not in {None, "__none__", "__manual__"} else None,
)

# Merge overrides and apply to sections
merged = merge_overrides(qdef, category=category, make=make, model=model)
sections_used = apply_field_overrides(sections_composed, merged)

# Initialize form_data as single source of truth
if "form_data" not in st.session_state:
    st.session_state["form_data"] = {}

# On model change, seed defaults
curr_model_key = st.session_state.get("_current_model_key")
if curr_model_key != model_key:
    # reset error flag on model change
    st.session_state["_show_required_errors"] = False
    st.session_state["_current_model_key"] = model_key
    # seed defaults from overrides directly into form_data
    seed_defaults(st.session_state["form_data"], merged.get(
        "defaults", {}), overwrite_empty_only=True)

# Single source of truth: answers IS st.session_state["form_data"]
answers: Dict[str, Any] = st.session_state["form_data"]

# ==================== Autosave Helper Function ====================
def try_autosave():
    """
    Attempt to autosave current form state if enough time has passed.
    Runs silently - shows subtle indicator only on success.
    """
    if not st.session_state.get("survey_id"):
        return
    
    if not (make and model):
        return
    
    current_time = time.time()
    last_save_time = st.session_state.get("last_autosave", 0)
    
    if current_time - last_save_time > Config.AUTOSAVE_INTERVAL_SECONDS:
        save_data = build_current_draft_payload()
        if not has_meaningful_draft_data(save_data):
            return

        if db.save_draft(st.session_state["survey_id"], save_data, user_id=st.session_state.get("tech_id", "")):
            st.session_state["last_autosave"] = current_time
            # Subtle success indicator (don't distract user)
            st.caption("Draft saved")

# --- Upload Site Photos with Server-Side compression ---
st.subheader("2. Upload Site Photos")

# Determine photo rules: use model.photo_rules, fallback to conservative defaults
rules = dict(model_meta.get("photo_rules", {}) or {})

max_count: int = int(rules.get("max_count", Config.MAX_PHOTOS_DEFAULT))
max_mb_each: float = float(rules.get("max_mb_each", Config.MAX_PHOTO_SIZE_MB))

# Import server-side compression handler
from utils.photo_handler import create_photo_uploader_with_compression

# Initialize session state for photos if not present
if "uploaded_photos" not in st.session_state:
    st.session_state["uploaded_photos"] = []

restored_photos = answers.get("photos", [])
if not isinstance(restored_photos, list):
    restored_photos = []

# Use new compressed uploader if feature is enabled
if Config.ENABLE_CLIENT_COMPRESSION:
    compressed_photos = create_photo_uploader_with_compression(
        max_photos=max_count,
        max_size_mb=max_mb_each,
        target_max_dimension=Config.MAX_IMAGE_DIMENSION,
        jpeg_quality=Config.PHOTO_QUALITY_JPEG
    )
    
    # Process compressed photos (server-side compression)
    if compressed_photos:
        st.session_state["uploaded_photos"] = compressed_photos
        st.success(f"{len(compressed_photos)} photo(s) ready to add to survey")
        
        # Update answers
        answers["photos"] = compressed_photos
        
        # Set accepted_photos for PDF builder (expects this variable name)
        accepted_photos = compressed_photos
        
        # Show count
        st.caption(f"{len(compressed_photos)} of {max_count} photos attached")
        
        # Preview thumbnails - mobile-friendly grid
        st.markdown("### Photo Preview")
        
        # Mobile-responsive columns
        st.markdown("""
        <style>
        @media (max-width: 480px) {
            .stColumns { 
                flex-direction: column !important;
            }
            .stColumn {
                width: 100% !important;
            }
        }
        </style>
        """, unsafe_allow_html=True)
        
        # Use 2 columns on mobile, 5 on desktop
        num_cols = 5
        cols = st.columns(num_cols)
        
        for i, photo_entry in enumerate(compressed_photos):
            img_bytes = photo_entry.get("data") or b""
            if not img_bytes:
                continue
            with cols[i % num_cols]:
                try:
                    st.image(img_bytes, caption=photo_entry.get("name", "")[:20] + "...", use_column_width=True)
                except Exception:
                    pass
    else:
        accepted_photos = restored_photos
        answers["photos"] = accepted_photos
        st.session_state["uploaded_photos"] = accepted_photos
        st.caption(f"{len(accepted_photos)} of {max_count} photos attached")
else:
    # Fallback to standard file uploader if compression is disabled
    allowed_exts: List[str] = rules.get("allowed_ext", [".jpg", ".png"]) or []
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
    else:
        accepted_photos = restored_photos
    
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
                st.session_state.get('_show_required_errors')),
            visibility_state=_visibility_state_for_sections(answers, sections_used),
        )
        break

# Autosave after Site Information
try_autosave()

# --- Contact Info ---
st.subheader(
    f"4. {lang_map.get('section.contact_info', 'Contact Information')}")
for _sec in sections_used:
    if _sec.get("key") == "contact_info":
        render_section(_sec, answers, lang=lang_map, category=category, make=make, model=model,
                       show_required_errors=bool(st.session_state.get('_show_required_errors')),
                       visibility_state=_visibility_state_for_sections(answers, sections_used))
        break

# Autosave after Contact Info
try_autosave()

# --- Hours of Operation ---
st.subheader("5. Hours of Operation")

days = ["Monday", "Tuesday", "Wednesday",
        "Thursday", "Friday", "Saturday", "Sunday"]

# Default times and step for the time picker
DEFAULT_OPEN_TIME = datetime.time(8, 0)   # 08:00
DEFAULT_CLOSE_TIME = datetime.time(20, 0) # 20:00 (8 PM)
TIME_STEP = datetime.timedelta(minutes=Config.TIME_PICKER_STEP_MINUTES)

# ---------- Quick presets (optional) ----------
st.markdown("**Quick Setup (optional)**")
HOUR_PRESET_OPTIONS = {
    "Custom": None,
    "08:00 to 17:00": (datetime.time(8, 0), datetime.time(17, 0)),
    "08:00 to 20:00": (datetime.time(8, 0), datetime.time(20, 0)),
    "09:00 to 17:00": (datetime.time(9, 0), datetime.time(17, 0)),
    "10:00 to 18:00": (datetime.time(10, 0), datetime.time(18, 0)),
}

selected_hours_template = st.selectbox(
    "Common hours",
    options=list(HOUR_PRESET_OPTIONS.keys()),
    key="hours_quick_template",
    help="Choose a common time range to prefill the open and close fields.",
)

selected_hours_range = HOUR_PRESET_OPTIONS[selected_hours_template]
if selected_hours_range and st.session_state.get("_last_hours_quick_template") != selected_hours_template:
    st.session_state["weekday_open_preset"], st.session_state["weekday_close_preset"] = selected_hours_range
st.session_state["_last_hours_quick_template"] = selected_hours_template

qp_cols = st.columns([1.2, 1.2, 1, 1])
with qp_cols[0]:
    same_weekdays = st.checkbox("Same hours Mon-Fri", key="same_weekdays")
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
st.caption("Enter the hours once here, then apply them to weekdays or the full week.")

apply_cols = st.columns(2)
with apply_cols[0]:
    apply_selected_days = st.button("Apply to selected days", key="apply_hours_presets")
with apply_cols[1]:
    apply_all_days = st.button("Apply to all days", key="apply_hours_all_days")

if apply_selected_days:
    # Apply Mon-Fri block
    if same_weekdays:
        for d in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]:
            st.session_state[f"open_{d}"] = weekday_open
            st.session_state[f"close_{d}"] = weekday_close
            st.session_state[f"closed_{d}"] = False
    # Close weekend
    if weekend_closed:
        for d in ["Saturday", "Sunday"]:
            st.session_state[f"closed_{d}"] = True

if apply_all_days:
    for d in days:
        st.session_state[f"open_{d}"] = weekday_open
        st.session_state[f"close_{d}"] = weekday_close
        st.session_state[f"closed_{d}"] = False

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

# Autosave after Hours of Operation
try_autosave()

# --- Delivery Instructions ---
st.subheader(f"6. {lang_map.get('section.delivery', 'Delivery Instructions')}")
for _sec in sections_used:
    if _sec.get("key") in ("delivery_base", "smart_safe_additions"):
        render_section(_sec, answers, lang=lang_map, category=category, make=make, model=model,
                       show_required_errors=bool(st.session_state.get('_show_required_errors')),
                       visibility_state=_visibility_state_for_sections(answers, sections_used))

# Autosave after Delivery Instructions
try_autosave()

# --- Additional Category Sections ---
for _sec in sections_used:
    if _sec.get("key") not in ("contact_info", "installation_location", "site_info", "delivery_base", "smart_safe_additions"):
        sec_title = lang_map.get(
            _sec.get("title_key", ""), _sec.get("title", ""))
        if sec_title:
            st.subheader(sec_title)
        render_section(_sec, answers, lang=lang_map, category=category, make=make, model=model,
                       show_required_errors=bool(st.session_state.get('_show_required_errors')),
                       visibility_state=_visibility_state_for_sections(answers, sections_used))

# --- Installation Location ---
st.subheader(
    f"7. {lang_map.get('section.installation_location', 'Installation Location')}")
for _sec in sections_used:
    if _sec.get("key") == "installation_location":
        render_section(_sec, answers, lang=lang_map, category=category, make=make, model=model,
                       show_required_errors=bool(st.session_state.get('_show_required_errors')),
                       visibility_state=_visibility_state_for_sections(answers, sections_used))
        break

# Autosave after Installation Location
try_autosave()

# ---------------- Submit -> Validate -> Build PDF ----------------

def _collect_missing_required(
    sections: List[Dict[str, Any]],
    state: Dict[str, Any],
    visibility_state: Dict[str, Any],
) -> List[str]:
    missing: List[str] = []
    for sec in sections:
        for fld in sec.get("fields", []) or []:
            if not fld.get("required"):
                continue
            if not visible_if_field(fld, visibility_state, category, make, model):
                continue
            v = state.get(fld.get("name"))
            is_empty = (v is None) or (isinstance(v, str) and v.strip() == "") or (
                isinstance(v, list) and len(v) == 0)
            if is_empty:
                missing.append(fld.get("name"))
    return missing


if st.button("Generate and Download PDF"):
    logger.info("PDF generation initiated", extra={"make": make, "model": model})
    
    # Merge collected inputs into session_state-based answers for validation
    validate_state = dict(st.session_state)
    validate_state.update(answers)
    filtered_validate_state = _visibility_state_for_sections(validate_state, sections_used)

    missing_fields = _collect_missing_required(
        sections_used,
        validate_state,
        filtered_validate_state,
    )
    # Non-blocking: highlight missing but continue generating the report
    st.session_state["_show_required_errors"] = True if missing_fields else False
    if missing_fields:
        logger.warning(f"Missing {len(missing_fields)} required fields", extra={"fields": missing_fields})
        st.warning(
            "Some recommended fields are missing. The report will still be generated."
        )

    # Delegate PDF construction + filename logic to dedicated builder
    try:
        pdf_bytes, file_name = build_survey_pdf(
        answers=filtered_validate_state,
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
        accepted_photos=accepted_photos,
        max_count=max_count,
        lang_map=lang_map,
        category=category,
        )
        logger.info("PDF generated successfully", extra={"pdf_filename": file_name, "size_bytes": len(pdf_bytes)})
        
        # Mark survey as complete in database
        if st.session_state.get("survey_id"):
            db.mark_complete(st.session_state["survey_id"], file_name)
            logger.info("Survey marked complete", extra={
                "survey_id": st.session_state["survey_id"],
                "pdf_filename": file_name
            })
        
        st.success("PDF generated successfully.")
        st.download_button(
            label="Download PDF Report",
            data=pdf_bytes,
            file_name=file_name,
            mime="application/pdf",
        )
    except Exception as e:
        logger.error("PDF generation failed", extra={"error": str(e), "make": make, "model": model}, exc_info=True)
        st.error(f"Failed to generate PDF: {str(e)}")
