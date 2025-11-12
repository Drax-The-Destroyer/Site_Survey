import streamlit as st


def wide_button(label: str, **kwargs):
    """Render a full-width Streamlit button, safely ignoring any width kwarg.

    - Pops an accidental "width" kwarg to avoid TypeError on st.button
    - Defaults to use_container_width=True so the button spans its container
    """
    # Guard against accidental width kwarg on buttons
    kwargs.pop("width", None)
    kwargs.setdefault("use_container_width", True)
    return st.button(label, **kwargs)
