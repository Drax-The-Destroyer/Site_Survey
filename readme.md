
# 📋 Site Survey Form (Streamlit) — Data-driven Catalog + Category Question Packs

A web-based Site Survey Form for documenting installation details and generating a downloadable PDF report.

## 🚀 What’s new in this refactor

* JSON-backed data model (no DB):

  * Catalog in `data/catalog.json` (categories, makes, models, hero images, dimensions, photo rules)
  * Questions + overrides in `data/questions.json`
  * Localization keys in `lang/en.json` (FR later)
* Category-based question packs with override merge chain:

  * Scope order: `*` → `category:<name>` → `make:<name>` → `model:<Make|Model>`
  * Override types: `required`, `defaults`, `hide_fields`, `insert_after`
* Dependent selects flow: Category → Make → Model

  * Category does not filter Make; Make filters Model choices
* Visible-if DSL with ops and all/any groups
* Photo rules validation (per category defaults; model can override)
* Same PDF output and layout, now sourced from the catalog JSON
* Streamlit deprecation fixes (no `use_container_width`; time inputs use HH:MM)

### 🆕 Recent changes (media, admin, and deployment)

* **Automated media index**

  * `data_loader.load_media_index()` scans both `assets/` and `data/media/` on startup.
  * Builds `data/media/index.json` with:

    * `images[filename] = { "path": <absolute_path>, "ts": <mtime> }`
    * `brochures[filename] = { ... }`
  * You **never edit `index.json` by hand** anymore; just drop files into `assets/` or `data/media/`.

* **Admin ▸ Model Media**

  * Uses the same media index loader (`load_media_index`) instead of its own logic.
  * Hero image & gallery dropdowns are populated from the auto-generated index.
  * Hero and gallery previews:

    * Resolve paths from both `data/media` and `assets`.
    * Show thumbnails at a fixed width so they don’t blow up the layout.
    * Provide download buttons for gallery images and brochures.

* **Main form hero image**

  * Hero image on the Site Survey form is now width-capped (600px) so it’s readable on desktop without taking over the whole screen.
  * Still responsive on tablet/phone.

* **Git / GitHub workflow**

  * Project is now designed to be run from a cloned repo (`C:\Python Projects\Site_Survey`).
  * Local changes are committed and pushed to GitHub, which Streamlit Cloud deploys from.
  * To deploy changes, commit to the repo and push to GitHub; Streamlit Cloud will redeploy automatically.

---

## 🧩 Folder Structure

```text
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
│  ├─ media/
│  │   ├─ index.json          # auto-generated media index (images + brochures)
│  │   └─ *.pdf / *.png ...
│  └─ customer_models.json    # reserved; unused now
├─ lang/
│  └─ en.json
├─ assets/                    # hero / gallery images, logos, misc assets
│  └─ *.png / *.jpg / *.pdf
├─ .streamlit/
│  ├─ config.toml
│  └─ secrets_template.toml
├─ requirements.txt
└─ pages/
   └─ 99_Admin.py             # Admin console (catalog, model media, validation)
```

Old backups and experimental scripts live under:

* `data/old/`
* `old/`
* `pages/old/`

and should generally be ignored in day-to-day work.

---

## 🧑‍💻 Local Setup

From a fresh clone of the repo:

```bash
cd "C:\Python Projects\Site_Survey"
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
streamlit run main.py
```

Then open: [http://localhost:8501](http://localhost:8501)

---

## 🗂 Data Model Overview

* **`data/catalog.json`**

  * `categories`: list of available categories (e.g., Smart Safe, Recycler, Dispenser)
  * `makes`: list of makes (e.g., TiDel, Kisan)
  * `models_by_make`: map `Make → [Model...]`
  * `models`: keyed by `"Make|Model"`, containing:

    * `category`, `name`, `make`
    * `dimensions`: `weight`, `width`, `depth`, `height`
    * `media.hero_image`: filename (must exist in `assets/` or `data/media/`)
    * `media.gallery`: optional list of additional filenames
    * `media.brochures`: optional list of PDF filenames
    * `photo_rules` (optional): `max_count`, `max_mb_each`, `allowed_ext`
  * `category_defaults`: per-category defaults (currently `photo_rules`)

* **`data/questions.json`**

  * `base_sections`: common sections across all categories
  * `category_packs`: category-specific sections
  * `overrides`: scope-based changes and insertions

    * Allowed fields: `required`, `defaults`, `hide_fields`, `insert_after`

* **`lang/en.json`**

  * Localization map used by `title_key` and `label_key`.

* **`data/media/index.json` (auto-generated)**

  * `images`: `{ "<filename>": { "path": "<abs_path>", "ts": <mtime> }, ... }`
  * `brochures`: same structure for PDFs.
  * Rebuilt on app start via `load_media_index()`; do **not** edit manually.

---

## ✅ How to: Add a new model in 60 seconds

1. Edit `data/catalog.json`:

   * Add the model name under `models_by_make["<Make>"]`.
   * Add a `models["<Make>|<Model>"]` entry with category, dimensions, and media configuration.

   Example:

   ```json
   {
     "models_by_make": {
       "TiDel": ["D3 XL SNF", "D4", "D5"]
     },
     "models": {
       "TiDel|D5": {
         "category": "smart_safe",
         "name": "D5",
         "make": "TiDel",
         "dimensions": {
           "weight": "55 kg / 121 lb",
           "width": "280 mm / 11.0 in",
           "depth": "505 mm / 19.9 in",
           "height": "740 mm / 29.1 in"
         },
         "media": {
           "hero_image": "tidel_d5.png",
           "gallery": ["tidel_d5_side.png"],
           "brochures": ["tidel-d5-family-brochure.pdf"]
         },
         "photo_rules": {
           "max_count": 12,
           "max_mb_each": 8,
           "allowed_ext": [".jpg", ".png"]
         }
       }
     }
   }
   ```

2. Drop the image/PDF files into `assets/` or `data/media/`:

   * Images: `.png`, `.jpg`, `.jpeg`
   * Brochures: `.pdf`

3. Run / refresh the app. `load_media_index()` will rebuild `data/media/index.json` automatically, and the Admin Model Media page will see the new files.

---

## ✅ How to: Attach / change model media in Admin

1. Open the **Admin** page (`pages/99_Admin.py`).
2. Select a **Make** and **Model**.
3. Under **Attach**:

   * Choose a **Hero image** (single file) from the dropdown.
   * Choose one or more **Gallery images**.
   * Choose one or more **Brochures / PDFs**.
4. The page will:

   * Show a hero preview (thumbnail, fixed width).
   * Show gallery previews with thumbnails.
   * Show brochure list with file size and download button.
5. Click **Save Media Attachments** to persist changes to `data/catalog.json`.

You do **not** need to touch `index.json`; the auto-indexer handles it.

---

## ✅ How to: Add a new field to a category pack

1. Edit `data/questions.json` → `category_packs["<category_key>"]`.

2. Add a field with a `label_key` from `lang/en.json`. Supported types:

   * `text`, `textarea`, `radio`, `time`, `number`, `select`, `multiselect`, `checkbox`, `file`

3. Optional visibility via DSL:

   * Groups: `{ "all":[... ] }` or `{ "any":[... ] }`
   * Clause:
     `{ "field":"<name>", "op":"eq|neq|in|nin|gt|gte|lt|lte|contains", "value": <v> }`

Example:

```json
{
  "key": "power_network",
  "title_key": "section.power_network",
  "fields": [
    {
      "name": "has_ethernet",
      "label_key": "field.has_ethernet",
      "type": "radio",
      "options": ["Yes", "No"],
      "required": true
    },
    {
      "name": "ethernet_distance_m",
      "label_key": "field.ethernet_distance_m",
      "type": "number",
      "visible_if": {
        "all": [{ "field": "has_ethernet", "op": "eq", "value": "Yes" }]
      }
    }
  ]
}
```

---

## ✅ How to: Set a model-specific default via overrides

1. Edit `data/questions.json` → `overrides`.
2. Use a `model:<Make>|<Model>` scope and set defaults.

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

* `required`: `["field_a","field_b"]` (merged as a union across scopes)
* `hide_fields`: `["field_to_hide"]` (merged as a union)
* `insert_after`:
  `[{ "after": "path_desc", "field": { ...new field def... } }]` (concatenated in order)

Scope order and precedence (later wins for defaults, others merge):
`*` → `category:<name>` → `make:<name>` → `model:<Make|Model>`

---

## 🧪 Acceptance Checklist Coverage

* Dependent selects: Category → Make → Model (model is filtered by make)
* Question packs vary by category; base sections always included
* Overrides:

  * Global: `store_name` required
  * Smart Safe: `loading_dock` required
  * Insert: `stairs_required` after `path_desc`
  * Kisan: hide `stairs_required`
  * TiDel D4: default `stairs_required = Yes`
* Visible-if:

  * `stairs_count` shown when `loading_dock == "No"`
  * Hidden fields are never required
* Photos:

  * Enforces count, size (MB), and extension per category/model rules
* Localization:

  * All labels/titles via `lang/en.json` (FR can be added later as `lang/fr.json`)
* PDF:

  * Uses hero image + dimensions from catalog
  * Hour inputs show HH:MM
* Validation:

  * Unique field names per section
  * `insert_after.after` must reference an existing field
  * `visible_if` references must exist (including virtual `__category__`, `__make__`, `__model__`)
* Admin page:

  * Full Admin console for managing catalog model media (hero/gallery/brochures) and validating media presence.

---

## ☁️ Deploy to Streamlit Cloud

1. Push to the public GitHub repository (`Drax-The-Destroyer/Site_Survey`).
2. Go to [https://share.streamlit.io](https://share.streamlit.io).
3. Select the repo/branch and set Main file path to `main.py`.
4. Streamlit installs dependencies from `requirements.txt` and runs the app.

---

## 🧰 Notes

* JSON is cached with `@st.cache_data(show_spinner=False)`.
* Time inputs are minute-granularity (HH:MM; no seconds).
* Images should be placed under `assets/` or `data/media/` and referenced by filename in catalog.
* `data/media/index.json` is **auto-generated**; if something looks wrong:

  * Check the file actually exists under `assets/` or `data/media/`.
  * Ensure the filename in `catalog.json` matches exactly (case-sensitive).
  * Restart the app so `load_media_index()` can rebuild the index.
* For initial localization, use `lang/en.json`; FR can be added later as `lang/fr.json`.
