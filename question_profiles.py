from __future__ import annotations

import copy
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


PROFILE_SCHEMA_META_KEYS = {
    "base_sections",
    "category_packs",
    "overrides",
    "question_bank",
    "profiles",
    "profile_defaults",
}

ALWAYS_INCLUDED_SECTION_KEYS = {"site_info", "contact_info"}

SECTION_TITLE_KEY_BY_KEY = {
    "site_info": "section.site_info",
    "contact_info": "section.contact_info",
    "delivery_base": "section.delivery",
    "installation_location": "section.installation_location",
    "power_network": "section.power_network",
}

SECTION_KEY_ALIASES = {
    "delivery": "delivery_base",
    "delivery_instructions": "delivery_base",
    "delivery_base": "delivery_base",
    "installation": "installation_location",
    "installation_location": "installation_location",
    "power_network": "power_network",
    "power": "power_network",
    "networking": "power_network",
    "site_information": "site_info",
    "site_info": "site_info",
    "contact_information": "contact_info",
    "contact_info": "contact_info",
}


def normalize_category_key(value: Any) -> str:
    text = str(value or "").strip().lower().replace("-", "_")
    text = re.sub(r"\s+", "_", text)
    return re.sub(r"[^a-z0-9_]+", "", text)


def slugify(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")


def question_id(question: Dict[str, Any]) -> str:
    return str(
        question.get("id")
        or question.get("name")
        or question.get("key")
        or ""
    ).strip()


def _deepcopy_list(items: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [copy.deepcopy(item) for item in items]


def _normalize_question(raw_question: Dict[str, Any]) -> Dict[str, Any]:
    question = copy.deepcopy(raw_question or {})
    qid = question_id(question)
    if not qid:
        label = str(question.get("label") or question.get("label_key") or "question")
        qid = slugify(label) or "question"

    if not question.get("name"):
        question["name"] = qid
    question["id"] = qid
    question.pop("key", None)
    question["type"] = str(question.get("type") or "text").strip() or "text"
    question["required"] = bool(question.get("required", False))

    if isinstance(question.get("options"), list):
        question["options"] = [str(item) for item in question["options"]]
    elif "options" in question:
        question.pop("options", None)

    if not isinstance(question.get("visible_if"), (dict, list)):
        question.pop("visible_if", None)

    return question


def _normalized_section_key(section: Dict[str, Any], fallback: str = "") -> str:
    if section.get("key"):
        return str(section["key"]).strip()
    return slugify(section.get("title") or section.get("title_key") or fallback) or fallback or "section"


def _normalize_section(raw_section: Dict[str, Any], fallback: str = "") -> Dict[str, Any]:
    section = copy.deepcopy(raw_section or {})
    section["key"] = _normalized_section_key(section, fallback=fallback)
    if section["key"] in SECTION_TITLE_KEY_BY_KEY and not section.get("title_key"):
        section["title_key"] = SECTION_TITLE_KEY_BY_KEY[section["key"]]

    raw_questions = section.get("questions")
    if raw_questions is None:
        raw_questions = section.get("fields", [])

    section["questions"] = [
        _normalize_question(question)
        for question in (raw_questions or [])
        if isinstance(question, dict)
    ]
    section.pop("fields", None)
    return section


def _section_aliases(section: Dict[str, Any]) -> List[str]:
    aliases = []
    for candidate in (
        section.get("key"),
        section.get("title"),
        section.get("title_key"),
    ):
        token = slugify(candidate)
        if token:
            aliases.append(token)
            aliases.append(token.replace("section_", ""))
    return aliases


def _canonical_section_key(section_name: str, existing_sections: Sequence[Dict[str, Any]]) -> str:
    normalized = slugify(section_name)
    if normalized in SECTION_KEY_ALIASES:
        return SECTION_KEY_ALIASES[normalized]

    for section in existing_sections:
        aliases = _section_aliases(section)
        if normalized in aliases:
            return str(section.get("key") or normalized)

    return normalized or "section"


def _merge_section_questions(
    base_section: Dict[str, Any],
    extra_questions: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    merged = copy.deepcopy(base_section)
    seen = {question_id(question) for question in merged.get("questions", [])}
    for question in extra_questions:
        qid = question_id(question)
        if not qid or qid in seen:
            continue
        merged.setdefault("questions", []).append(copy.deepcopy(question))
        seen.add(qid)
    return merged


def _merge_sections(
    existing_sections: Sequence[Dict[str, Any]],
    incoming_sections: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    merged = _deepcopy_list(existing_sections)
    index_by_key = {str(section.get("key")): idx for idx, section in enumerate(merged)}

    for section in incoming_sections:
        key = str(section.get("key") or "")
        if not key:
            continue
        if key in index_by_key:
            idx = index_by_key[key]
            merged[idx] = _merge_section_questions(merged[idx], section.get("questions", []))
            if section.get("title") and not merged[idx].get("title"):
                merged[idx]["title"] = section["title"]
            if section.get("title_key") and not merged[idx].get("title_key"):
                merged[idx]["title_key"] = section["title_key"]
        else:
            index_by_key[key] = len(merged)
            merged.append(copy.deepcopy(section))
    return merged


def _managed_base_sections(qdef: Dict[str, Any]) -> List[Dict[str, Any]]:
    sections = []
    for section in qdef.get("base_sections", []) or []:
        if not isinstance(section, dict):
            continue
        normalized = _normalize_section(section)
        if normalized["key"] in ALWAYS_INCLUDED_SECTION_KEYS:
            continue
        sections.append(normalized)
    return sections


def _collect_category_keys(qdef: Dict[str, Any]) -> List[str]:
    keys = set()

    for key in (qdef.get("question_bank") or {}).keys():
        normalized = normalize_category_key(key)
        if normalized:
            keys.add(normalized)

    for key in (qdef.get("profiles") or {}).keys():
        normalized = normalize_category_key(key)
        if normalized:
            keys.add(normalized)

    for key in (qdef.get("category_packs") or {}).keys():
        normalized = normalize_category_key(key)
        if normalized:
            keys.add(normalized)

    for key, value in (qdef or {}).items():
        if key in PROFILE_SCHEMA_META_KEYS or not isinstance(value, dict):
            continue
        normalized = normalize_category_key(key)
        if normalized:
            keys.add(normalized)

    return sorted(keys)


def _legacy_category_sections(qdef: Dict[str, Any], category_key: str) -> List[Dict[str, Any]]:
    legacy_sections = []
    for raw_key, section_map in (qdef or {}).items():
        if raw_key in PROFILE_SCHEMA_META_KEYS or not isinstance(section_map, dict):
            continue
        if normalize_category_key(raw_key) != category_key:
            continue

        existing = _managed_base_sections(qdef)
        existing += _category_pack_sections(qdef, category_key)

        for section_name, question_list in section_map.items():
            if not isinstance(question_list, list):
                continue
            section_key = _canonical_section_key(section_name, existing + legacy_sections)
            section = {
                "key": section_key,
                "title": str(section_name),
                "title_key": SECTION_TITLE_KEY_BY_KEY.get(section_key),
                "questions": [
                    _normalize_question(question)
                    for question in question_list
                    if isinstance(question, dict)
                ],
            }
            legacy_sections.append(_normalize_section(section, fallback=section_key))
    return legacy_sections


def _category_pack_sections(qdef: Dict[str, Any], category_key: str) -> List[Dict[str, Any]]:
    sections = []
    for raw_key, raw_sections in (qdef.get("category_packs") or {}).items():
        if normalize_category_key(raw_key) != category_key:
            continue
        for section in raw_sections or []:
            if isinstance(section, dict):
                sections.append(_normalize_section(section))
    return sections


def _default_profile_id() -> str:
    return "default"


def _default_profile(category_key: str, sections: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    questions = []
    order = 1
    for section in sections:
        for section_question in section.get("questions", []) or []:
            qid = question_id(section_question)
            if not qid:
                continue
            questions.append({"question_id": qid, "order": order})
            order += 1
    return {
        "id": _default_profile_id(),
        "name": "Default",
        "category": category_key,
        "questions": questions,
        "custom_questions": [],
    }


def _normalize_profile_question(raw_question: Dict[str, Any], order: int) -> Optional[Dict[str, Any]]:
    qid = str(
        raw_question.get("question_id")
        or raw_question.get("id")
        or raw_question.get("name")
        or ""
    ).strip()
    if not qid:
        return None

    item: Dict[str, Any] = {"question_id": qid}
    required = raw_question.get("required")
    if required in (True, False):
        item["required"] = bool(required)

    try:
        item["order"] = int(raw_question.get("order", order))
    except Exception:
        item["order"] = order

    return item


def _normalize_custom_question(raw_question: Dict[str, Any], index: int) -> Optional[Dict[str, Any]]:
    if not isinstance(raw_question, dict):
        return None

    section_key = str(raw_question.get("section_key") or "").strip()
    field = raw_question.get("field")
    if not section_key or not isinstance(field, dict):
        return None

    question = {
        "section_key": section_key,
        "field": _normalize_question(field),
    }
    required = raw_question.get("required")
    if required in (True, False):
        question["required"] = bool(required)
    try:
        question["order"] = int(raw_question.get("order", index))
    except Exception:
        question["order"] = index
    return question


def _normalize_profile(
    raw_profile: Dict[str, Any],
    category_key: str,
    known_question_ids: set[str],
    fallback_name: str,
) -> Dict[str, Any]:
    profile = copy.deepcopy(raw_profile or {})
    profile_id = slugify(profile.get("id") or fallback_name) or _default_profile_id()

    normalized_questions = []
    seen = set()
    for idx, question in enumerate(profile.get("questions", []) or [], start=1):
        if not isinstance(question, dict):
            continue
        normalized = _normalize_profile_question(question, idx)
        if not normalized:
            continue
        qid = normalized["question_id"]
        if qid in seen or qid not in known_question_ids:
            continue
        seen.add(qid)
        normalized_questions.append(normalized)

    custom_questions = []
    for idx, question in enumerate(profile.get("custom_questions", []) or [], start=1):
        normalized = _normalize_custom_question(question, idx)
        if normalized:
            custom_questions.append(normalized)

    return {
        "id": profile_id,
        "name": str(profile.get("name") or fallback_name or profile_id),
        "category": category_key,
        "questions": sorted(normalized_questions, key=lambda item: item.get("order", 0)),
        "custom_questions": custom_questions,
    }


def ensure_question_profile_schema(raw_qdef: Dict[str, Any]) -> Dict[str, Any]:
    qdef = copy.deepcopy(raw_qdef or {})
    qdef.setdefault("base_sections", [])
    qdef.setdefault("category_packs", {})
    qdef.setdefault("overrides", {})

    base_bank: Dict[str, Dict[str, Any]] = {}
    existing_bank = qdef.get("question_bank")

    if isinstance(existing_bank, dict) and existing_bank:
        for raw_category_key, raw_category_bank in existing_bank.items():
            category_key = normalize_category_key(raw_category_key)
            if not category_key:
                continue

            if isinstance(raw_category_bank, dict):
                raw_sections = raw_category_bank.get("sections", [])
            elif isinstance(raw_category_bank, list):
                raw_sections = raw_category_bank
            else:
                raw_sections = []

            base_bank[category_key] = {
                "sections": [
                    _normalize_section(section)
                    for section in raw_sections
                    if isinstance(section, dict)
                ]
            }

    for category_key in _collect_category_keys(qdef):
        merged_sections = _managed_base_sections(qdef)
        merged_sections = _merge_sections(merged_sections, _category_pack_sections(qdef, category_key))
        merged_sections = _merge_sections(merged_sections, _legacy_category_sections(qdef, category_key))

        if category_key in base_bank and base_bank[category_key].get("sections"):
            merged_sections = _merge_sections(merged_sections, base_bank[category_key]["sections"])

        base_bank[category_key] = {"sections": merged_sections}

    qdef["question_bank"] = base_bank

    normalized_profiles: Dict[str, List[Dict[str, Any]]] = {}
    raw_profiles = qdef.get("profiles") if isinstance(qdef.get("profiles"), dict) else {}
    raw_defaults = qdef.get("profile_defaults") if isinstance(qdef.get("profile_defaults"), dict) else {}
    normalized_defaults: Dict[str, str] = {}

    for category_key, bank_entry in base_bank.items():
        known_ids = {
            question_id(question)
            for section in bank_entry.get("sections", [])
            for question in section.get("questions", [])
        }

        raw_category_profiles = raw_profiles.get(category_key) or raw_profiles.get(category_key.replace("_", " ")) or []
        if not isinstance(raw_category_profiles, list) or not raw_category_profiles:
            raw_category_profiles = [_default_profile(category_key, bank_entry.get("sections", []))]

        profiles = []
        seen_profile_ids = set()
        for idx, raw_profile in enumerate(raw_category_profiles, start=1):
            if not isinstance(raw_profile, dict):
                continue
            normalized = _normalize_profile(
                raw_profile,
                category_key,
                known_ids,
                fallback_name=f"Profile {idx}",
            )
            if normalized["id"] in seen_profile_ids:
                continue
            seen_profile_ids.add(normalized["id"])
            profiles.append(normalized)

        if not profiles:
            profiles = [_default_profile(category_key, bank_entry.get("sections", []))]

        normalized_profiles[category_key] = profiles

        preferred_default = slugify(raw_defaults.get(category_key) or raw_defaults.get(category_key.replace("_", " ")) or "")
        available_ids = {profile["id"] for profile in profiles}
        normalized_defaults[category_key] = (
            preferred_default
            if preferred_default in available_ids
            else profiles[0]["id"]
        )

    qdef["profiles"] = normalized_profiles
    qdef["profile_defaults"] = normalized_defaults
    return qdef


def ensure_category_profile_data(qdef: Dict[str, Any], category_key: str) -> Dict[str, Any]:
    normalized = ensure_question_profile_schema(qdef)
    category_key = normalize_category_key(category_key)
    if not category_key:
        return normalized

    if category_key not in normalized["question_bank"]:
        sections = _managed_base_sections(normalized)
        normalized["question_bank"][category_key] = {"sections": sections}

    if category_key not in normalized["profiles"] or not normalized["profiles"][category_key]:
        normalized["profiles"][category_key] = [
            _default_profile(category_key, normalized["question_bank"][category_key].get("sections", []))
        ]

    normalized["profile_defaults"][category_key] = (
        normalized["profile_defaults"].get(category_key)
        or normalized["profiles"][category_key][0]["id"]
    )
    return normalized


def get_question_bank_sections(qdef: Dict[str, Any], category_key: str) -> List[Dict[str, Any]]:
    normalized = ensure_category_profile_data(qdef, category_key)
    category_key = normalize_category_key(category_key)
    return _deepcopy_list(
        (normalized.get("question_bank", {}).get(category_key, {}) or {}).get("sections", [])
    )


def get_profiles_for_category(qdef: Dict[str, Any], category_key: str) -> List[Dict[str, Any]]:
    normalized = ensure_category_profile_data(qdef, category_key)
    category_key = normalize_category_key(category_key)
    return _deepcopy_list((normalized.get("profiles", {}) or {}).get(category_key, []))


def get_default_profile_id(qdef: Dict[str, Any], category_key: str) -> str:
    normalized = ensure_category_profile_data(qdef, category_key)
    category_key = normalize_category_key(category_key)
    default_id = (normalized.get("profile_defaults", {}) or {}).get(category_key)
    if default_id:
        return default_id

    profiles = (normalized.get("profiles", {}) or {}).get(category_key, [])
    return profiles[0]["id"] if profiles else _default_profile_id()


def get_profile_by_id(
    qdef: Dict[str, Any],
    category_key: str,
    profile_id: Optional[str],
) -> Dict[str, Any]:
    profiles = get_profiles_for_category(qdef, category_key)
    wanted = slugify(profile_id)
    for profile in profiles:
        if profile.get("id") == wanted:
            return copy.deepcopy(profile)
    if profiles:
        return copy.deepcopy(profiles[0])
    return _default_profile(normalize_category_key(category_key), [])


def _profile_question_index(profile: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {
        item["question_id"]: item
        for item in profile.get("questions", []) or []
        if isinstance(item, dict) and item.get("question_id")
    }


def build_sections_for_profile(
    qdef: Dict[str, Any],
    category_key: str,
    profile_id: Optional[str],
) -> Tuple[List[Dict[str, Any]], set[str]]:
    sections = get_question_bank_sections(qdef, category_key)
    profile = get_profile_by_id(qdef, category_key, profile_id)
    profile_questions = _profile_question_index(profile)

    built_sections: List[Dict[str, Any]] = []
    included_ids: set[str] = set()

    for section in sections:
        question_rows = []
        for section_index, question in enumerate(section.get("questions", []) or [], start=1):
            qid = question_id(question)
            profile_item = profile_questions.get(qid)
            if not profile_item:
                continue

            field = copy.deepcopy(question)
            required_override = profile_item.get("required")
            if required_override in (True, False):
                field["required"] = bool(required_override)

            question_rows.append(
                (
                    int(profile_item.get("order", section_index)),
                    section_index,
                    field,
                )
            )
            included_ids.add(qid)

        custom_items = []
        for custom_index, custom_question in enumerate(profile.get("custom_questions", []) or [], start=1):
            if custom_question.get("section_key") != section.get("key"):
                continue
            field = copy.deepcopy(custom_question.get("field") or {})
            required_override = custom_question.get("required")
            if required_override in (True, False):
                field["required"] = bool(required_override)
            included_ids.add(question_id(field))
            custom_items.append(
                (
                    int(custom_question.get("order", 10000 + custom_index)),
                    10000 + custom_index,
                    field,
                )
            )

        section_fields = [field for _, _, field in sorted(question_rows + custom_items, key=lambda item: (item[0], item[1]))]
        if not section_fields:
            continue

        built_section = copy.deepcopy(section)
        built_section["fields"] = section_fields
        built_section.pop("questions", None)
        built_sections.append(built_section)

    return built_sections, included_ids


def section_field_names(sections: Sequence[Dict[str, Any]]) -> set[str]:
    names = set()
    for section in sections or []:
        for field in section.get("fields", []) or []:
            name = str(field.get("name") or "").strip()
            if name:
                names.add(name)
    return names


def always_included_sections(qdef: Dict[str, Any]) -> List[Dict[str, Any]]:
    sections = []
    for section in qdef.get("base_sections", []) or []:
        if not isinstance(section, dict):
            continue
        normalized = copy.deepcopy(section)
        if str(normalized.get("key") or "") in ALWAYS_INCLUDED_SECTION_KEYS:
            sections.append(normalized)
    return sections

