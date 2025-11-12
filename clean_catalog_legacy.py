# clean_catalog_legacy.py (one-time)
import json
import os

p = os.path.join("data", "catalog.json")
with open(p, "r", encoding="utf-8") as f:
    cat = json.load(f)

for k in ("models_by_make", "models", "categories", "category_defaults"):
    cat.pop(k, None)

with open(p, "w", encoding="utf-8") as f:
    json.dump(cat, f, ensure_ascii=False, indent=2)

print("Removed legacy keys from catalog.json")
