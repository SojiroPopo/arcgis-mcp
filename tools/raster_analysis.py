"""
Raster analysis tools for ArcGIS MCP Server.

Provides zonal statistics, reclassify, extract by mask, raster calculator,
polygon-to-raster conversion, and raster-to-polygon conversion.
Requires the Spatial Analyst extension.
"""

from typing import List, Optional

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field, field_validator

from utils.helpers import format_error, run_arcpy, tool_result, validate_path


def register(mcp: FastMCP) -> None:
    """Register all raster analysis tools onto the FastMCP instance."""

    # ------------------------------------------------------------------ #
    # Input Models                                                         #
    # ------------------------------------------------------------------ #

    class ZonalStatsInput(BaseModel):
        """Input for arcgis_zonal_statistics."""
        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
        zone_features: str = Field(
            ...,
            description=(
                "Path to zone feature class or raster that defines the zones "
                "(e.g. plantation plot polygons, catchment polygons)"
            ),
        )
        zone_field: str = Field(
            ...,
            description="Field in zone_features that identifies each zone, e.g. 'PLOT_ID', 'AFDELING', 'FID'",
        )
        value_raster: str = Field(
            ...,
            description="Path to raster whose values will be summarised (e.g. slope, elevation, NDVI raster)",
        )
        output_table: str = Field(
            ...,
            description="Full output path for the statistics table (e.g. 'D:/output/slope_by_plot.dbf' or 'D:/output.gdb/slope_stats')",
        )
        statistics_type: str = Field(
            default="ALL",
            description=(
                "Statistics to compute: 'ALL', 'MEAN', 'SUM', 'MINIMUM', 'MAXIMUM', "
                "'RANGE', 'STD', 'COUNT', 'MAJORITY', 'MINORITY'. Default: 'ALL'"
            ),
        )

        @field_validator("statistics_type")
        @classmethod
        def validate_stats(cls, v: str) -> str:
            allowed = {"ALL", "MEAN", "SUM", "MINIMUM", "MAXIMUM", "RANGE", "STD", "COUNT", "MAJORITY", "MINORITY"}
            v = v.upper()
            if v not in allowed:
                raise ValueError(f"statistics_type must be one of {allowed}")
            return v

    class ZonalStatsAsTableInput(BaseModel):
        """Input for arcgis_zonal_statistics_as_table (more complete output)."""
        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
        zone_features: str = Field(..., description="Path to zone feature class or raster")
        zone_field: str = Field(..., description="Zone identifier field")
        value_raster: str = Field(..., description="Path to value raster")
        output_table: str = Field(..., description="Full output table path")
        ignore_nodata: bool = Field(default=True, description="Ignore NoData cells in statistics calculation. Default: True")
        statistics_type: str = Field(
            default="ALL",
            description="Statistics: 'ALL', 'MEAN', 'SUM', 'MINIMUM', 'MAXIMUM', 'RANGE', 'STD'. Default: 'ALL'",
        )

    class ReclassifyInput(BaseModel):
        """Input for arcgis_reclassify."""
        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
        input_raster: str = Field(..., description="Path to input raster to reclassify")
        output_path: str = Field(..., description="Full output raster path")
        reclass_field: str = Field(
            default="Value",
            description="Raster field to reclassify. Use 'Value' for standard rasters. Default: 'Value'",
        )
        remap_table: List[str] = Field(
            ...,
            description=(
                "Reclassification rules as list of strings in format 'OLD_VALUE NEW_VALUE' (for unique values) "
                "or 'FROM TO NEW_VALUE' (for ranges).\n"
                "Examples (unique): ['1 10', '2 20', '3 30']\n"
                "Examples (range): ['0 10 1', '10 25 2', '25 90 3']"
            ),
            min_length=1,
        )
        remap_type: str = Field(
            default="RANGE",
            description="Mapping type: 'RANGE' (from-to-new) or 'UNIQUE' (old-new). Default: 'RANGE'",
        )

        @field_validator("remap_type")
        @classmethod
        def validate_remap(cls, v: str) -> str:
            v = v.upper()
            if v not in {"RANGE", "UNIQUE"}:
                raise ValueError("remap_type must be 'RANGE' or 'UNIQUE'")
            return v

    class ExtractByMaskInput(BaseModel):
        """Input for arcgis_extract_by_mask."""
        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
        input_raster: str = Field(..., description="Path to input raster to extract from")
        mask_path: str = Field(
            ...,
            description="Path to mask (feature class polygon or raster) defining extraction area",
        )
        output_path: str = Field(..., description="Full output raster path")

    class RasterCalculatorInput(BaseModel):
        """Input for arcgis_raster_calculator."""
        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
        expression: str = Field(
            ...,
            description=(
                "Map algebra expression using Raster() references.\n"
                "Examples:\n"
                "  'Raster(\"D:/ndvi.tif\") * 10000'  (scale NDVI)\n"
                "  'Raster(\"D:/band4.tif\") / Raster(\"D:/band3.tif\")'  (ratio)\n"
                "  'Con(Raster(\"D:/slope.tif\") > 25, 1, 0)'  (condition: slope > 25°)\n"
                "  'Raster(\"D:/dem.tif\") - Raster(\"D:/base.tif\")'  (difference)"
            ),
            min_length=5,
        )
        output_path: str = Field(..., description="Full output raster path")

    class RasterToPolygonInput(BaseModel):
        """Input for arcgis_raster_to_polygon."""
        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
        input_raster: str = Field(..., description="Path to classified raster to convert (integer raster)")
        output_path: str = Field(..., description="Full output polygon feature class path")
        simplify: bool = Field(
            default=True,
            description="Simplify polygon boundaries to reduce vertex count. Default: True",
        )
        raster_field: str = Field(
            default="Value",
            description="Raster field to use as polygon attribute. Default: 'Value'",
        )

    class PolygonToRasterInput(BaseModel):
        """Input for arcgis_polygon_to_raster."""
        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
        input_features: str = Field(..., description="Path to input polygon feature class")
        value_field: str = Field(..., description="Field to use as raster cell values")
        output_path: str = Field(..., description="Full output raster path")
        cell_size: float = Field(
            ...,
            description="Output raster cell size in dataset units (e.g. 10.0 for 10m cells)",
            gt=0,
        )

    class ResampleRasterInput(BaseModel):
        """Input for arcgis_resample_raster."""
        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
        input_raster: str = Field(..., description="Path to input raster")
        output_path: str = Field(..., description="Full output raster path")
        cell_size: float = Field(
            ...,
            description="Target cell size in dataset units (e.g. 5.0 for 5m cells)",
            gt=0,
        )
        resampling_type: str = Field(
            default="BILINEAR",
            description="Resampling method: 'NEAREST' (categorical), 'BILINEAR' (continuous), 'CUBIC' (smooth continuous). Default: 'BILINEAR'",
        )

    # ------------------------------------------------------------------ #
    # Tool Implementations                                                 #
    # ------------------------------------------------------------------ #

    @mcp.tool(
        name="arcgis_zonal_statistics_as_table",
        annotations={
            "title": "Zonal Statistics as Table",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def arcgis_zonal_statistics_as_table(params: ZonalStatsAsTableInput) -> str:
        """Calculate statistics of a raster within zones (polygons) and save as a table.

        Most common analysis in plantation GIS:
        - Mean/max/min elevation per plot
        - % of each slope class within each planting block
        - Mean NDVI per Afdeling
        - Sum of area above slope threshold per plot

        Requires Spatial Analyst extension.

        Args:
            params (ZonalStatsAsTableInput):
                - zone_features (str): Zone polygons or raster (e.g. plot boundaries)
                - zone_field (str): Zone ID field (e.g. 'PLOT_ID', 'AFDELING')
                - value_raster (str): Raster to summarise (e.g. slope, elevation)
                - output_table (str): Output table path (.dbf or GDB table)
                - ignore_nodata (bool): Ignore NoData in stats (default: True)
                - statistics_type (str): 'ALL', 'MEAN', 'SUM', etc.

        Returns:
            str: JSON with success, output table path, row count, and field list
        """
        try:
            zones = validate_path(params.zone_features)
            raster = validate_path(params.value_raster)
            out = params.output_table.strip().replace("\\", "/")

            def _zonal():
                import arcpy
                arcpy.CheckOutExtension("Spatial")
                nodata_opt = "DATA" if params.ignore_nodata else "NODATA"
                arcpy.sa.ZonalStatisticsAsTable(
                    in_zone_data=zones,
                    zone_field=params.zone_field,
                    in_value_raster=raster,
                    out_table=out,
                    ignore_nodata=nodata_opt,
                    statistics_type=params.statistics_type,
                )
                count = int(arcpy.management.GetCount(out).getOutput(0))
                fields = [f.name for f in arcpy.ListFields(out)]
                arcpy.CheckInExtension("Spatial")
                return count, fields

            count, fields = await run_arcpy(_zonal)
            return tool_result(True, f"Zonal statistics table created: {out} ({count} zones)", {
                "zones": zones, "zone_field": params.zone_field,
                "value_raster": raster, "output": out,
                "row_count": count, "output_fields": fields,
                "statistics_type": params.statistics_type,
            })
        except Exception as e:
            return format_error(e)

    # ------------------------------------------------------------------ #

    @mcp.tool(
        name="arcgis_reclassify",
        annotations={
            "title": "Reclassify Raster Values",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def arcgis_reclassify(params: ReclassifyInput) -> str:
        """Reclassify raster values into new categories using a remap table.

        Common uses:
        - Convert continuous slope to slope classes
        - Reclassify soil suitability scores
        - Simplify land-use codes
        - Create binary masks (e.g. 1=suitable, 0=unsuitable)

        Requires Spatial Analyst extension.

        Args:
            params (ReclassifyInput):
                - input_raster (str): Input raster
                - output_path (str): Output raster
                - reclass_field (str): Field to reclassify (default: 'Value')
                - remap_table (List[str]): Rules as ['FROM TO NEW', ...] or ['OLD NEW', ...]
                - remap_type (str): 'RANGE' or 'UNIQUE' (default: 'RANGE')

        Returns:
            str: JSON with success, output path

        Examples:
            Range remap: remap_table=['0 8 1', '8 15 2', '15 25 3', '25 90 4']
            Unique remap: remap_table=['1 10', '2 20', '3 30']
        """
        try:
            in_raster = validate_path(params.input_raster)
            out = params.output_path.strip().replace("\\", "/")

            def _reclass():
                import arcpy
                from arcpy.sa import Reclassify, RemapRange, RemapValue
                arcpy.CheckOutExtension("Spatial")

                if params.remap_type == "RANGE":
                    ranges = []
                    for row in params.remap_table:
                        parts = row.strip().split()
                        if len(parts) == 3:
                            ranges.append([float(parts[0]), float(parts[1]), int(parts[2])])
                    remap = RemapRange(ranges)
                else:
                    pairs = []
                    for row in params.remap_table:
                        parts = row.strip().split()
                        if len(parts) == 2:
                            pairs.append([float(parts[0]), int(parts[1])])
                    remap = RemapValue(pairs)

                result = Reclassify(in_raster, params.reclass_field, remap, "NODATA")
                result.save(out)
                arcpy.CheckInExtension("Spatial")

            await run_arcpy(_reclass)
            return tool_result(True, f"Reclassified raster saved: {out}", {
                "input": in_raster, "output": out,
                "reclass_field": params.reclass_field,
                "remap_type": params.remap_type,
                "remap_rules": params.remap_table,
            })
        except Exception as e:
            return format_error(e)

    # ------------------------------------------------------------------ #

    @mcp.tool(
        name="arcgis_extract_by_mask",
        annotations={
            "title": "Extract Raster by Mask",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def arcgis_extract_by_mask(params: ExtractByMaskInput) -> str:
        """Extract raster cells that fall within a mask area (polygon or raster).

        Common uses:
        - Clip a DEM to the plantation boundary
        - Extract slope raster to individual Afdeling polygons
        - Mask out non-plantation areas from analysis rasters

        Requires Spatial Analyst extension.

        Args:
            params (ExtractByMaskInput):
                - input_raster (str): Raster to extract from
                - mask_path (str): Mask polygon or raster (cells outside = NoData)
                - output_path (str): Output extracted raster

        Returns:
            str: JSON with success and output path
        """
        try:
            in_raster = validate_path(params.input_raster)
            mask = validate_path(params.mask_path)
            out = params.output_path.strip().replace("\\", "/")

            def _extract():
                import arcpy
                from arcpy.sa import ExtractByMask
                arcpy.CheckOutExtension("Spatial")
                result = ExtractByMask(in_raster, mask)
                result.save(out)
                arcpy.CheckInExtension("Spatial")

            await run_arcpy(_extract)
            return tool_result(True, f"Extracted raster saved: {out}", {
                "input_raster": in_raster, "mask": mask, "output": out,
            })
        except Exception as e:
            return format_error(e)

    # ------------------------------------------------------------------ #

    @mcp.tool(
        name="arcgis_raster_calculator",
        annotations={
            "title": "Raster Calculator (Map Algebra)",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def arcgis_raster_calculator(params: RasterCalculatorInput) -> str:
        """Execute a map algebra expression on one or more rasters.

        Use for: NDVI calculation, difference maps, suitability scoring,
        conditional masking, raster arithmetic.
        Requires Spatial Analyst extension.

        Args:
            params (RasterCalculatorInput):
                - expression (str): Map algebra Python expression using Raster() and arcpy.sa functions
                - output_path (str): Output raster path

        Returns:
            str: JSON with success, output path

        Expression examples:
            NDVI: '(Raster("nir.tif") - Raster("red.tif")) / (Raster("nir.tif") + Raster("red.tif"))'
            Slope mask: 'Con(Raster("slope.tif") > 25, 1, 0)'
            Elevation diff: 'Raster("dem_2024.tif") - Raster("dem_2020.tif")'
            Scale NDVI: 'Raster("ndvi.tif") * 10000'
        """
        try:
            out = params.output_path.strip().replace("\\", "/")
            expr = params.expression

            def _calc():
                import arcpy
                from arcpy.sa import Con, Raster  # noqa: F401 — needed for eval
                arcpy.CheckOutExtension("Spatial")
                result = eval(expr)  # noqa: S307 — intentional map algebra eval
                result.save(out)
                arcpy.CheckInExtension("Spatial")

            await run_arcpy(_calc)
            return tool_result(True, f"Raster calculation saved: {out}", {
                "expression": expr, "output": out,
            })
        except Exception as e:
            return format_error(e)

    # ------------------------------------------------------------------ #

    @mcp.tool(
        name="arcgis_raster_to_polygon",
        annotations={
            "title": "Convert Raster to Polygon",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def arcgis_raster_to_polygon(params: RasterToPolygonInput) -> str:
        """Convert a classified integer raster to polygon feature class.

        Common uses:
        - Convert slope class raster to polygon for area calculations
        - Vectorise land-use raster for overlay analysis
        - Convert watershed raster to polygon boundaries

        Args:
            params (RasterToPolygonInput):
                - input_raster (str): Integer raster to convert
                - output_path (str): Output polygon feature class
                - simplify (bool): Simplify boundaries (default: True)
                - raster_field (str): Field to attribute polygons (default: 'Value')

        Returns:
            str: JSON with success, output path, polygon count
        """
        try:
            in_raster = validate_path(params.input_raster)
            out = params.output_path.strip().replace("\\", "/")
            simplify = "SIMPLIFY" if params.simplify else "NO_SIMPLIFY"

            def _to_poly():
                import arcpy
                arcpy.conversion.RasterToPolygon(in_raster, out, simplify, params.raster_field)
                count = int(arcpy.management.GetCount(out).getOutput(0))
                return count

            count = await run_arcpy(_to_poly)
            return tool_result(True, f"Raster converted to {count} polygons: {out}", {
                "input_raster": in_raster, "output": out,
                "simplify": params.simplify, "polygon_count": count,
            })
        except Exception as e:
            return format_error(e)

    # ------------------------------------------------------------------ #

    @mcp.tool(
        name="arcgis_polygon_to_raster",
        annotations={
            "title": "Convert Polygon to Raster",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def arcgis_polygon_to_raster(params: PolygonToRasterInput) -> str:
        """Convert a polygon feature class to a raster dataset.

        Common uses:
        - Rasterise plot boundaries for zonal analysis
        - Convert soil type polygons to raster for modelling
        - Create zone rasters from management unit polygons

        Args:
            params (PolygonToRasterInput):
                - input_features (str): Polygon feature class
                - value_field (str): Attribute field to burn as raster values
                - output_path (str): Output raster path
                - cell_size (float): Raster resolution in dataset units

        Returns:
            str: JSON with success and output path
        """
        try:
            in_fc = validate_path(params.input_features)
            out = params.output_path.strip().replace("\\", "/")

            def _to_raster():
                import arcpy
                arcpy.conversion.PolygonToRaster(
                    in_features=in_fc,
                    value_field=params.value_field,
                    out_rasterdataset=out,
                    cell_assignment="CELL_CENTER",
                    priority_field="NONE",
                    cellsize=params.cell_size,
                )

            await run_arcpy(_to_raster)
            return tool_result(True, f"Polygon rasterised: {out}", {
                "input": in_fc, "output": out,
                "value_field": params.value_field,
                "cell_size": params.cell_size,
            })
        except Exception as e:
            return format_error(e)

    # ------------------------------------------------------------------ #

    @mcp.tool(
        name="arcgis_resample_raster",
        annotations={
            "title": "Resample Raster Resolution",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def arcgis_resample_raster(params: ResampleRasterInput) -> str:
        """Change raster cell size (resolution) by resampling.

        Use when:
        - Aligning multiple rasters to the same resolution for overlay
        - Downscaling high-res DEMs for faster processing
        - Upscaling coarse data to finer resolution

        Args:
            params (ResampleRasterInput):
                - input_raster (str): Input raster
                - output_path (str): Output resampled raster
                - cell_size (float): Target cell size in dataset units
                - resampling_type (str): 'NEAREST', 'BILINEAR', or 'CUBIC'
                  - NEAREST: for categorical data (land use, slope class)
                  - BILINEAR: for continuous data (elevation, slope degrees)
                  - CUBIC: for smooth continuous surfaces

        Returns:
            str: JSON with success and output path
        """
        try:
            in_raster = validate_path(params.input_raster)
            out = params.output_path.strip().replace("\\", "/")

            def _resample():
                import arcpy
                arcpy.management.Resample(
                    in_raster=in_raster,
                    out_raster=out,
                    cell_size=params.cell_size,
                    resampling_type=params.resampling_type,
                )

            await run_arcpy(_resample)
            return tool_result(True, f"Resampled to {params.cell_size} units: {out}", {
                "input": in_raster, "output": out,
                "cell_size": params.cell_size,
                "resampling_type": params.resampling_type,
            })
        except Exception as e:
            return format_error(e)
