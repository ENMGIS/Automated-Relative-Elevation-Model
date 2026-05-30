"""Step 2: Configure REM parameters + visualization.

Reads AOI/river/resolution from session_state and populates pipeline config.
"""
from __future__ import annotations
import os
os.environ.setdefault("HYRIVER_CACHE_DISABLE", "true")

import streamlit as st

from rem_config import COLOR_RAMP_OPTIONS, BACKGROUND_OPTIONS

st.set_page_config(page_title="Configure", layout="wide")
st.title("Step 2 — Configure")

ss = st.session_state
ss.setdefault("spacing", 20)
ss.setdefault("engine_choice", "HAND (Hydrologic)")
ss.setdefault("k_neighbors", 8)
ss.setdefault("cpu_util_percent", 75)
ss.setdefault("comp_max_m", "")
ss.setdefault("viz_max_m", "")
ss.setdefault("selected_ramps", [COLOR_RAMP_OPTIONS[0]])
ss.setdefault("bg_type", BACKGROUND_OPTIONS[0])
ss.setdefault("bg_alpha", 0.5)
ss.setdefault("rem_alpha", 1.0)
ss.setdefault("use_discrete_colors", False)

if ss.get("aoi_gdf") is None:
    st.warning("No AOI yet. Go to **Step 1 — Draw AOI** first.")

with st.container(border=True):
    st.markdown("### Interpolation")
    ss["spacing"] = st.number_input("Spacing (m)", 1, 500, ss["spacing"])
    ss["engine_choice"] = st.radio(
        "Engine",
        ["HAND (Hydrologic)", "Flow-Weighted", "IDW (legacy)"],
        index=["HAND (Hydrologic)", "Flow-Weighted", "IDW (legacy)"].index(ss["engine_choice"]),
        help="HAND follows real flow paths; Flow-Weighted is fast for very large DEMs; IDW is legacy.",
    )
    if ss["engine_choice"] == "IDW (legacy)":
        ss["k_neighbors"] = st.number_input("K neighbors", 4, 300, ss["k_neighbors"])
    ss["cpu_util_percent"] = st.slider("CPU usage", 10, 100, ss["cpu_util_percent"], 5, format="%d%%")
    ss["comp_max_m"] = st.text_input("Max REM (m) — computation", ss["comp_max_m"])

with st.container(border=True):
    st.markdown("### Visualization")
    ss["selected_ramps"] = st.multiselect("Color ramps", COLOR_RAMP_OPTIONS, default=ss["selected_ramps"])
    ss["bg_type"] = st.selectbox(
        "Background",
        BACKGROUND_OPTIONS,
        index=BACKGROUND_OPTIONS.index(ss["bg_type"]) if ss["bg_type"] in BACKGROUND_OPTIONS else 0,
    )
    ss["bg_alpha"] = st.slider("Background transparency", 0.0, 1.0, ss["bg_alpha"])
    ss["rem_alpha"] = st.slider("REM transparency", 0.0, 1.0, ss["rem_alpha"])
    ss["viz_max_m"] = st.text_input("Max REM (m) — visualization", ss["viz_max_m"])
    ss["use_discrete_colors"] = st.checkbox("Discrete colors", value=ss["use_discrete_colors"])

st.caption("Next: **Run** (on app.py for now — the long-form run UI still lives there).")
