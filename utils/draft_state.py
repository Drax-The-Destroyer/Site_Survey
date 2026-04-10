from __future__ import annotations

import base64
import datetime as dt
import re
from typing import Any, Dict, Mapping


DRAFT_TYPE_KEY = "__draft_type__"
DRAFT_TYPE_TIME = "time"
DRAFT_TYPE_BYTES = "bytes"

DRAFT_SCHEMA_VERSION = 1
DRAFT_ALLOWED_TOP_LEVEL_KEYS = {
    "schema_version",
    "survey_id",
    "customer_id",
    "make_sel",
    "model_sel",
    "profile_id",
    "tech_id",
    "make",
    "model",
    "category",
    "form_data",
}

HOURS_FIELD = "hours"
PHOTOS_FIELD = "photos"
HOUR_DAYS = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)
DEFAULT_OPEN_TIME = "08:00:00"
DEFAULT_CLOSE_TIME = "20:00:00"
TIME_RE = re.compile(r"^\d{1,2}:\d{2}(:\d{2})?$")


def default_hours_template() -> Dict[str, Dict[str, Any]]:
    return {
        day: {
            "open": None if day in {"Saturday", "Sunday"} else DEFAULT_OPEN_TIME,
            "close": None if day in {"Saturday", "Sunday"} else DEFAULT_CLOSE_TIME,
            "closed": day in {"Saturday", "Sunday"},
            "open_24h": False,
        }
        for day in HOUR_DAYS
    }


def _normalize_time_string(value: str) -> str | None:
    if not TIME_RE.match(value.strip()):
        return None

    parts = value.strip().split(":")
    hour = int(parts[0])
    minute = int(parts[1])
    second = int(parts[2]) if len(parts) > 2 else 0
    return f"{hour:02d}:{minute:02d}:{second:02d}"


def _normalize_time_like(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, dt.time):
        return value.strftime("%H:%M:%S")
    if isinstance(value, str):
        return _normalize_time_string(value)
    return None


def serialize_draft_value(value: Any) -> Any:
    if isinstance(value, dt.time):
        return {DRAFT_TYPE_KEY: DRAFT_TYPE_TIME, "value": value.strftime("%H:%M:%S")}

    if isinstance(value, (bytes, bytearray)):
        encoded = base64.b64encode(bytes(value)).decode("ascii")
        return {DRAFT_TYPE_KEY: DRAFT_TYPE_BYTES, "encoding": "base64", "value": encoded}

    if hasattr(value, "getvalue") and hasattr(value, "name"):
        try:
            return {
                "name": str(getattr(value, "name", "upload")),
                "data": serialize_draft_value(value.getvalue()),
            }
        except Exception:
            return {"name": str(getattr(value, "name", "upload"))}

    if isinstance(value, list):
        return [serialize_draft_value(item) for item in value]

    if isinstance(value, dict):
        return {
            str(key): serialize_draft_value(item)
            for key, item in value.items()
            if isinstance(key, str)
        }

    if isinstance(value, (str, int, float, bool)) or value is None:
        return value

    return str(value)


def deserialize_draft_value(value: Any) -> Any:
    if isinstance(value, list):
        return [deserialize_draft_value(item) for item in value]

    if isinstance(value, dict):
        draft_type = value.get(DRAFT_TYPE_KEY)
        if draft_type == DRAFT_TYPE_TIME:
            normalized = _normalize_time_like(value.get("value"))
            if normalized:
                hour, minute, second = (int(part) for part in normalized.split(":"))
                return dt.time(hour, minute, second)
            return value.get("value")
        if draft_type == DRAFT_TYPE_BYTES:
            raw_value = value.get("value", "")
            if isinstance(raw_value, str):
                try:
                    return base64.b64decode(raw_value.encode("ascii"))
                except Exception:
                    return b""
            return b""
        return {key: deserialize_draft_value(item) for key, item in value.items()}

    return value


def _normalize_hours_value(hours: Any) -> Dict[str, Dict[str, Any]]:
    normalized = default_hours_template()
    if not isinstance(hours, Mapping):
        return normalized

    for day in HOUR_DAYS:
        raw_entry = hours.get(day)
        if not isinstance(raw_entry, Mapping):
            continue
        open_24h = bool(raw_entry.get("open_24h"))
        closed = bool(raw_entry.get("closed"))
        if open_24h:
            closed = False
        elif closed:
            open_24h = False
        normalized[day] = {
            "open": None if (closed or open_24h) else _normalize_time_like(raw_entry.get("open")),
            "close": None if (closed or open_24h) else _normalize_time_like(raw_entry.get("close")),
            "closed": closed,
            "open_24h": open_24h,
        }

    return normalized


def _is_meaningful_generic(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (bytes, bytearray)):
        return len(value) > 0
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, list):
        return any(_is_meaningful_generic(item) for item in value)
    if isinstance(value, dict):
        return any(_is_meaningful_generic(item) for item in value.values())
    return True


def is_meaningful_form_value(name: str, value: Any) -> bool:
    if name == HOURS_FIELD:
        return _normalize_hours_value(value) != default_hours_template()

    if name == PHOTOS_FIELD:
        return isinstance(value, list) and len(value) > 0

    return _is_meaningful_generic(value)


def prune_meaningful_form_data(form_data: Any) -> Dict[str, Any]:
    if not isinstance(form_data, Mapping):
        return {}

    meaningful: Dict[str, Any] = {}
    for key, value in form_data.items():
        if not isinstance(key, str):
            continue
        if is_meaningful_form_value(key, value):
            meaningful[key] = value
    return meaningful


def extract_safe_draft_payload(
    source: Mapping[str, Any],
    *,
    make: str | None = None,
    model: str | None = None,
    category: str | None = None,
    profile_id: str | None = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"schema_version": DRAFT_SCHEMA_VERSION}

    for key in ("survey_id", "customer_id", "make_sel", "model_sel", "profile_id", "tech_id", "make", "model", "category"):
        value = source.get(key)
        if isinstance(value, str) and value.strip():
            payload[key] = value

    if make:
        payload["make"] = make
    if model:
        payload["model"] = model
    if category:
        payload["category"] = category
    if profile_id:
        payload["profile_id"] = profile_id

    form_data = source.get("form_data")
    if not isinstance(form_data, Mapping):
        form_data = {}

    legacy_hours = source.get(HOURS_FIELD)
    legacy_photos = source.get("uploaded_photos")
    merged_form_data = dict(form_data)
    if HOURS_FIELD not in merged_form_data and legacy_hours is not None:
        merged_form_data[HOURS_FIELD] = legacy_hours
    if PHOTOS_FIELD not in merged_form_data and legacy_photos is not None:
        merged_form_data[PHOTOS_FIELD] = legacy_photos

    meaningful_form_data = prune_meaningful_form_data(merged_form_data)
    payload["form_data"] = serialize_draft_value(meaningful_form_data)
    return payload


def has_meaningful_draft_data(payload: Mapping[str, Any]) -> bool:
    form_data = payload.get("form_data")
    if not isinstance(form_data, Mapping):
        return False
    restored_form_data = deserialize_draft_value(dict(form_data))
    return bool(prune_meaningful_form_data(restored_form_data))
