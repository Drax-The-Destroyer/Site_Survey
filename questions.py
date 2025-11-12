"""
Declarative form schema loader shim for the Site Survey app.

This file remains to keep 'from questions import FORM_DEFINITION' imports stable.
Internally it loads data/questions.json via data_loader.load_questions().
"""

from __future__ import annotations
from typing import Any, Dict

from data_loader import load_questions

# Load JSON-backed question definition at import time.
FORM_DEFINITION: Dict[str, Any] = load_questions()
