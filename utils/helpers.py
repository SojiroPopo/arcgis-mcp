"""
Shared utility functions for ArcGIS MCP Server.

Provides error handling, path validation, arcpy executor wrapper,
and common response formatting used across all tool modules.
"""

import asyncio
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional

# Thread pool for running blocking arcpy calls
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="arcpy_worker")

# Supported GIS file extensions
VECTOR_EXTENSIONS = {".shp", ".gpkg", ".gdb", ".geojson", ".kml", ".kmz"}
RASTER_EXTENSIONS = {".tif", ".tiff", ".img", ".jpg", ".png", ".asc", ".nc"}


def check_arcpy_available() -> bool:
    """Return True if arcpy can be imported."""
    try:
        import arcpy  # noqa: F401
        return True
    except ImportError:
        return False


async def run_arcpy(func: Callable, *args, **kwargs) -> Any:
    """
    Run a blocking arcpy function in the thread pool executor.

    Wraps synchronous arcpy calls so they don't block the async event loop.

    Args:
        func: Callable arcpy function or lambda
        *args: Positional arguments to pass to func
        **kwargs: Keyword arguments to pass to func

    Returns:
        Whatever func returns

    Raises:
        Exception: Re-raises any exception from the arcpy call
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_executor, lambda: func(*args, **kwargs))


def validate_path(path: str, must_exist: bool = True) -> str:
    """
    Validate and normalise a file/workspace path.

    Args:
        path: Raw path string
        must_exist: If True, raise ValueError when the path doesn't exist

    Returns:
        Normalised absolute path

    Raises:
        ValueError: If path is empty or doesn't exist when must_exist=True
    """
    if not path or not path.strip():
        raise ValueError("Path cannot be empty.")
    path = path.strip().replace("\\", "/")
    if must_exist and not os.path.exists(path):
        raise ValueError(f"Path does not exist: {path}")
    return path


def sanitize_field_name(name: str) -> str:
    """
    Sanitise a string to be a valid ArcGIS field name.

    Replaces illegal characters with underscores and ensures the name
    starts with a letter.
    """
    name = re.sub(r"[^A-Za-z0-9_]", "_", name)
    if name and name[0].isdigit():
        name = "f_" + name
    return name[:64]  # ArcGIS field name limit


def format_error(e: Exception) -> str:
    """
    Return a concise, actionable error string.

    Args:
        e: Any exception

    Returns:
        Human-readable error message string
    """
    msg = str(e)

    # arcpy-specific error codes
    if "000732" in msg:
        return f"Error: Input dataset not found or inaccessible. Check the path and ensure the file exists. Detail: {msg}"
    if "000210" in msg:
        return f"Error: Cannot create output — check that the output path is writable and the workspace exists. Detail: {msg}"
    if "000258" in msg:
        return f"Error: Output already exists. Delete it first or choose a different output path. Detail: {msg}"
    if "000816" in msg:
        return f"Error: No spatial reference defined. Project the data first using arcgis_project. Detail: {msg}"
    if "ERROR 999999" in msg or "999999" in msg:
        return f"Error: ArcGIS general geoprocessing error. Check input paths, spatial references, and data integrity. Detail: {msg}"
    if "ExecuteError" in type(e).__name__:
        return f"ArcGIS geoprocessing error: {msg}"
    if isinstance(e, ValueError):
        return f"Validation error: {msg}"
    if isinstance(e, FileNotFoundError):
        return f"File not found: {msg}"
    return f"Unexpected error ({type(e).__name__}): {msg}"


def success_json(data: Dict[str, Any]) -> str:
    """Serialise a dict to a pretty JSON string."""
    return json.dumps(data, indent=2, ensure_ascii=False, default=str)


def tool_result(
    success: bool,
    message: str,
    data: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Build a standardised tool response string.

    Args:
        success: Whether the operation succeeded
        message: Human-readable summary
        data: Optional additional structured data

    Returns:
        JSON-formatted string
    """
    payload: Dict[str, Any] = {"success": success, "message": message}
    if data:
        payload.update(data)
    return success_json(payload)


def arcpy_exists(path: str) -> bool:
    """Return True if arcpy.Exists(path) is True (needs arcpy context)."""
    try:
        import arcpy
        return arcpy.Exists(path)
    except Exception:
        return os.path.exists(path)


def get_arcpy_messages() -> List[str]:
    """Return the last arcpy geoprocessing messages as a list of strings."""
    try:
        import arcpy
        return [arcpy.GetMessages()]
    except Exception:
        return []
