"""Shared REM pipeline — consumed by both the Streamlit UI (app.py) and the
guided CLI (run_rem_guided.py).

Each stage is an independent function so the UI can insert gates (QA, stop
button, memory check) between them. The CLI calls them in sequence.
"""
from __future__ import annotations
import os
import time
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any

import geopandas as gpd
import rasterio

import rem_config as cfg
import rem_utils as utils
import data_collections as dc
import hillshade as hillshade_module
import REM_Calcs as rem_calcs_module
import rem_hillshade_colorramp as style_rem_module
import rem_cache


@dataclass
class RemPipelineConfig:
    """Everything a run needs. Construct once and thread through the stages."""

    project_folder: str
    aoi_geojson_path: Optional[str] = None
    # One of: "nhd" (AOI+NHD download) or "user_upload"
    data_source: str = "nhd"
    resolution: int = 10

    # User inputs
    dem_file: Optional[str] = None
    river_vector_path: Optional[str] = None
    river_name: Optional[str] = None

    # REM parameters
    spacing: int = 20
    engine: str = "hand"                # hand | projection | idw
    k_neighbors: int = 8
    max_value: Optional[float] = None   # comp max
    tile_size: int = 1024

    # Styling
    selected_ramps: List[str] = field(default_factory=list)
    bg_type: str = "hillshade"          # hillshade | aerial | white
    bg_alpha: float = 0.5
    rem_alpha: float = 1.0
    viz_max_m: Optional[float] = None
    use_discrete_colors: bool = False

    # Threads
    download_threads: int = 4
    compute_threads: int = 4

    # Observability
    tile_urls_used: List[str] = field(default_factory=list)

    def to_manifest(self) -> Dict[str, Any]:
        """Serialisable version for write_run_manifest()."""
        d = asdict(self)
        return d


# Stage 1: DEM acquisition

def acquire_dem(config: RemPipelineConfig) -> str:
    """Download + mosaic (or validate existing) DEM. Returns final DEM path."""
    if config.data_source == "user_upload":
        dem_file = config.dem_file
        if not dem_file or not os.path.exists(dem_file):
            raise FileNotFoundError(f"DEM not found: {dem_file}")

        # CRS sanity: reproject geographic DEMs to UTM meters.
        with rasterio.open(dem_file) as src:
            if utils.is_geographic_crs(src.crs):
                out = os.path.join(config.project_folder, "DEM_reprojected_UTM.tif")
                dem_file, _ = utils.reproject_dem_to_utm(dem_file, out, verbose=True)
        return dem_file

    # NHD + 3DEP download path
    if not config.aoi_geojson_path:
        raise ValueError("aoi_geojson_path required for NHD download path")

    mosaic = dc.download_and_mosaic_dems(
        [config.aoi_geojson_path],
        config.project_folder,
        config.resolution,
        n_jobs_download=config.download_threads,
        n_jobs_mosaic=config.compute_threads,
    )
    if not mosaic:
        raise RuntimeError(f"DEM download failed for resolution {config.resolution}m")

    if cfg.CLIP_DEM:
        clip_out = os.path.join(config.project_folder, "mosaic_clipped.tif")
        try:
            clipped = utils.clip_dem_to_aoi(mosaic, config.aoi_geojson_path, clip_out)
            if clipped and os.path.exists(clipped):
                mosaic = clipped
        except Exception:
            pass
    return mosaic


# Stage 2: River acquisition

def acquire_river(config: RemPipelineConfig, dem_file: str) -> str:
    """Fetch NHD river or use provided path. Returns reprojected-to-DEM path."""
    if config.data_source == "user_upload":
        if not config.river_vector_path or not os.path.exists(config.river_vector_path):
            raise FileNotFoundError(f"River not found: {config.river_vector_path}")
        river_raw = config.river_vector_path
    else:
        if not config.aoi_geojson_path:
            raise ValueError("aoi_geojson_path required for NHD download path")
        river_raw = dc.choose_and_save_nhd_river(
            [config.aoi_geojson_path], config.project_folder,
            river_choice=1, river_name=config.river_name,
        )
        if not river_raw:
            raise RuntimeError("No river found in the selected AOI")

    out = os.path.join(config.project_folder, "river_reprojected.gpkg")
    utils.reproject_vector_to_match_dem(river_raw, dem_file, out)
    return out


# Stage 3: Hillshade (used for QA and optionally as viz background)

def make_hillshade(config: RemPipelineConfig, dem_file: str) -> str:
    out = os.path.join(config.project_folder, "hillshade.tif")
    hillshade_module.create_hillshade_fast_qa(dem_file, out, downsample_factor=1, z_factor=5.5)
    return out


# Stage 4: REM calculation

def compute_rem(config: RemPipelineConfig, dem_file: str, river_path: str) -> str:
    out = os.path.join(config.project_folder, "REM.tif")
    dem_folder = os.path.dirname(dem_file) or config.project_folder

    rem_args = dict(
        dem_folder=dem_folder,
        river_shp=river_path,
        output_rem_path=out,
        spacing=int(config.spacing),
        tile_size=int(config.tile_size),
        k_neighbors=int(config.k_neighbors),
        max_value=config.max_value,
        threads=int(config.compute_threads),
        idw_power=None,
        engine=config.engine,
        data_source=config.data_source,
    )

    with utils.limit_threadpools(config.compute_threads):
        utils._call_rem_main_with_filtered_kwargs(rem_calcs_module, **rem_args)

    if cfg.CLIP_DEM and config.aoi_geojson_path and os.path.exists(config.aoi_geojson_path):
        clipped = os.path.join(config.project_folder, "REM_clipped.tif")
        try:
            clipped_path = utils.clip_dem_to_aoi(out, config.aoi_geojson_path, clipped)
            if clipped_path and os.path.exists(clipped_path):
                out = clipped_path
        except Exception:
            pass
    return out


# Stage 5: Run manifest

def write_manifest(config: RemPipelineConfig, dem_file: str, rem_file: str, pngs: List[str]) -> str:
    payload = {
        "aoi_bbox": _aoi_bbox(config.aoi_geojson_path) if config.aoi_geojson_path else None,
        "config": config.to_manifest(),
        "outputs": {
            "dem": dem_file,
            "rem": rem_file,
            "pngs": pngs,
        },
        "cache_stats": rem_cache.cache_stats(),
    }
    return rem_cache.write_manifest(config.project_folder, payload)


def _aoi_bbox(path: Optional[str]) -> Optional[List[float]]:
    if not path or not os.path.exists(path):
        return None
    try:
        gdf = gpd.read_file(path)
        return [float(x) for x in gdf.total_bounds]
    except Exception:
        return None
