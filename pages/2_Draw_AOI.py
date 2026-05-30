"""Step 1: Draw AOI on the map.

Lets the user draw a polygon, scan tile coverage, and pick a resolution +
river name. Persists everything into st.session_state so downstream pages
pick it up.
"""
from __future__ import annotations
import os
os.environ.setdefault("HYRIVER_CACHE_DISABLE", "true")

import streamlit as st
import geopandas as gpd
from shapely.ops import unary_union
from streamlit_folium import st_folium

from ui.map import (
    build_aoi_map,
    extract_aoi_from_map,
    save_aoi_geojson,
    fetch_dem_coverage_footprints,
)
import data_collections as dc

st.set_page_config(page_title="Draw AOI", layout="wide")
st.title("Step 1 — Draw Area of Interest")

# Defaults
ss = st.session_state
ss.setdefault("aoi_gdf", None)
ss.setdefault("coverage_data", None)
ss.setdefault("show_coverage_layers", False)
ss.setdefault("map_center", [39.8283, -98.5795])
ss.setdefault("map_zoom", 5)
ss.setdefault("scanned_river_list", [])
ss.setdefault("available_resolutions", [])
ss.setdefault("project_folder", "./Project")

ss["project_folder"] = st.text_input("Project folder", ss["project_folder"])
os.makedirs(ss["project_folder"], exist_ok=True)

with st.container(border=True):
    st.markdown("### Draw your AOI")
    m = build_aoi_map(
        center=ss["map_center"],
        zoom_start=ss["map_zoom"],
        coverage_data=ss["coverage_data"],
        show_coverage_layers=ss["show_coverage_layers"],
    )
    map_data = st_folium(m, width=None, height=500, key="aoi_wizard_map")

    aoi_gdf = extract_aoi_from_map(map_data)
    if aoi_gdf is not None and not aoi_gdf.empty:
        ss["aoi_gdf"] = aoi_gdf
    elif map_data and map_data.get("all_drawings") is None:
        ss["aoi_gdf"] = None

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Scan current viewport for tiles", use_container_width=True):
            bounds_data = (map_data or {}).get("bounds") or {}
            sw = bounds_data.get("_southWest") or {}
            ne = bounds_data.get("_northEast") or {}
            if sw and ne:
                bounds = (sw["lat"], sw["lng"], ne["lat"], ne["lng"])
                ss["map_center"] = [(sw["lat"] + ne["lat"]) / 2, (sw["lng"] + ne["lng"]) / 2]
                if map_data.get("zoom"):
                    ss["map_zoom"] = map_data["zoom"]
                aoi_geom = unary_union(ss["aoi_gdf"].geometry) if ss["aoi_gdf"] is not None else None
                with st.status("Querying USGS tile catalog..."):
                    ss["coverage_data"] = fetch_dem_coverage_footprints(bounds, aoi_geom=aoi_geom, sink=st)
                    ss["show_coverage_layers"] = True
                st.rerun()
            else:
                st.warning("Map isn't ready — pan/zoom, then retry.")
    with col2:
        ss["show_coverage_layers"] = st.checkbox(
            "Show coverage layers",
            value=ss["show_coverage_layers"],
            disabled=ss["coverage_data"] is None,
        )

with st.container(border=True):
    st.markdown("### Scan AOI for rivers + resolutions")
    if st.button("Scan AOI", use_container_width=True, disabled=ss["aoi_gdf"] is None):
        tpath = os.path.join(ss["project_folder"], "temp_scan.geojson")
        save_aoi_geojson(ss["aoi_gdf"], tpath)
        with st.status("Scanning..."):
            ss["scanned_river_list"] = dc.scan_nhd_rivers(tpath)
            avail = dc.get_available_project_resolutions(tpath)
            if not avail:
                avail = dc.get_available_wcs_resolutions(tpath)
            ss["available_resolutions"] = avail

    if ss["available_resolutions"]:
        ss["dem_res_input"] = st.selectbox(
            "Resolution",
            options=ss["available_resolutions"],
            format_func=lambda x: f"{x}m",
        )
    if ss["scanned_river_list"]:
        ss["selected_river_name"] = st.selectbox("River", ss["scanned_river_list"])

st.page_link("pages/3_Configure.py", label="Next: Configure run →") if os.path.exists(
    os.path.join(os.path.dirname(__file__), "3_Configure.py")
) else st.caption("Next page will be Configure (coming up).")
