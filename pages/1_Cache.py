"""Cache management page.

A minimal Streamlit page to inspect and manage the on-disk tile cache.
This is the first step toward a multi-page wizard; more pages (Draw AOI,
Configure, Run, Results) will land next to this one.
"""
from __future__ import annotations
import os
os.environ.setdefault("HYRIVER_CACHE_DISABLE", "true")

import streamlit as st
import rem_cache

st.set_page_config(page_title="REM Cache", layout="wide")
st.title("Tile Cache")

stats = rem_cache.cache_stats()
col1, col2, col3 = st.columns(3)
col1.metric("Cached tiles", f"{stats['count']:,}")
col2.metric("Disk used", f"{stats['bytes'] / (1024**3):.2f} GB")
col3.metric("Cache root", stats["root"], help="Override via REM_CACHE_DIR env var")

st.divider()

st.caption(
    "Tiles downloaded from USGS TNM / S3 are cached here across runs. "
    "Repeat runs on the same AOI reuse the cache and skip the network."
)

if st.button("Clear cache", type="secondary"):
    rem_cache.clear_cache()
    st.success("Cache cleared.")
    st.rerun()
