"""Persistent on-disk cache for DEM/NHD tiles + run manifests.

Cache layout:
  ~/.cache/rem_generator/tiles/<sha1(url)[:2]>/<sha1(url)>.tif

Manifest format (per-project run_manifest.json):
  {
    "schema": 1,
    "timestamp": "...",
    "aoi_bbox": [...],
    "resolution": 10,
    "river_name": "...",
    "dem_source": "tnm|s3|wcs|stac|custom",
    "tile_urls": [...],
    "outputs": {"rem": "...", "dem": "...", "pngs": [...]},
    "config": {...}
  }
"""
from __future__ import annotations
import hashlib
import json
import os
import shutil
import time
from pathlib import Path
from typing import Optional


def _env_cache_root() -> Path:
    override = os.environ.get("REM_CACHE_DIR")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".cache" / "rem_generator"


def tile_cache_dir() -> Path:
    root = _env_cache_root() / "tiles"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _url_key(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()


def cached_path_for(url: str) -> Path:
    key = _url_key(url)
    return tile_cache_dir() / key[:2] / f"{key}.tif"


def get_cached(url: str) -> Optional[str]:
    p = cached_path_for(url)
    if p.exists() and p.stat().st_size > 0:
        return str(p)
    return None


def store_in_cache(url: str, source_path: str) -> Optional[str]:
    """Copy a downloaded tile into the cache. Returns cached path or None on failure."""
    if not source_path or not os.path.exists(source_path):
        return None
    target = cached_path_for(url)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        if not target.exists():
            tmp = target.with_suffix(target.suffix + ".tmp")
            shutil.copy2(source_path, tmp)
            os.replace(tmp, target)
        return str(target)
    except OSError:
        return None


def link_from_cache(url: str, dest_path: str) -> bool:
    """Materialize the cached tile at dest_path (hardlink, fallback to copy).
    Returns True if dest_path now exists.
    """
    cached = get_cached(url)
    if not cached:
        return False
    try:
        if os.path.exists(dest_path):
            os.remove(dest_path)
        os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)
        try:
            os.link(cached, dest_path)
        except OSError:
            shutil.copy2(cached, dest_path)
        return os.path.exists(dest_path)
    except OSError:
        return False


def clear_cache() -> None:
    root = tile_cache_dir()
    if root.exists():
        shutil.rmtree(root)


def cache_stats() -> dict:
    root = tile_cache_dir()
    files = list(root.rglob("*.tif"))
    total_bytes = sum(f.stat().st_size for f in files if f.exists())
    return {"count": len(files), "bytes": total_bytes, "root": str(root)}


# Run Manifest

MANIFEST_NAME = "run_manifest.json"
SCHEMA_VERSION = 1


def write_manifest(project_folder: str, payload: dict) -> str:
    """Write a run manifest next to the REM outputs.

    The payload is merged with a schema version and timestamp.
    Returns the manifest path.
    """
    os.makedirs(project_folder, exist_ok=True)
    path = os.path.join(project_folder, MANIFEST_NAME)
    full = {
        "schema": SCHEMA_VERSION,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z") or time.strftime("%Y-%m-%dT%H:%M:%S"),
        **payload,
    }
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(full, f, indent=2, default=str)
    os.replace(tmp, path)
    return path


def read_manifest(project_folder: str) -> Optional[dict]:
    path = os.path.join(project_folder, MANIFEST_NAME)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
