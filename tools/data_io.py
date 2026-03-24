"""
Data I/O tools for ArcGIS MCP Server.

Provides tools for reading GIS data properties, listing workspace contents,
describing datasets, listing fields, and exporting data to common formats.
"""

import json
from typing import List, Optional

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field, field_validator

from utils.helpers import format_error, run_arcpy, success_json, tool_result, validate_path


def register(mcp: FastMCP) -> None:
    """Register all data I/O tools onto the FastMCP instance."""

    # ------------------------------------------------------------------ #
    # Input Models                                                         #
    # ------------------------------------------------------------------ #

    class DescribeDataInput(BaseModel):
        """Input model for arcgis_describe_data."""
        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

        dataset_path: str = Field(
            ...,
            description="Full path to dataset, feature class, or raster (e.g. 'D:/data/plots.shp', 'D:/data/data.gdb/parcels')",
        )

    class ListWorkspaceInput(BaseModel):
        """Input model for arcgis_list_workspace."""
        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

        workspace_path: str = Field(
            ...,
            description="Path to workspace: folder, file geodatabase (.gdb), or .gpkg file",
        )
        data_type: Optional[str] = Field(
            default="All",
            description="Filter by type: 'FeatureClass', 'RasterDataset', 'Table', 'All' (default: 'All')",
        )

    class ListFieldsInput(BaseModel):
        """Input model for arcgis_list_fields."""
        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

        dataset_path: str = Field(
            ...,
            description="Full path to the feature class or table whose fields you want to inspect",
        )

    class GetFeatureCountInput(BaseModel):
        """Input model for arcgis_get_feature_count."""
        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

        dataset_path: str = Field(
            ...,
            description="Full path to feature class or table",
        )
        where_clause: Optional[str] = Field(
            default=None,
            description="Optional SQL WHERE clause to count a subset, e.g. \"LUAS_HA > 50\"",
        )

    class ExportDataInput(BaseModel):
        """Input model for arcgis_export_data."""
        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

        input_path: str = Field(
            ...,
            description="Full path to source feature class or table",
        )
        output_path: str = Field(
            ...,
            description="Full output path including filename and extension, e.g. 'D:/output/plots.shp' or 'D:/output/output.gdb/plots'",
        )
        where_clause: Optional[str] = Field(
            default=None,
            description="Optional SQL WHERE clause to export a subset, e.g. \"DIVISI = 'ALPHA'\"",
        )

    class CreateGDBInput(BaseModel):
        """Input model for arcgis_create_gdb."""
        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

        folder_path: str = Field(
            ...,
            description="Folder where the geodatabase will be created, e.g. 'D:/output'",
        )
        gdb_name: str = Field(
            ...,
            description="Name for the geodatabase WITHOUT .gdb extension, e.g. 'perkebunan_data'",
            min_length=1,
            max_length=64,
        )

        @field_validator("gdb_name")
        @classmethod
        def validate_gdb_name(cls, v: str) -> str:
            import re
            if not re.match(r"^[A-Za-z][A-Za-z0-9_]*$", v):
                raise ValueError("GDB name must start with a letter and contain only letters, numbers, or underscores.")
            return v

    # ------------------------------------------------------------------ #
    # Tool Implementations                                                 #
    # ------------------------------------------------------------------ #

    @mcp.tool(
        name="arcgis_describe_data",
        annotations={
            "title": "Describe GIS Dataset",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def arcgis_describe_data(params: DescribeDataInput) -> str:
        """Describe properties of a GIS dataset: geometry type, CRS, extent, row count, and more.

        Works on feature classes, shapefiles, rasters, geodatabases, GeoPackages.
        Use this tool before any processing to understand the input data.

        Args:
            params (DescribeDataInput):
                - dataset_path (str): Path to the dataset

        Returns:
            str: JSON with keys:
                - name, catalogPath, dataType, datasetType
                - shapeType (for feature classes)
                - spatialReference: name, factoryCode (EPSG/WKID), units
                - extent: XMin, YMin, XMax, YMax (for spatial data)
                - featureCount (for feature classes/tables)
                - bandCount, pixelType, meanCellWidth, meanCellHeight (for rasters)
                - fields: list of {name, type, length, alias}

        Error responses:
            - "Validation error: ..." for bad inputs
            - "Error: Input dataset not found..." for missing paths
        """
        try:
            path = validate_path(params.dataset_path)

            def _describe():
                import arcpy

                desc = arcpy.Describe(path)
                result: dict = {
                    "name": desc.name,
                    "catalogPath": desc.catalogPath,
                    "dataType": desc.dataType,
                }

                # Spatial reference
                if hasattr(desc, "spatialReference") and desc.spatialReference:
                    sr = desc.spatialReference
                    result["spatialReference"] = {
                        "name": sr.name,
                        "factoryCode": sr.factoryCode,
                        "linearUnitName": getattr(sr, "linearUnitName", None),
                        "angularUnitName": getattr(sr, "angularUnitName", None),
                    }

                # Feature class properties
                if hasattr(desc, "shapeType"):
                    result["shapeType"] = desc.shapeType
                if hasattr(desc, "featureType"):
                    result["featureType"] = desc.featureType

                # Extent
                if hasattr(desc, "extent") and desc.extent:
                    ext = desc.extent
                    result["extent"] = {
                        "XMin": round(ext.XMin, 6),
                        "YMin": round(ext.YMin, 6),
                        "XMax": round(ext.XMax, 6),
                        "YMax": round(ext.YMax, 6),
                    }

                # Feature count
                if desc.dataType in ("FeatureClass", "ShapeFile", "Table"):
                    result["featureCount"] = int(arcpy.management.GetCount(path).getOutput(0))

                # Raster properties
                if desc.dataType == "RasterDataset":
                    result["bandCount"] = desc.bandCount
                    result["pixelType"] = desc.pixelType
                    result["meanCellWidth"] = desc.meanCellWidth
                    result["meanCellHeight"] = desc.meanCellHeight
                    result["format"] = desc.format

                # Fields
                if hasattr(desc, "fields"):
                    result["fields"] = [
                        {
                            "name": f.name,
                            "aliasName": f.aliasName,
                            "type": f.type,
                            "length": f.length,
                            "nullable": f.isNullable,
                        }
                        for f in desc.fields
                    ]

                return result

            data = await run_arcpy(_describe)
            return success_json(data)

        except Exception as e:
            return format_error(e)

    # ------------------------------------------------------------------ #

    @mcp.tool(
        name="arcgis_list_workspace",
        annotations={
            "title": "List Workspace Contents",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def arcgis_list_workspace(params: ListWorkspaceInput) -> str:
        """List all datasets inside a workspace (folder, file geodatabase, or GeoPackage).

        Args:
            params (ListWorkspaceInput):
                - workspace_path (str): Path to workspace
                - data_type (str): 'FeatureClass', 'RasterDataset', 'Table', or 'All'

        Returns:
            str: JSON with keys:
                - workspace: path to workspace
                - data_type: filter used
                - items: list of {name, path, dataType, shapeType, spatialRef}
                - count: total number of items
        """
        try:
            ws = validate_path(params.workspace_path)
            data_type = (params.data_type or "All").strip()

            def _list():
                import arcpy

                arcpy.env.workspace = ws
                items = []

                type_map = {
                    "FeatureClass": ["FeatureClass"],
                    "RasterDataset": ["RasterDataset"],
                    "Table": ["Table"],
                    "All": ["FeatureClass", "RasterDataset", "Table"],
                }
                types_to_list = type_map.get(data_type, ["FeatureClass", "RasterDataset", "Table"])

                for dtype in types_to_list:
                    if dtype == "FeatureClass":
                        names = arcpy.ListFeatureClasses() or []
                        for name in names:
                            full_path = f"{ws}/{name}"
                            try:
                                desc = arcpy.Describe(full_path)
                                items.append({
                                    "name": name,
                                    "path": full_path,
                                    "dataType": "FeatureClass",
                                    "shapeType": getattr(desc, "shapeType", None),
                                    "spatialRef": desc.spatialReference.name if hasattr(desc, "spatialReference") and desc.spatialReference else None,
                                })
                            except Exception:
                                items.append({"name": name, "path": full_path, "dataType": "FeatureClass"})

                    elif dtype == "RasterDataset":
                        names = arcpy.ListRasters() or []
                        for name in names:
                            full_path = f"{ws}/{name}"
                            items.append({"name": name, "path": full_path, "dataType": "RasterDataset"})

                    elif dtype == "Table":
                        names = arcpy.ListTables() or []
                        for name in names:
                            full_path = f"{ws}/{name}"
                            items.append({"name": name, "path": full_path, "dataType": "Table"})

                return items

            items = await run_arcpy(_list)
            return success_json({
                "workspace": ws,
                "data_type": data_type,
                "count": len(items),
                "items": items,
            })

        except Exception as e:
            return format_error(e)

    # ------------------------------------------------------------------ #

    @mcp.tool(
        name="arcgis_list_fields",
        annotations={
            "title": "List Feature Class Fields",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def arcgis_list_fields(params: ListFieldsInput) -> str:
        """List all fields (columns) in a feature class or table with type, length, and alias.

        Args:
            params (ListFieldsInput):
                - dataset_path (str): Path to feature class or table

        Returns:
            str: JSON with:
                - dataset: path
                - field_count: int
                - fields: list of {name, aliasName, type, length, nullable, domain, editable}

        Examples:
            - Use when: "What fields are in plots.shp?" -> dataset_path='D:/data/plots.shp'
            - Use when: "Show me the attributes of the parcels layer" -> dataset_path='...'
        """
        try:
            path = validate_path(params.dataset_path)

            def _fields():
                import arcpy
                fields = arcpy.ListFields(path)
                return [
                    {
                        "name": f.name,
                        "aliasName": f.aliasName,
                        "type": f.type,
                        "length": f.length,
                        "nullable": f.isNullable,
                        "editable": f.editable,
                        "domain": f.domain if f.domain else None,
                        "defaultValue": f.defaultValue,
                    }
                    for f in fields
                ]

            fields = await run_arcpy(_fields)
            return success_json({
                "dataset": path,
                "field_count": len(fields),
                "fields": fields,
            })

        except Exception as e:
            return format_error(e)

    # ------------------------------------------------------------------ #

    @mcp.tool(
        name="arcgis_get_feature_count",
        annotations={
            "title": "Get Feature Count",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def arcgis_get_feature_count(params: GetFeatureCountInput) -> str:
        """Count features or rows in a dataset, optionally filtered by a SQL WHERE clause.

        Args:
            params (GetFeatureCountInput):
                - dataset_path (str): Path to feature class or table
                - where_clause (Optional[str]): SQL WHERE expression, e.g. "LUAS_HA > 50"

        Returns:
            str: JSON with:
                - dataset: path
                - where_clause: applied filter (or null)
                - count: integer row/feature count
        """
        try:
            path = validate_path(params.dataset_path)
            where = params.where_clause

            def _count():
                import arcpy
                if where:
                    lyr = arcpy.management.MakeFeatureLayer(path, "tmp_lyr_count", where).getOutput(0)
                    result = int(arcpy.management.GetCount(lyr).getOutput(0))
                    arcpy.management.Delete(lyr)
                else:
                    result = int(arcpy.management.GetCount(path).getOutput(0))
                return result

            count = await run_arcpy(_count)
            return success_json({
                "dataset": path,
                "where_clause": where,
                "count": count,
            })

        except Exception as e:
            return format_error(e)

    # ------------------------------------------------------------------ #

    @mcp.tool(
        name="arcgis_export_data",
        annotations={
            "title": "Export GIS Data",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def arcgis_export_data(params: ExportDataInput) -> str:
        """Export a feature class or table to a new location/format (shapefile, GDB, GeoPackage).

        The output format is determined by the output path extension or destination:
        - .shp → Shapefile
        - .gdb/name → File Geodatabase feature class
        - .gpkg → GeoPackage (requires ArcGIS Pro 2.5+)

        Args:
            params (ExportDataInput):
                - input_path (str): Source dataset path
                - output_path (str): Destination path including filename
                - where_clause (Optional[str]): SQL filter, exports only matching features

        Returns:
            str: JSON with success status, output path, and feature count exported
        """
        try:
            in_path = validate_path(params.input_path)
            out_path = params.output_path.strip().replace("\\", "/")
            where = params.where_clause

            def _export():
                import arcpy
                if where:
                    arcpy.conversion.ExportFeatures(in_path, out_path, where_clause=where)
                else:
                    arcpy.conversion.ExportFeatures(in_path, out_path)
                count = int(arcpy.management.GetCount(out_path).getOutput(0))
                return count

            count = await run_arcpy(_export)
            return tool_result(True, f"Exported {count} features to {out_path}", {
                "input": in_path,
                "output": out_path,
                "where_clause": where,
                "exported_count": count,
            })

        except Exception as e:
            return format_error(e)

    # ------------------------------------------------------------------ #

    @mcp.tool(
        name="arcgis_create_gdb",
        annotations={
            "title": "Create File Geodatabase",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def arcgis_create_gdb(params: CreateGDBInput) -> str:
        """Create a new empty ArcGIS File Geodatabase (.gdb).

        Args:
            params (CreateGDBInput):
                - folder_path (str): Parent folder where the GDB will be created
                - gdb_name (str): Name of the GDB (without .gdb extension)

        Returns:
            str: JSON with success status and full path to the created GDB
        """
        try:
            folder = validate_path(params.folder_path)
            name = params.gdb_name

            def _create():
                import arcpy
                arcpy.management.CreateFileGDB(folder, name)
                return f"{folder}/{name}.gdb"

            gdb_path = await run_arcpy(_create)
            return tool_result(True, f"Created geodatabase: {gdb_path}", {"gdb_path": gdb_path})

        except Exception as e:
            return format_error(e)
