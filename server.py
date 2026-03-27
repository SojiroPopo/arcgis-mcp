#!/usr/bin/env python3
"""
ArcGIS MCP Server — arcgis_mcp

An MCP server that exposes ArcGIS Pro geoprocessing capabilities via arcpy.
Designed for oil palm plantation GIS teams working with ArcGIS Pro 3.x.

Transport: stdio (runs as subprocess under arcgispro-py3 environment)

Tool categories:
  - Data I/O      : describe, list, export, create GDB
  - Geoprocessing : clip, buffer, intersect, union, dissolve, spatial join,
                    project, select, erase, repair geometry
  - Terrain       : slope, aspect, hillshade, contour, fill, flow direction,
                    flow accumulation, watershed, slope classification
  - Raster        : zonal statistics, reclassify, extract by mask,
                    raster calculator, raster/polygon conversions, resample
  - Map Layout    : create layout, export layout, list layouts, update elements

Requirements:
  - ArcGIS Pro 3.x with valid license
  - Spatial Analyst extension (for terrain/raster SA tools)
  - Python environment: arcgispro-py3
  - mcp package: pip install mcp (in arcgispro-py3)

Usage:
  Run with arcgispro-py3 Python:
    "C:/Program Files/ArcGIS/Pro/bin/Python/envs/arcgispro-py3/python.exe" server.py

  Claude Desktop config (claude_desktop_config.json):
    {
      "mcpServers": {
        "arcgis": {
          "command": "C:/Program Files/ArcGIS/Pro/bin/Python/envs/arcgispro-py3/python.exe",
          "args": ["D:/04 Claude/arcgis-mcp/server.py"]
        }
      }
    }
"""

import sys
import os

# Ensure the project root is on sys.path so relative imports work
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp.server.fastmcp import FastMCP

# Import tool registration functions
from tools import data_io, geoprocessing, terrain, raster_analysis, map_layout

# ---------------------------------------------------------------------------
# Server initialisation
# ---------------------------------------------------------------------------

mcp = FastMCP(
    name="arcgis_mcp",
    instructions=(
        "ArcGIS Pro MCP server for plantation GIS workflows. "
        "Provides geoprocessing, terrain analysis, and raster analysis tools via arcpy. "
        "IMPORTANT: All file paths must use forward slashes or double backslashes. "
        "Spatial Analyst tools require an active Spatial Analyst license. "
        "Run this server using the arcgispro-py3 Python environment."
    ),
)

# ---------------------------------------------------------------------------
# Register all tool modules
# ---------------------------------------------------------------------------

data_io.register(mcp)
geoprocessing.register(mcp)
terrain.register(mcp)
raster_analysis.register(mcp)
map_layout.register(mcp)

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Verify arcpy is importable before starting
    try:
        import arcpy
        print(f"[arcgis_mcp] arcpy loaded. ArcGIS Pro version: {arcpy.GetInstallInfo().get('Version', 'unknown')}", file=sys.stderr)
    except ImportError:
        print(
            "[arcgis_mcp] WARNING: arcpy not found. "
            "Ensure this server is run from the arcgispro-py3 environment.\n"
            "Path: C:/Program Files/ArcGIS/Pro/bin/Python/envs/arcgispro-py3/python.exe",
            file=sys.stderr,
        )

    mcp.run()
