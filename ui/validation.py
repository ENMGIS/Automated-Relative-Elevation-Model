"""File validation helpers for DEM + river vector inputs.

Pure, no Streamlit dependency — callable from either the UI or from CLI/tests.
"""
from __future__ import annotations
import os
from typing import Any, Dict
import numpy as np
import geopandas as gpd
import rasterio

import rem_utils as utils


def path_exists(p: str) -> bool:
    return bool(p) and os.path.exists(os.path.expanduser(p))


def validate_dem_file(dem_path: str) -> Dict[str, Any]:
    """Return {'valid': bool, 'error': str|None, 'info': dict}."""
    result: Dict[str, Any] = {"valid": False, "error": None, "info": {}}

    try:
        dem_path = os.path.expanduser(dem_path)

        if not os.path.exists(dem_path):
            result["error"] = f"DEM file not found: {dem_path}"
            return result
        if not os.access(dem_path, os.R_OK):
            result["error"] = f"DEM file not readable (permission denied): {dem_path}"
            return result

        try:
            with rasterio.open(dem_path) as src:
                if src.crs is None:
                    result["error"] = "DEM has no coordinate reference system (CRS)."
                    return result
                if src.width <= 0 or src.height <= 0:
                    result["error"] = f"DEM has invalid dimensions: {src.width} x {src.height}"
                    return result

                try:
                    sample = src.read(
                        1,
                        window=(
                            (src.height // 2, src.height // 2 + 10),
                            (src.width // 2, src.width // 2 + 10),
                        ),
                    )
                    if src.nodata is not None:
                        valid_data = sample[sample != src.nodata]
                    else:
                        valid_data = sample.flatten()
                    valid_data = valid_data[np.isfinite(valid_data)]
                    if valid_data.size == 0:
                        result["error"] = (
                            "DEM appears to contain only NoData in sampled area. "
                            "File may be empty or corrupted."
                        )
                        return result
                except Exception as e:
                    result["error"] = f"Could not read DEM data: {e}"
                    return result

                bounds = src.bounds
                res_x, res_y = src.res
                is_geographic = utils.is_geographic_crs(src.crs)

                result["valid"] = True
                result["info"] = {
                    "width": src.width,
                    "height": src.height,
                    "resolution": (abs(res_x), abs(res_y)),
                    "crs": str(src.crs),
                    "crs_type": "Geographic (degrees)" if is_geographic else "Projected (meters)",
                    "is_geographic": is_geographic,
                    "bounds": {
                        "west": bounds.left,
                        "south": bounds.bottom,
                        "east": bounds.right,
                        "north": bounds.top,
                    },
                    "nodata": src.nodata,
                    "dtype": str(src.dtypes[0]),
                    "file_size_mb": os.path.getsize(dem_path) / (1024 * 1024),
                }
        except rasterio.errors.RasterioIOError as e:
            result["error"] = f"Not a valid raster file or unsupported format: {e}"
            return result

    except Exception as e:
        result["error"] = f"Unexpected error validating DEM: {e}"
        return result

    return result


def validate_river_file(river_path: str) -> Dict[str, Any]:
    result: Dict[str, Any] = {"valid": False, "error": None, "info": {}}

    try:
        river_path = os.path.expanduser(river_path)

        if not os.path.exists(river_path):
            result["error"] = f"River file not found: {river_path}"
            return result
        if not os.access(river_path, os.R_OK):
            result["error"] = f"River file not readable (permission denied): {river_path}"
            return result

        if river_path.lower().endswith(".shp"):
            base = river_path[:-4]
            missing = [base + ext for ext in (".shx", ".dbf") if not os.path.exists(base + ext)]
            if missing:
                result["error"] = f"Shapefile missing required companion files: {', '.join(missing)}"
                return result

        try:
            gdf = gpd.read_file(river_path)
            if len(gdf) == 0:
                result["error"] = "River file contains no features (empty dataset)"
                return result
            if gdf.crs is None:
                result["error"] = "River file has no coordinate reference system (CRS)."
                return result

            geom_types = gdf.geometry.geom_type.unique()
            if "LineString" not in geom_types and "MultiLineString" not in geom_types:
                result["error"] = (
                    "River file must contain LineString or MultiLineString geometries. "
                    f"Found: {', '.join(geom_types)}"
                )
                return result

            null_count = int(gdf.geometry.isna().sum())
            if null_count == len(gdf):
                result["error"] = "All features have null/invalid geometries"
                return result

            bounds = gdf.total_bounds
            result["valid"] = True
            result["info"] = {
                "feature_count": len(gdf),
                "crs": str(gdf.crs),
                "bounds": {
                    "west": float(bounds[0]),
                    "south": float(bounds[1]),
                    "east": float(bounds[2]),
                    "north": float(bounds[3]),
                },
                "geometry_types": ", ".join(geom_types),
                "null_geometries": null_count,
                "columns": list(gdf.columns),
                "file_size_mb": os.path.getsize(river_path) / (1024 * 1024),
            }
        except Exception as e:
            result["error"] = f"Not a valid vector file or unsupported format: {e}"
            return result

    except Exception as e:
        result["error"] = f"Unexpected error validating river: {e}"
        return result

    return result
