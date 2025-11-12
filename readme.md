# 📋 Site Survey Form (Streamlit) — Data-driven Catalog + Category Question Packs

A web-based Site Survey Form for documenting installation details and generating a downloadable PDF report.

## 🚀 What’s new in this refactor

- JSON-backed data model (no DB):
  - Catalog in `data/catalog.json` (categories, makes, models, hero images, dimensions, photo rules)
  - Questions + overrides in `data/questions.json`
  - Localization keys in `lang/en.json` (FR later)
- Category-based question packs with override merge chain:
  - Scope order: `*` → `category:<name>` → `make:<name>` → `model:<Make|Model>`
  - Override types: `required`, `defaults`, `hide_fields`, `insert_after`
- Dependent selects flow: Category → Make → Model
  - Category does not filter Make; Make filters Model choices
- Visible-if DSL with ops and asll/any groups
- Photo rules validation (per category defaults; model can override)
- Same PDF output and layout, now sourced from the catalog JSON
- Streamlit deprecation fixes (no `use_container_width` usage; time inputs use HH:MM)

## 🧩 Folder Structure

```
.
├─ main.py
├─ form_renderer.py
├─ questions.py               # thin loader shim → loads data/questions.json
├─ data_loader.py
├─ overrides.py
├─ visible_if.py
├─ data/
│  ├─ catalog.json
│  ├─ questions.json
│  └─ customer_models.json    # reserved; unused now
├─ lang/
│  └─ en.json
├─ assets/
│  ├─ tidel_d3.png
│  └─ tidel_d4.png
├─ requirements.txt
└─ pages/
   └─ 99_Admin.py             # placeholder scaffold
```

## 🧑‍💻 Local Setup

```bash
pip install -r requirements.txt
streamlit run main.py
```

Then open: <http://localhost:8501>

## 🗂 Data Model Overview

- data/catalog.json
  - categories: list of available categories (e.g., Smart Safe, Recycler, Dispenser)
  - makes: list of makes (e.g., TiDel, Kisan)
  - models_by_make: map Make → [Model...]
  - models: keyed by "Make|Model", containing:
    - category, name, make
    - dimensions: weight, width, depth, height
    - hero_image: filename under assets/
    - photo_rules (optional): max_count, max_mb_each, allowed_ext
  - category_defaults: per-category defaults (currently photo_rules)

- data/questions.json
  - base_sections: common sections across all
  - category_packs: category-specific sections
  - overrides: scope-based changes and insertions
    - allowed fields: required, defaults, hide_fields, insert_after

- lang/en.json
  - localization map used by title_key and label_key

## ✅ How to: Add a new model in 60 seconds

1) Edit `data/catalog.json`:

- Add the model name under `models_by_make["<Make>"]`
- Add a `models["<Make>|<Model>"]` entry with category, dimensions, and a hero image filename (place the image under `assets/`)

Example:

```json
{
  "models_by_make": {
    "TiDel": ["D3 w/Storage Vault", "D4", "D5"]
  },
  "models": {
    "TiDel|D5": {
      "category": "Smart Safe",
      "name": "D5",
      "make": "TiDel",
      "dimensions": {
        "weight": "55 kg / 121 lb",
        "width": "280 mm / 11.0 in",
        "depth": "505 mm / 19.9 in",
        "height": "740 mm / 29.1 in"
      },
      "hero_image": "tidel_d5.png",
      "photo_rules": { "max_count": 12, "max_mb_each": 8, "allowed_ext": [".jpg", ".png"] }
    }
  }
}
```

2) Put `tidel_d5.png` into `assets/`.
3) Run or refresh the app.

## ✅ How to: Add a new field to a category pack

1) Edit `data/questions.json` → `category_packs["<Category>"]`.
2) Add a field with a `label_key` from `lang/en.json`. Supported types:
   - text, textarea, radio, time, number, select, multiselect, checkbox, file
3) Optional visibility via DSL:
   - Groups: `{ "all":[... ] }` or `{ "any":[... ] }`
   - Clause: `{ "field":"<name>", "op":"eq|neq|in|nin|gt|gte|lt|lte|contains", "value": <v> }`

Example:

```json
{
  "key": "power_network",
  "title_key": "section.power_network",
  "fields": [
    { "name":"has_ethernet", "label_key":"field.has_ethernet", "type":"radio", "options":["Yes","No"], "required":true },
    { "name":"ethernet_distance_m", "label_key":"field.ethernet_distance_m", "type":"number",
      "visible_if": { "all":[{ "field":"has_ethernet", "op":"eq", "value":"Yes" }] } }
  ]
}
```

## ✅ How to: Set a model-specific default via overrides

1) Edit `data/questions.json` → `overrides`.
2) Use a `model:<Make>|<Model>` scope and set defaults.

Example (set default for a field when TiDel D4 is chosen):

```json
{
  "overrides": {
    "model:TiDel|D4": {
      "defaults": { "stairs_required": "Yes" }
    }
  }
}
```

Other override capabilities:

- required: `["field_a","field_b"]` (merged as a union across scopes)
- hide_fields: `["field_to_hide"]` (merged as a union)
- insert_after: `[ { "after":"path_desc", "field": { ...new field def... } } ]` (concatenated in order)

Scope order and precedence (later wins for defaults, others merge):
`*` → `category:<name>` → `make:<name>` → `model:<Make|Model>`

## 🧪 Acceptance Checklist Coverage

- Dependent selects: Category → Make → Model (model is filtered by make)
- Question packs vary by category; base sections always included
- Overrides:
  - Global: `store_name` required
  - Smart Safe: `loading_dock` required
  - Insert: `stairs_required` after `path_desc`
  - Kisan: hide `stairs_required`
  - TiDel D4: default `stairs_required = Yes`
- Visible-if: `stairs_count` when `loading_dock == "No"`; hidden fields are not required
- Photos: enforces count, size (MB), and extension per category/model rules
- Localization: all labels/titles via `lang/en.json` (FR later)
- PDF: uses hero image + dimensions from catalog; hour inputs show HH:MM
- Validation:
  - Unique field names per section
  - `insert_after.after` must reference an existing field
  - `visible_if` references must exist (including virtual `__category__`, `__make__`, `__model__`)
- Admin page scaffold under `pages/99_Admin.py`

## ☁️ Deploy to Streamlit Cloud

1. Push to a public GitHub repository.
2. Go to <https://share.streamlit.io>
3. Select your repo/branch, and set Main file path to `main.py`.
4. Streamlit installs dependencies automatically.

## 🧰 Notes

- JSON is cached with `@st.cache_data(show_spinner=False)`
- Time inputs are minute-granularity (HH:MM; no seconds)
- Images should be placed under `assets/` and referenced by filename in catalog
- If a hero image is missing, a sidebar warning appears (non-blocking)
- For initial localization, use `lang/en.json`; FR can be added later as `lang/fr.json`
