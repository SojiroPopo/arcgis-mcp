"""
Terrain analysis tools for ArcGIS MCP Server.

Provides DEM-based surface analysis: slope, aspect, hillshade, contour,
fill sinks, flow direction, flow accumulation, and watershed delineation.
Requires the Spatial Analyst extension.
"""

from typing import Optional

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field, field_validator

from utils.helpers import format_error, run_arcpy, tool_result, validate_path


def register(mcp: FastMCP) -> None:
    """Register all terrain analysis tools onto the FastMCP instance."""

    # ------------------------------------------------------------------ #
    # Input Models                                                         #
    # ------------------------------------------------------------------ #

    class SlopeInput(BaseModel):
        """Input for arcgis_slope."""
        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
        dem_path: str = Field(..., description="Path to input DEM (Digital Elevation Model) raster")
        output_path: str = Field(..., description="Full output raster path (e.g. 'D:/output/slope.tif')")
        output_measurement: str = Field(
            default="DEGREE",
            description="Output units: 'DEGREE' (0-90 degrees) or 'PERCENT_RISE' (percent slope). Default: 'DEGREE'",
        )
        z_factor: float = Field(
            default=1.0,
            description="Z-unit conversion factor. Use 1.0 when XY and Z units are the same (e.g. both meters). Use 0.00001 to convert Z from degrees to meters. Default: 1.0",
            gt=0,
        )

        @field_validator("output_measurement")
        @classmethod
        def validate_measurement(cls, v: str) -> str:
            allowed = {"DEGREE", "PERCENT_RISE"}
            v = v.upper()
            if v not in allowed:
                raise ValueError(f"output_measurement must be one of {allowed}")
            return v

    class AspectInput(BaseModel):
        """Input for arcgis_aspect."""
        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
        dem_path: str = Field(..., description="Path to input DEM raster")
        output_path: str = Field(..., description="Full output raster path")

    class HillshadeInput(BaseModel):
        """Input for arcgis_hillshade."""
        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
        dem_path: str = Field(..., description="Path to input DEM raster")
        output_path: str = Field(..., description="Full output raster path")
        azimuth: float = Field(
            default=315.0,
            description="Sun azimuth angle in degrees (0-360, measured clockwise from north). Default: 315 (northwest)",
            ge=0.0,
            le=360.0,
        )
        altitude: float = Field(
            default=45.0,
            description="Sun altitude angle above horizon in degrees (0-90). Default: 45",
            ge=0.0,
            le=90.0,
        )
        z_factor: float = Field(default=1.0, description="Z-unit conversion factor. Default: 1.0", gt=0)

    class ContourInput(BaseModel):
        """Input for arcgis_contour."""
        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
        dem_path: str = Field(..., description="Path to input DEM raster")
        output_path: str = Field(..., description="Full output contour feature class path")
        contour_interval: float = Field(
            ...,
            description="Vertical interval between contour lines in DEM Z-units (e.g. 5 for 5-meter contours)",
            gt=0,
        )
        base_contour: float = Field(
            default=0.0,
            description="Starting elevation value for contours. Default: 0.0",
        )

    class FillInput(BaseModel):
        """Input for arcgis_fill (hydrology - fill sinks)."""
        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
        dem_path: str = Field(..., description="Path to input DEM raster (should be hydrologically conditioned)")
        output_path: str = Field(..., description="Full output filled DEM raster path")
        z_limit: Optional[float] = Field(
            default=None,
            description="Maximum fill depth to remove. Leave None to fill all sinks. Use to avoid over-filling large basins.",
        )

    class FlowDirectionInput(BaseModel):
        """Input for arcgis_flow_direction."""
        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
        filled_dem_path: str = Field(..., description="Path to filled (sink-free) DEM raster. Run arcgis_fill first.")
        output_path: str = Field(..., description="Full output flow direction raster path")
        flow_direction_type: str = Field(
            default="D8",
            description="Flow model: 'D8' (8-direction, standard) or 'MFD' (multiple flow direction). Default: 'D8'",
        )

    class FlowAccumulationInput(BaseModel):
        """Input for arcgis_flow_accumulation."""
        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
        flow_direction_path: str = Field(..., description="Path to flow direction raster (output of arcgis_flow_direction)")
        output_path: str = Field(..., description="Full output flow accumulation raster path")
        data_type: str = Field(
            default="FLOAT",
            description="Output raster data type: 'INTEGER' or 'FLOAT'. Default: 'FLOAT'",
        )

    class WatershedInput(BaseModel):
        """Input for arcgis_watershed."""
        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
        flow_direction_path: str = Field(..., description="Path to flow direction raster")
        pour_points_path: str = Field(..., description="Path to pour points feature class or raster (outlet locations)")
        output_path: str = Field(..., description="Full output watershed raster path")
        pour_point_field: Optional[str] = Field(
            default=None,
            description="Field in pour_points to use as zone value. Leave None to use object ID.",
        )

    class SlopeclassInput(BaseModel):
        """Input for arcgis_slope_classification."""
        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
        dem_path: str = Field(..., description="Path to input DEM raster")
        output_path: str = Field(..., description="Full output classified slope raster path")
        classification_scheme: str = Field(
            default="PLANTATION",
            description=(
                "Classification scheme:\n"
                "'PLANTATION' - Classes optimised for oil palm (0-8°, 8-15°, 15-25°, >25°)\n"
                "'STANDARD' - Standard geomorphology classes (0-5°, 5-15°, 15-30°, 30-45°, >45°)"
            ),
        )

    # ------------------------------------------------------------------ #
    # Tool Implementations                                                 #
    # ------------------------------------------------------------------ #

    @mcp.tool(
        name="arcgis_slope",
        annotations={
            "title": "Calculate Slope from DEM",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def arcgis_slope(params: SlopeInput) -> str:
        """Calculate slope (steepness) from a DEM raster.

        Requires Spatial Analyst extension.
        Essential for plantation planning: identifies areas unsuitable for
        mechanised harvesting (>25°) and risk of erosion.

        Args:
            params (SlopeInput):
                - dem_path (str): Input DEM path
                - output_path (str): Output slope raster path
                - output_measurement (str): 'DEGREE' or 'PERCENT_RISE' (default: 'DEGREE')
                - z_factor (float): Z conversion factor (default: 1.0)

        Returns:
            str: JSON with success, output path, and raster statistics (min, max, mean slope)
        """
        try:
            dem = validate_path(params.dem_path)
            out = params.output_path.strip().replace("\\", "/")

            def _slope():
                import arcpy
                from arcpy.sa import Slope
                arcpy.CheckOutExtension("Spatial")
                result = Slope(dem, params.output_measurement, params.z_factor)
                result.save(out)
                stats = arcpy.management.GetRasterProperties(out, "MINIMUM").getOutput(0)
                min_v = float(arcpy.management.GetRasterProperties(out, "MINIMUM").getOutput(0))
                max_v = float(arcpy.management.GetRasterProperties(out, "MAXIMUM").getOutput(0))
                mean_v = float(arcpy.management.GetRasterProperties(out, "MEAN").getOutput(0))
                arcpy.CheckInExtension("Spatial")
                return {"min": round(min_v, 2), "max": round(max_v, 2), "mean": round(mean_v, 2)}

            stats = await run_arcpy(_slope)
            return tool_result(True, f"Slope raster created: {out}", {
                "dem_input": dem, "output": out,
                "measurement": params.output_measurement,
                "statistics": stats,
            })
        except Exception as e:
            return format_error(e)

    # ------------------------------------------------------------------ #

    @mcp.tool(
        name="arcgis_aspect",
        annotations={
            "title": "Calculate Aspect from DEM",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def arcgis_aspect(params: AspectInput) -> str:
        """Calculate aspect (compass direction of slope face) from a DEM.

        Output values: -1=flat, 0-360=degrees clockwise from north.
        Useful for solar radiation analysis and microclimate mapping.
        Requires Spatial Analyst extension.

        Args:
            params (AspectInput):
                - dem_path (str): Input DEM path
                - output_path (str): Output aspect raster path

        Returns:
            str: JSON with success and output path
        """
        try:
            dem = validate_path(params.dem_path)
            out = params.output_path.strip().replace("\\", "/")

            def _aspect():
                import arcpy
                from arcpy.sa import Aspect
                arcpy.CheckOutExtension("Spatial")
                result = Aspect(dem)
                result.save(out)
                arcpy.CheckInExtension("Spatial")

            await run_arcpy(_aspect)
            return tool_result(True, f"Aspect raster created: {out}", {
                "dem_input": dem, "output": out,
                "note": "Values: -1=flat, 0=North, 90=East, 180=South, 270=West",
            })
        except Exception as e:
            return format_error(e)

    # ------------------------------------------------------------------ #

    @mcp.tool(
        name="arcgis_hillshade",
        annotations={
            "title": "Generate Hillshade from DEM",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def arcgis_hillshade(params: HillshadeInput) -> str:
        """Generate a hillshade (shaded relief) raster for map visualisation.

        Creates a grayscale relief image simulating illumination from a light source.
        Use as a base layer in maps to show terrain relief.
        Requires Spatial Analyst extension.

        Args:
            params (HillshadeInput):
                - dem_path (str): Input DEM path
                - output_path (str): Output hillshade raster path
                - azimuth (float): Sun direction 0-360° clockwise from north (default: 315)
                - altitude (float): Sun elevation above horizon 0-90° (default: 45)
                - z_factor (float): Z conversion factor (default: 1.0)

        Returns:
            str: JSON with success and output path
        """
        try:
            dem = validate_path(params.dem_path)
            out = params.output_path.strip().replace("\\", "/")

            def _hillshade():
                import arcpy
                from arcpy.sa import Hillshade
                arcpy.CheckOutExtension("Spatial")
                result = Hillshade(dem, params.azimuth, params.altitude, "NO_SHADOWS", params.z_factor)
                result.save(out)
                arcpy.CheckInExtension("Spatial")

            await run_arcpy(_hillshade)
            return tool_result(True, f"Hillshade created: {out}", {
                "dem_input": dem, "output": out,
                "azimuth": params.azimuth, "altitude": params.altitude,
            })
        except Exception as e:
            return format_error(e)

    # ------------------------------------------------------------------ #

    @mcp.tool(
        name="arcgis_contour",
        annotations={
            "title": "Generate Contour Lines from DEM",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def arcgis_contour(params: ContourInput) -> str:
        """Generate contour (isoline) lines from a DEM raster.

        Requires Spatial Analyst extension.
        Common intervals: 1m for flat areas, 5m for hilly terrain, 10m for mountains.

        Args:
            params (ContourInput):
                - dem_path (str): Input DEM path
                - output_path (str): Output contour polyline feature class path
                - contour_interval (float): Vertical spacing between contours (must be > 0)
                - base_contour (float): Starting elevation value (default: 0.0)

        Returns:
            str: JSON with success, output path, contour count
        """
        try:
            dem = validate_path(params.dem_path)
            out = params.output_path.strip().replace("\\", "/")

            def _contour():
                import arcpy
                from arcpy.sa import Contour
                arcpy.CheckOutExtension("Spatial")
                Contour(dem, out, params.contour_interval, params.base_contour)
                count = int(arcpy.management.GetCount(out).getOutput(0))
                arcpy.CheckInExtension("Spatial")
                return count

            count = await run_arcpy(_contour)
            return tool_result(True, f"Generated {count} contour lines in {out}", {
                "dem_input": dem, "output": out,
                "contour_interval": params.contour_interval,
                "contour_count": count,
            })
        except Exception as e:
            return format_error(e)

    # ------------------------------------------------------------------ #

    @mcp.tool(
        name="arcgis_fill_dem",
        annotations={
            "title": "Fill DEM Sinks (Hydrology)",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def arcgis_fill_dem(params: FillInput) -> str:
        """Fill sinks in a DEM for hydrological analysis.

        Must be run BEFORE flow direction and flow accumulation.
        Sinks are cells with no downslope neighbour — filling ensures
        continuous drainage flow across the surface.
        Requires Spatial Analyst extension.

        Args:
            params (FillInput):
                - dem_path (str): Input DEM path
                - output_path (str): Output filled DEM path
                - z_limit (Optional[float]): Max fill depth; None fills all sinks

        Returns:
            str: JSON with success and output path

        Typical workflow: arcgis_fill_dem → arcgis_flow_direction → arcgis_flow_accumulation → arcgis_watershed
        """
        try:
            dem = validate_path(params.dem_path)
            out = params.output_path.strip().replace("\\", "/")

            def _fill():
                import arcpy
                from arcpy.sa import Fill
                arcpy.CheckOutExtension("Spatial")
                if params.z_limit is not None:
                    result = Fill(dem, params.z_limit)
                else:
                    result = Fill(dem)
                result.save(out)
                arcpy.CheckInExtension("Spatial")

            await run_arcpy(_fill)
            return tool_result(True, f"Filled DEM saved: {out}", {
                "dem_input": dem, "output": out, "z_limit": params.z_limit,
                "next_step": "Run arcgis_flow_direction on this output",
            })
        except Exception as e:
            return format_error(e)

    # ------------------------------------------------------------------ #

    @mcp.tool(
        name="arcgis_flow_direction",
        annotations={
            "title": "Calculate Flow Direction",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def arcgis_flow_direction(params: FlowDirectionInput) -> str:
        """Calculate water flow direction from each DEM cell to its steepest downslope neighbour.

        Input must be a filled (sink-free) DEM from arcgis_fill_dem.
        Output D8 values: 1=East, 2=SE, 4=S, 8=SW, 16=W, 32=NW, 64=N, 128=NE.
        Requires Spatial Analyst extension.

        Args:
            params (FlowDirectionInput):
                - filled_dem_path (str): Filled DEM path
                - output_path (str): Output flow direction raster path
                - flow_direction_type (str): 'D8' or 'MFD' (default: 'D8')

        Returns:
            str: JSON with success and output path
        """
        try:
            dem = validate_path(params.filled_dem_path)
            out = params.output_path.strip().replace("\\", "/")

            def _flow_dir():
                import arcpy
                from arcpy.sa import FlowDirection
                arcpy.CheckOutExtension("Spatial")
                result = FlowDirection(dem, "NORMAL", None, params.flow_direction_type)
                result.save(out)
                arcpy.CheckInExtension("Spatial")

            await run_arcpy(_flow_dir)
            return tool_result(True, f"Flow direction raster saved: {out}", {
                "filled_dem": dem, "output": out,
                "flow_type": params.flow_direction_type,
                "next_step": "Run arcgis_flow_accumulation on this output",
            })
        except Exception as e:
            return format_error(e)

    # ------------------------------------------------------------------ #

    @mcp.tool(
        name="arcgis_flow_accumulation",
        annotations={
            "title": "Calculate Flow Accumulation",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def arcgis_flow_accumulation(params: FlowAccumulationInput) -> str:
        """Calculate accumulated flow (number of upslope cells) for each cell.

        High values indicate drainage channels and rivers.
        Use to delineate drainage networks: select cells where accumulation > threshold.
        Requires Spatial Analyst extension.

        Args:
            params (FlowAccumulationInput):
                - flow_direction_path (str): Flow direction raster path
                - output_path (str): Output accumulation raster path
                - data_type (str): 'FLOAT' or 'INTEGER' (default: 'FLOAT')

        Returns:
            str: JSON with success, output path, and max accumulation value
        """
        try:
            fdir = validate_path(params.flow_direction_path)
            out = params.output_path.strip().replace("\\", "/")

            def _accum():
                import arcpy
                from arcpy.sa import FlowAccumulation
                arcpy.CheckOutExtension("Spatial")
                result = FlowAccumulation(fdir, None, params.data_type)
                result.save(out)
                max_v = float(arcpy.management.GetRasterProperties(out, "MAXIMUM").getOutput(0))
                arcpy.CheckInExtension("Spatial")
                return max_v

            max_acc = await run_arcpy(_accum)
            return tool_result(True, f"Flow accumulation raster saved: {out}", {
                "flow_direction_input": fdir, "output": out,
                "max_accumulation": max_acc,
                "tip": f"High-flow cells (drainage channels): flow_accumulation > {int(max_acc * 0.001)}",
            })
        except Exception as e:
            return format_error(e)

    # ------------------------------------------------------------------ #

    @mcp.tool(
        name="arcgis_watershed",
        annotations={
            "title": "Delineate Watershed",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def arcgis_watershed(params: WatershedInput) -> str:
        """Delineate watershed catchment areas for given outlet (pour) points.

        Use for: sub-catchment mapping, drainage basin analysis,
        CECT (Conserved & Enhanced Conservation Targets) area delineation,
        water supply catchment mapping in plantations.
        Requires Spatial Analyst extension.

        Args:
            params (WatershedInput):
                - flow_direction_path (str): Flow direction raster
                - pour_points_path (str): Outlet point feature class or raster
                - output_path (str): Output watershed raster path
                - pour_point_field (Optional[str]): Field to use as zone ID

        Returns:
            str: JSON with success and output path
        """
        try:
            fdir = validate_path(params.flow_direction_path)
            pour = validate_path(params.pour_points_path)
            out = params.output_path.strip().replace("\\", "/")

            def _watershed():
                import arcpy
                from arcpy.sa import Watershed
                arcpy.CheckOutExtension("Spatial")
                field = params.pour_point_field or ""
                result = Watershed(fdir, pour, field if field else None)
                result.save(out)
                arcpy.CheckInExtension("Spatial")

            await run_arcpy(_watershed)
            return tool_result(True, f"Watershed raster saved: {out}", {
                "flow_direction": fdir, "pour_points": pour, "output": out,
            })
        except Exception as e:
            return format_error(e)

    # ------------------------------------------------------------------ #

    @mcp.tool(
        name="arcgis_slope_classification",
        annotations={
            "title": "Classify Slope for Plantation Planning",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def arcgis_slope_classification(params: SlopeclassInput) -> str:
        """Classify a slope raster into suitability classes for oil palm plantation planning.

        Plantation scheme (Indonesian regulatory standard):
          Class 1 (value=1): 0-8°   → Flat, suitable for mechanised harvesting
          Class 2 (value=2): 8-15°  → Gentle, suitable with manual harvesting
          Class 3 (value=3): 15-25° → Moderate, marginal for planting
          Class 4 (value=4): >25°   → Steep, UNSUITABLE — conservation buffer required

        Standard geomorphological scheme:
          Class 1: 0-5°, Class 2: 5-15°, Class 3: 15-30°, Class 4: 30-45°, Class 5: >45°

        Requires Spatial Analyst extension.

        Args:
            params (SlopeclassInput):
                - dem_path (str): Input DEM path (slope calculated internally)
                - output_path (str): Output classified slope raster path
                - classification_scheme (str): 'PLANTATION' or 'STANDARD' (default: 'PLANTATION')

        Returns:
            str: JSON with success, output path, class areas, and class descriptions
        """
        try:
            dem = validate_path(params.dem_path)
            out = params.output_path.strip().replace("\\", "/")
            scheme = params.classification_scheme.upper()

            def _classify():
                import arcpy
                from arcpy.sa import Reclassify, RemapRange, Slope
                arcpy.CheckOutExtension("Spatial")

                slope_raster = Slope(dem, "DEGREE", 1.0)

                if scheme == "PLANTATION":
                    remap = RemapRange([
                        [0, 8, 1],
                        [8, 15, 2],
                        [15, 25, 3],
                        [25, 90, 4],
                    ])
                    class_desc = {
                        "1": "0-8° (Flat - suitable mechanised)",
                        "2": "8-15° (Gentle - manual harvesting)",
                        "3": "15-25° (Moderate - marginal)",
                        "4": ">25° (Steep - unsuitable/conservation)",
                    }
                else:
                    remap = RemapRange([
                        [0, 5, 1],
                        [5, 15, 2],
                        [15, 30, 3],
                        [30, 45, 4],
                        [45, 90, 5],
                    ])
                    class_desc = {
                        "1": "0-5° (Datar)",
                        "2": "5-15° (Landai)",
                        "3": "15-30° (Agak curam)",
                        "4": "30-45° (Curam)",
                        "5": ">45° (Sangat curam)",
                    }

                classified = Reclassify(slope_raster, "Value", remap, "NODATA")
                classified.save(out)
                arcpy.CheckInExtension("Spatial")
                return class_desc

            class_desc = await run_arcpy(_classify)
            return tool_result(True, f"Slope classified and saved: {out}", {
                "dem_input": dem, "output": out,
                "scheme": scheme,
                "class_descriptions": class_desc,
                "tip": "Use arcgis_zonal_statistics to compute area per class within each plot",
            })
        except Exception as e:
            return format_error(e)
