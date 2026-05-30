"""Step 4: View outputs of the latest run."""
from __future__ import annotations
import os
import glob

import streamlit as st

import rem_cache

st.set_page_config(page_title="Results", layout="wide")
st.title("Step 4 — Results")

proj_dir = st.session_state.get("project_folder", "./Project")
proj_dir = st.text_input("Project folder", proj_dir)

manifest = rem_cache.read_manifest(proj_dir)
if manifest is None:
    st.info("No run manifest found in this project folder yet.")
    st.stop()

outputs = manifest.get("outputs", {})

col1, col2, col3 = st.columns(3)
col1.metric("REM", os.path.basename(outputs.get("rem") or "-"))
col2.metric("DEM", os.path.basename(outputs.get("dem") or "-"))
col3.metric("Run timestamp", manifest.get("timestamp", "-"))

st.divider()

pngs = outputs.get("pngs") or []
if not pngs:
    pngs = sorted(glob.glob(os.path.join(proj_dir, "*.png")))

for p in pngs:
    if os.path.exists(p):
        st.image(p, caption=os.path.basename(p), use_container_width=True)

with st.expander("Full manifest JSON"):
    st.json(manifest)
