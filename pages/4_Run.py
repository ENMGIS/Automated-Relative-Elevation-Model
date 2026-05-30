"""Step 3: Run the pipeline.

Runs DEM → river → hillshade → REM → styling via pipeline.py and writes a
run manifest. Uses st.status for per-stage feedback.
"""
from __future__ import annotations
import os
os.environ.setdefault("HYRIVER_CACHE_DISABLE", "true")
os.environ.setdefault("PROJ_NETWORK", "OFF")

import time
import streamlit as st

from ui.map import save_aoi_geojson
import pipeline as pl
import rem_cache

st.set_page_config(page_title="Run", layout="wide")
st.title("Step 3 — Run REM")

ss = st.session_state
if ss.get("aoi_gdf") is None:
    st.error("No AOI — go to Step 1.")
    st.stop()
if not ss.get("selected_ramps"):
    st.error("Pick at least one color ramp in Step 2.")
    st.stop()

proj_dir = ss.get("project_folder", "./Project")
os.makedirs(proj_dir, exist_ok=True)

aoi_path = os.path.join(proj_dir, "AOI_streamlit.geojson")
save_aoi_geojson(ss["aoi_gdf"], aoi_path)

engine_map = {
    "HAND (Hydrologic)": "hand",
    "Flow-Weighted":     "projection",
    "IDW (legacy)":      "idw",
}
engine = engine_map.get(ss.get("engine_choice", "HAND (Hydrologic)"), "hand")

total_cores = os.cpu_count() or 4
cpu_util = ss.get("cpu_util_percent", 75) / 100.0
compute_threads = max(1, min(total_cores, int(round(total_cores * cpu_util))))
download_threads = max(1, total_cores // 2)

comp_max = float(ss["comp_max_m"]) if str(ss.get("comp_max_m", "")).strip() else None
viz_max = float(ss["viz_max_m"]) if str(ss.get("viz_max_m", "")).strip() else None

cfg = pl.RemPipelineConfig(
    project_folder=proj_dir,
    aoi_geojson_path=aoi_path,
    data_source="nhd",
    resolution=int(ss.get("dem_res_input") or 10),
    river_name=ss.get("selected_river_name"),
    spacing=int(ss.get("spacing", 20)),
    engine=engine,
    k_neighbors=int(ss.get("k_neighbors", 8)),
    max_value=comp_max,
    selected_ramps=list(ss["selected_ramps"]),
    bg_type=ss.get("bg_type", "hillshade"),
    bg_alpha=float(ss.get("bg_alpha", 0.5)),
    rem_alpha=float(ss.get("rem_alpha", 1.0)),
    viz_max_m=viz_max,
    use_discrete_colors=bool(ss.get("use_discrete_colors", False)),
    download_threads=download_threads,
    compute_threads=compute_threads,
)

st.caption(
    f"Threads: {download_threads} download / {compute_threads} compute • "
    f"Resolution: {cfg.resolution}m • Engine: {cfg.engine}"
)

if not st.button("Run pipeline", type="primary", use_container_width=True):
    st.stop()

t0 = time.time()

with st.status("Downloading DEM...", expanded=True) as s:
    dem_file = pl.acquire_dem(cfg)
    s.update(label=f"DEM ready: {os.path.basename(dem_file)}", state="complete", expanded=False)

with st.status("Fetching river...", expanded=True) as s:
    river_path = pl.acquire_river(cfg, dem_file)
    s.update(label=f"River: {os.path.basename(river_path)}", state="complete", expanded=False)

with st.status("Computing hillshade...", expanded=False) as s:
    hs = pl.make_hillshade(cfg, dem_file)
    s.update(label=f"Hillshade: {os.path.basename(hs)}", state="complete")

with st.status(f"Computing REM ({cfg.engine})...", expanded=True) as s:
    rem_file = pl.compute_rem(cfg, dem_file, river_path)
    s.update(label=f"REM: {os.path.basename(rem_file)}", state="complete", expanded=False)

# Styling is still handled in app.py; for now just finalize + manifest.
manifest_path = pl.write_manifest(cfg, dem_file, rem_file, pngs=[])

elapsed = time.time() - t0
mins, secs = divmod(elapsed, 60)
st.success(f"Done in {int(mins)}m {int(secs)}s. Manifest: {os.path.basename(manifest_path)}")

with st.expander("Manifest"):
    m = rem_cache.read_manifest(proj_dir)
    st.json(m)
