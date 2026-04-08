# Site Survey Web App – Changelog

## v0.3.0 – 2025-12-02

### Overview

This release focuses on:

- Keeping data alive during normal use (session safety)
- Making radios behave properly and start “blank”
- Cleaning up the stairs / loading dock questions
- Fixing photo orientation and shrinking PDF sizes

---

### User-facing changes

#### Form answers are more resilient

- Normal Streamlit reruns no longer wipe answers.
- Widget values are stored in the browser session; as long as the tab stays open and you don’t refresh, your entries survive:
  - “Connecting…” blips
  - Most app switches on the phone
- **Still true:** if you refresh the page, close the tab, or the OS kills the browser, the survey is lost.

#### Photo uploads are safer

- If a single photo fails validation, it **no longer clears the entire form**.
- Valid photos remain attached; only the bad file is skipped with an error.

#### Photos now auto-rotate

- Photos taken on phones should now appear upright in:
  - The app’s photo preview, and
  - The generated PDF
- Orientation is read from the image’s EXIF metadata. If any image still shows sideways or upside down, Wayne can send the PDF + original photo for debugging.

#### Smaller PDF files

- Survey photos are now resized and compressed before being embedded in the PDF.
- Typical site survey PDFs should drop from around **8 MB** to roughly **2–3 MB**, depending on photo count and resolution.
- This makes emailing and storing surveys much easier.

#### Stairs question always visible and better placed

- The stairs count question (`field.stairs_count`) for delivery is no longer conditional.
- It now always appears directly under:

  > Describe the flooring along the path from delivery point to storage location.

- If that field is blank in a PDF, it clearly indicates the tech did not provide a stairs count.
- The old Smart Safe–only `stairs_count` pack with broken `visible_if` logic tied to `loading_dock` has been removed.

#### Loading dock is no longer pre-selected

- The **“Loading dock”** radio question no longer quietly defaults to “No dock – lift gate required”.
- It now starts on a neutral `--- Select one ---` option.
- If it is left on the placeholder, managers can see that the question was never answered.

#### Yes/No radios now behave on the first tap

- Fixed a bug where changing from **Yes → No** (or between any two options) sometimes required **two taps** because defaults were being re-applied on rerun.
- Changing any radio value now:
  - Updates immediately on the first tap, and
  - Stays selected after the page reruns.

#### Radios now start “blank”

- All radio questions now include a placeholder option: `--- Select one ---`.
- Behavior:
  - On a new survey with no default, the placeholder is selected initially.
  - If the tech never changes it, the answer is treated as **empty** and appears blank in the PDF.
  - If the tech chooses a real option, that value is saved and persists across reruns.
- Radios with explicit defaults (e.g. model-specific flags) still start with the real default selected, but the placeholder option remains available if the tech needs to clear the answer.

---

### Technical changes

#### Unified widget key / state model

All question widgets rendered from `questions.json` now:

- Use the field `name` as their Streamlit `key` (no more `section__field` keys).
- Store their value in `st.session_state[name]`.
- Mirror that value into `st.session_state["form_data"][name]` (the `answers` dict) after each render.

This removes duplicated/conflicting state and makes each field’s value come from one canonical place.

#### Session state is canonical

`_init_field_state(field, answers)` was rewritten so that:

```python
if name in st.session_state:
    answers[name] = st.session_state[name]
    return
```

Once a widget has a value in `st.session_state[name]`, that value is always treated as the single source of truth.

Defaults (from overrides or `field["default"]`) are only applied once, before the first render of a field.

#### Radio implementation details

Constant added:

```python
RADIO_EMPTY_LABEL = "--- Select one ---"
```

All radios now:

- Render with `options = [RADIO_EMPTY_LABEL] + field["options"]`.
- Use `key = name` (the field name).

After rendering:

- If the placeholder is selected → `answers[name] = None`.
- Otherwise → `answers[name] = selected_option_string`.

No `index=` parameter is used anywhere for radios.

Defaults for radios come from `_init_field_state` seeding `st.session_state[name]` once, not from passing an `index` on every rerun.

#### Stairs / loading dock cleanup

- `stairs_count` was removed from the Smart Safe–specific `category_packs`.
- `stairs_count` was added into the `delivery_base` section directly under `delivery_floor_desc`.
- The broken `visible_if` logic (“only show stairs when `loading_dock == No`”) has been removed.
- Global overrides no longer set a default for `loading_dock`, so that question is never silently pre-answered.

#### Photo and PDF handling

Image handling now:

- Reads EXIF rotation flags and applies them so images render upright.
- Resizes images to sane maximum dimensions for the PDF page.
- Encodes JPEGs with higher compression to reduce size while keeping detail readable.

`pdf_builder.py` still uses the `answers` dict; with the new state model this data is stable and matches what the user sees in the UI.

#### Photo uploads now accept .JPEG correctly

- Default allowed extensions for site photos are now `.jpg`, `.jpeg`, and `.png`.
- The file uploader and server-side validation both use the same normalized extension list.
- iPhone photos with `.jpeg` extensions no longer trigger “invalid extension” errors.

---

### Known limitations (for technicians)

#### No server-side storage yet

The app still does not save surveys to a database.

If you:

- Refresh the page,
- Close the tab, or
- The phone/OS kills the browser,

all entered data is lost.

#### Connection drops

Short “Connecting…” events and quick app switches are now much safer; data should normally survive.

A long network loss or leaving the tab in the background long enough for the OS to kill it can still wipe the session.

---

### Reporting issues

If you see:

- Sideways/rotated photos,
- PDFs that are still unusually large,
- Fields that don’t hold their values,

please report with:

- Store name / site ID
- Approximate time of survey
- A copy of the generated PDF
- If possible, one or two of the original photo files
