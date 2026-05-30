"""AOI map + DEM coverage footprint helpers.

Extracted from app.py — pure Folium / shapely / requests, no Streamlit state.
The one exception is `fetch_dem_coverage_footprints` which optionally calls
`st.info/warning/success` for user feedback; callers in non-UI contexts can
pass a silent sink.
"""
from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional

import requests
import folium
from folium.plugins import Draw, Fullscreen, MeasureControl, Geocoder
import geopandas as gpd
from shapely.geometry import box as shp_box

logger = logging.getLogger(__name__)


# Silent fallback for non-Streamlit callers (CLI, tests).
class _SilentSink:
    def info(self, *a, **k): pass
    def warning(self, *a, **k): pass
    def success(self, *a, **k): pass


_SILENT = _SilentSink()


def fetch_dem_coverage_footprints(
    bounds: tuple,
    radius_km: float = 100,
    aoi_geom=None,
    sink=None,
) -> Dict[int, List[dict]]:
    """Query USGS TNM (and ScienceBase for Alaska IfSAR) for tile footprints.

    bounds = (south, west, north, east)
    sink   = object with info/warning/success methods (e.g. streamlit).
    """
    sink = sink if sink is not None else _SILENT
    south, west, north, east = bounds
    bbox_str = f"{west},{south},{east},{north}"
    center_lat = (south + north) / 2
    is_alaska_region = center_lat > 50.0

    if is_alaska_region:
        resolution_keywords = {
            1:  ["1 meter", "1m", "one meter"],
            3:  ["3 meter", "3m", "1/9 arc-second", "1/9 arc second"],
            5:  ["5 meter", "5m", "alaska 5 meter", "ak_ifsar", "ifsar", "5m ifsar",
                 "13 arc-second", "13 arc second", "13 arc"],
            10: ["10 meter", "10m", "1/3 arc-second", "1/3 arc second", "0.33 arc"],
            30: ["30 meter", "30m", "1 arc-second", "1 arc second"],
        }
    else:
        resolution_keywords = {
            1:  ["1 meter", "1m", "one meter"],
            3:  ["3 meter", "3m", "1/9 arc-second", "1/9 arc second"],
            5:  ["5 meter", "5m"],
            10: ["10 meter", "10m", "1/3 arc-second", "1/3 arc second", "0.33 arc"],
            30: ["30 meter", "30m", "1 arc-second", "1 arc second"],
        }

    tiles_by_resolution: Dict[int, List[dict]] = {res: [] for res in resolution_keywords}

    # TNM catalog
    try:
        api_url = "https://tnmaccess.nationalmap.gov/api/v1/products"
        params = {"bbox": bbox_str, "prodFormats": "GeoTIFF", "max": 10000}
        r = requests.get(api_url, params=params, timeout=30)
        if r.status_code == 200:
            for item in r.json().get("items", []):
                title = item.get("title", "").lower()
                bbox_item = item.get("boundingBox", {})
                if not bbox_item:
                    continue
                durl = item.get("downloadURL", "")
                is_s1m = "s1m" in title or "standard 1-meter" in title or "/S1M/" in durl
                if is_s1m:
                    continue
                pub_date = item.get("publicationDate", "Unknown")[:10]
                for res, keywords in resolution_keywords.items():
                    if any(kw in title for kw in keywords):
                        try:
                            tgeom = shp_box(
                                float(bbox_item["minX"]), float(bbox_item["minY"]),
                                float(bbox_item["maxX"]), float(bbox_item["maxY"]),
                            )
                            tiles_by_resolution[res].append({
                                "geometry": tgeom,
                                "title": item.get("title", "")[:50] + "...",
                                "date": pub_date,
                            })
                        except Exception:
                            pass
                        break
    except Exception as e:
        sink.warning(f"USGS TNM API error: {e}")

    # ScienceBase IfSAR (Alaska only)
    if is_alaska_region:
        try:
            viewport_geom = shp_box(west, south, east, north)
            sb_url = "https://www.sciencebase.gov/catalog/items"
            sb_params = {
                "parentId": "5641fe98e4b0831b7d62e758",
                "max": 1000,
                "format": "json",
                "fields": "title,spatial,webLinks",
                "bbox": bbox_str,
            }
            r_sb = requests.get(sb_url, params=sb_params, timeout=30)
            if r_sb.status_code == 200:
                for item in r_sb.json().get("items", []):
                    try:
                        title = item.get("title", "")
                        bbox_item = item.get("spatial", {}).get("boundingBox", {})
                        if not bbox_item:
                            continue
                        tgeom = shp_box(
                            float(bbox_item["minX"]), float(bbox_item["minY"]),
                            float(bbox_item["maxX"]), float(bbox_item["maxY"]),
                        )
                        if tgeom.intersects(viewport_geom):
                            tiles_by_resolution[5].append({
                                "geometry": tgeom,
                                "title": title[:50] + "..." if len(title) > 50 else title,
                                "date": "IfSAR",
                            })
                    except Exception:
                        continue
        except Exception:
            pass

    if aoi_geom is not None:
        filtered = {res: [] for res in tiles_by_resolution}
        total_before = sum(len(v) for v in tiles_by_resolution.values())
        for res, tiles in tiles_by_resolution.items():
            filtered[res] = [t for t in tiles if t["geometry"].intersects(aoi_geom)]
        total_after = sum(len(v) for v in filtered.values())
        if total_before > total_after:
            sink.success(
                f"Filtered from {total_before} to {total_after} tiles "
                "(only showing tiles that would be downloaded for your AOI)"
            )
        else:
            sink.info(f"All {total_after} tiles intersect your AOI")
        return filtered

    return tiles_by_resolution


_RES_COLORS = {
    1:  "#0066CC",
    3:  "#00CC66",
    5:  "#00CCCC",
    10: "#FFCC00",
    30: "#FF6600",
}


def build_aoi_map(
    center: List[float],
    zoom_start: int = 8,
    coverage_data: Optional[Dict[int, List[dict]]] = None,
    show_coverage_layers: bool = True,
) -> folium.Map:
    m = folium.Map(location=center, zoom_start=zoom_start, tiles=None, control_scale=True)
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Tiles © Esri", name="Aerial", control=True, show=True,
    ).add_to(m)
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}",
        attr="Tiles © Esri", name="Topo", control=True, show=False,
    ).add_to(m)

    if coverage_data and show_coverage_layers:
        for res in sorted(_RES_COLORS):
            tiles = coverage_data.get(res, [])
            if not tiles:
                continue
            layer = folium.FeatureGroup(name=f"{res}m DEM ({len(tiles)} tiles)", show=True)
            color = "#00FFFF" if res == 5 else _RES_COLORS[res]
            fill_op = 0.4 if res == 5 else 0.25
            weight = 2 if res == 5 else 1
            for tile in tiles:
                b = tile["geometry"].bounds
                geom_json = {
                    "type": "Polygon",
                    "coordinates": [[
                        [b[0], b[1]], [b[2], b[1]], [b[2], b[3]],
                        [b[0], b[3]], [b[0], b[1]],
                    ]],
                }
                folium.GeoJson(
                    geom_json,
                    style_function=lambda x, c=color, w=weight, fo=fill_op: {
                        "fillColor": c,
                        "color": c,
                        "weight": w,
                        "fillOpacity": fo,
                        "interactive": False,
                    },
                    highlight_function=None,
                    tooltip=None,
                    popup=None,
                ).add_to(layer)
            layer.add_to(m)

    Draw(
        export=False,
        position="topleft",
        draw_options={"polyline": False, "circle": False, "marker": False, "circlemarker": False},
    ).add_to(m)
    Fullscreen().add_to(m)
    Geocoder().add_to(m)
    MeasureControl().add_to(m)
    folium.LayerControl(position="topright", collapsed=True).add_to(m)
    return m


def extract_aoi_from_map(map_data: Dict[str, Any]) -> Optional[gpd.GeoDataFrame]:
    if not map_data:
        return None
    features = None
    if map_data.get("all_drawings"):
        raw = map_data["all_drawings"]
        features = raw.get("features") if isinstance(raw, dict) else raw
    elif map_data.get("last_active_drawing"):
        features = [map_data["last_active_drawing"]]
    if not features:
        return None
    return gpd.GeoDataFrame.from_features(features, crs="EPSG:4326")


def save_aoi_geojson(aoi_gdf: gpd.GeoDataFrame, out_path: str) -> str:
    import os
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    aoi_gdf.to_file(out_path, driver="GeoJSON")
    return out_path
