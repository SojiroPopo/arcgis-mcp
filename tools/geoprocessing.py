"""
Vector geoprocessing tools for ArcGIS MCP Server.

Provides core GIS overlay and proximity tools commonly used in plantation GIS:
clip, buffer, intersect, union, dissolve, spatial join, project, and select.
"""

import os
from typing import List, Optional

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field, field_validator

from utils.helpers import format_error, run_arcpy, tool_result, validate_path


def register(mcp: FastMCP) -> None:
    """Register all geoprocessing tools onto the FastMCP instance."""

    # ------------------------------------------------------------------ #
    # Input Models                                                         #
    # ------------------------------------------------------------------ #

    class ClipInput(BaseModel):
        """Input model for arcgis_clip."""
        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
        input_features: str = Field(..., description="Path to the feature class to be clipped (e.g. 'D:/data/roads.shp')")
        clip_features: str = Field(..., description="Path to the polygon feature class used as clip boundary (e.g. 'D:/data/kebun_boundary.shp')")
        output_path: str = Field(..., description="Full output path including filename (e.g. 'D:/output/roads_clipped.shp')")

    class BufferInput(BaseModel):
        """Input model for arcgis_buffer."""
        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
        input_features: str = Field(..., description="Path to input feature class (points, lines, or polygons)")
        output_path: str = Field(..., description="Full output path including filename")
        distance: float = Field(..., description="Buffer distance as a number (e.g. 30.0)", gt=0)
        distance_unit: str = Field(
            default="Meters",
            description="Distance unit: 'Meters', 'Kilometers', 'Feet', 'Miles', 'Degrees'. Default: 'Meters'",
        )
        dissolve_option: str = Field(
            default="NONE",
            description="How to dissolve output: 'NONE' (keep all buffers separate), 'ALL' (merge all into one), 'LIST' (merge by field). Default: 'NONE'",
        )
        dissolve_fields: Optional[List[str]] = Field(
            default=None,
            description="Field names to dissolve by when dissolve_option='LIST', e.g. ['DIVISI', 'AFDELING']",
        )

        @field_validator("dissolve_option")
        @classmethod
        def validate_dissolve(cls, v: str) -> str:
            allowed = {"NONE", "ALL", "LIST"}
            v = v.upper()
            if v not in allowed:
                raise ValueError(f"dissolve_option must be one of {allowed}")
            return v

    class IntersectInput(BaseModel):
        """Input model for arcgis_intersect."""
        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
        input_features: List[str] = Field(
            ...,
            description="List of 2 or more input feature class paths to intersect, e.g. ['D:/plots.shp', 'D:/slopes.shp']",
            min_length=2,
        )
        output_path: str = Field(..., description="Full output path including filename")
        join_attributes: str = Field(
            default="ALL",
            description="Which attributes to retain: 'ALL' (all fields), 'NO_FID', or 'ONLY_FID'. Default: 'ALL'",
        )

    class UnionInput(BaseModel):
        """Input model for arcgis_union."""
        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
        input_features: List[str] = Field(
            ...,
            description="List of 2 or more polygon feature class paths to union",
            min_length=2,
        )
        output_path: str = Field(..., description="Full output path including filename")

    class DissolveInput(BaseModel):
        """Input model for arcgis_dissolve."""
        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
        input_features: str = Field(..., description="Path to input polygon feature class")
        output_path: str = Field(..., description="Full output path including filename")
        dissolve_fields: Optional[List[str]] = Field(
            default=None,
            description="Field names to group by during dissolve, e.g. ['DIVISI', 'AFDELING']. If None, dissolves all features into one.",
        )
        statistics_fields: Optional[List[str]] = Field(
            default=None,
            description="Statistics to compute in format 'FIELD STATISTIC', e.g. ['LUAS_HA SUM', 'POHON COUNT']",
        )

    class SpatialJoinInput(BaseModel):
        """Input model for arcgis_spatial_join."""
        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
        target_features: str = Field(..., description="Path to target feature class (receives attributes from join)")
        join_features: str = Field(..., description="Path to join feature class (attributes transferred from this)")
        output_path: str = Field(..., description="Full output path including filename")
        join_operation: str = Field(
            default="JOIN_ONE_TO_ONE",
            description="'JOIN_ONE_TO_ONE' (keep one match per target feature) or 'JOIN_ONE_TO_MANY' (keep all matches). Default: 'JOIN_ONE_TO_ONE'",
        )
        match_option: str = Field(
            default="INTERSECT",
            description="Spatial relationship: 'INTERSECT', 'WITHIN', 'CONTAINS', 'CLOSEST', 'COMPLETELY_WITHIN'. Default: 'INTERSECT'",
        )

    class ProjectInput(BaseModel):
        """Input model for arcgis_project."""
        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
        input_dataset: str = Field(..., description="Path to input feature class or raster to reproject")
        output_dataset: str = Field(..., description="Full output path including filename")
        out_crs: str = Field(
            ...,
            description=(
                "Target coordinate system. Use EPSG/WKID code as string (e.g. '32750' for WGS84 UTM Zone 50S, "
                "'4326' for WGS84 Geographic, '23830' for DGN95/UTM Zone 50N, '32748' for WGS84 UTM Zone 48S)"
            ),
        )

    class SelectByAttributeInput(BaseModel):
        """Input model for arcgis_select_by_attribute."""
        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
        input_features: str = Field(..., description="Path to input feature class")
        output_path: str = Field(..., description="Full output path for selected features")
        where_clause: str = Field(
            ...,
            description="SQL WHERE expression, e.g. \"LUAS_HA > 20 AND DIVISI = 'ALPHA'\"",
            min_length=1,
        )

    class EraseInput(BaseModel):
        """Input model for arcgis_erase."""
        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
        input_features: str = Field(..., description="Path to input feature class from which areas will be erased")
        erase_features: str = Field(..., description="Path to polygon feature class defining areas to erase")
        output_path: str = Field(..., description="Full output path including filename")

    class RepairGeometryInput(BaseModel):
        """Input model for arcgis_repair_geometry."""
        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
        input_features: str = Field(..., description="Path to feature class with geometry to repair")

    # ------------------------------------------------------------------ #
    # Tool Implementations                                                 #
    # ------------------------------------------------------------------ #

    @mcp.tool(
        name="arcgis_clip",
        annotations={
            "title": "Clip Features",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def arcgis_clip(params: ClipInput) -> str:
        """Clip input features using a polygon boundary (like cookie-cutter).

        Commonly used to clip roads, rivers, or land-use data to the plantation boundary.

        Args:
            params (ClipInput):
                - input_features (str): Feature class to clip
                - clip_features (str): Polygon used as the clip extent (e.g. kebun boundary)
                - output_path (str): Output path

        Returns:
            str: JSON with success, output path, and output feature count

        Examples:
            - "Clip jalan_utama.shp to batas_kebun.shp" → use arcgis_clip
            - "Extract rivers within plantation boundary" → use arcgis_clip
        """
        try:
            in_fc = validate_path(params.input_features)
            clip_fc = validate_path(params.clip_features)
            out = params.output_path.strip().replace("\\", "/")

            def _clip():
                import arcpy
                arcpy.analysis.Clip(in_fc, clip_fc, out)
                count = int(arcpy.management.GetCount(out).getOutput(0))
                return count

            count = await run_arcpy(_clip)
            return tool_result(True, f"Clip completed. {count} features written to {out}", {
                "input": in_fc, "clip_boundary": clip_fc, "output": out, "feature_count": count,
            })
        except Exception as e:
            return format_error(e)

    # ------------------------------------------------------------------ #

    @mcp.tool(
        name="arcgis_buffer",
        annotations={
            "title": "Buffer Features",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def arcgis_buffer(params: BufferInput) -> str:
        """Create buffer polygons around input features at a specified distance.

        Commonly used for riparian buffer zones (30m from rivers), road setbacks,
        conservation buffer analysis, HCV buffer delineation.

        Args:
            params (BufferInput):
                - input_features (str): Points, lines, or polygons to buffer
                - output_path (str): Output path
                - distance (float): Buffer distance (must be > 0)
                - distance_unit (str): 'Meters', 'Kilometers', 'Feet' (default: 'Meters')
                - dissolve_option (str): 'NONE', 'ALL', or 'LIST' (default: 'NONE')
                - dissolve_fields (Optional[List[str]]): Fields to dissolve by (only for 'LIST')

        Returns:
            str: JSON with success, output path, feature count

        Examples:
            - "Buffer sungai.shp by 30m" → distance=30, distance_unit='Meters'
            - "Create 50m buffer around jalan, dissolve by DIVISI" → dissolve_option='LIST', dissolve_fields=['DIVISI']
        """
        try:
            in_fc = validate_path(params.input_features)
            out = params.output_path.strip().replace("\\", "/")
            dist_str = f"{params.distance} {params.distance_unit}"
            dissolve = params.dissolve_option
            dissolve_fields = params.dissolve_fields or []

            def _buffer():
                import arcpy
                arcpy.analysis.Buffer(
                    in_features=in_fc,
                    out_feature_class=out,
                    buffer_distance_or_field=dist_str,
                    dissolve_option=dissolve,
                    dissolve_field=dissolve_fields if dissolve == "LIST" else None,
                )
                count = int(arcpy.management.GetCount(out).getOutput(0))
                return count

            count = await run_arcpy(_buffer)
            return tool_result(True, f"Buffer {dist_str} completed. {count} features in {out}", {
                "input": in_fc, "output": out,
                "distance": dist_str, "dissolve_option": dissolve,
                "feature_count": count,
            })
        except Exception as e:
            return format_error(e)

    # ------------------------------------------------------------------ #

    @mcp.tool(
        name="arcgis_intersect",
        annotations={
            "title": "Intersect Features",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def arcgis_intersect(params: IntersectInput) -> str:
        """Intersect two or more feature classes — keeps only overlapping geometry.

        Commonly used to overlay plot boundaries with land-use/slope/soil maps
        to compute areas of each category within each plot.

        Args:
            params (IntersectInput):
                - input_features (List[str]): 2+ feature class paths
                - output_path (str): Output path
                - join_attributes (str): 'ALL', 'NO_FID', or 'ONLY_FID' (default: 'ALL')

        Returns:
            str: JSON with success, output path, feature count

        Examples:
            - "Overlay plots with slope class raster (polygonised)" → arcgis_intersect
            - "Find area of each land-use type within each plot" → arcgis_intersect([plots, landuse])
        """
        try:
            in_fcs = [validate_path(p) for p in params.input_features]
            out = params.output_path.strip().replace("\\", "/")
            join_attr = params.join_attributes

            def _intersect():
                import arcpy
                arcpy.analysis.Intersect(in_fcs, out, join_attributes=join_attr)
                count = int(arcpy.management.GetCount(out).getOutput(0))
                return count

            count = await run_arcpy(_intersect)
            return tool_result(True, f"Intersect completed. {count} features in {out}", {
                "inputs": in_fcs, "output": out,
                "join_attributes": join_attr, "feature_count": count,
            })
        except Exception as e:
            return format_error(e)

    # ------------------------------------------------------------------ #

    @mcp.tool(
        name="arcgis_union",
        annotations={
            "title": "Union Features",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def arcgis_union(params: UnionInput) -> str:
        """Union two or more polygon feature classes — keeps ALL geometry from all inputs.

        Use when you need to combine plantation blocks with other polygon layers
        and retain all boundaries from both datasets.

        Args:
            params (UnionInput):
                - input_features (List[str]): 2+ polygon feature class paths
                - output_path (str): Output path

        Returns:
            str: JSON with success, output path, feature count
        """
        try:
            in_fcs = [validate_path(p) for p in params.input_features]
            out = params.output_path.strip().replace("\\", "/")

            def _union():
                import arcpy
                arcpy.analysis.Union(in_fcs, out)
                count = int(arcpy.management.GetCount(out).getOutput(0))
                return count

            count = await run_arcpy(_union)
            return tool_result(True, f"Union completed. {count} features in {out}", {
                "inputs": in_fcs, "output": out, "feature_count": count,
            })
        except Exception as e:
            return format_error(e)

    # ------------------------------------------------------------------ #

    @mcp.tool(
        name="arcgis_dissolve",
        annotations={
            "title": "Dissolve Features",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def arcgis_dissolve(params: DissolveInput) -> str:
        """Dissolve (merge) polygon features by attribute values, optionally computing statistics.

        Common use cases:
        - Dissolve individual plots into Afdeling or Divisi polygons
        - Aggregate small land-use parcels into larger units
        - Compute total area per management unit

        Args:
            params (DissolveInput):
                - input_features (str): Polygon feature class
                - output_path (str): Output path
                - dissolve_fields (Optional[List[str]]): Group-by fields (e.g. ['DIVISI', 'AFDELING'])
                - statistics_fields (Optional[List[str]]): Stats in 'FIELD STAT' format (e.g. ['LUAS_HA SUM'])

        Returns:
            str: JSON with success, output path, feature count

        Examples:
            - "Merge blok plots into afdeling" → dissolve_fields=['AFDELING']
            - "Sum LUAS_HA per DIVISI" → dissolve_fields=['DIVISI'], statistics_fields=['LUAS_HA SUM']
        """
        try:
            in_fc = validate_path(params.input_features)
            out = params.output_path.strip().replace("\\", "/")
            d_fields = params.dissolve_fields or []
            stats = params.statistics_fields or []

            def _dissolve():
                import arcpy
                stat_fields = [[s.rsplit(" ", 1)[0], s.rsplit(" ", 1)[1]] for s in stats if " " in s]
                arcpy.management.Dissolve(
                    in_features=in_fc,
                    out_feature_class=out,
                    dissolve_field=d_fields if d_fields else None,
                    statistics_fields=stat_fields if stat_fields else None,
                )
                count = int(arcpy.management.GetCount(out).getOutput(0))
                return count

            count = await run_arcpy(_dissolve)
            return tool_result(True, f"Dissolve completed. {count} features in {out}", {
                "input": in_fc, "output": out,
                "dissolve_fields": d_fields,
                "statistics_fields": stats,
                "feature_count": count,
            })
        except Exception as e:
            return format_error(e)

    # ------------------------------------------------------------------ #

    @mcp.tool(
        name="arcgis_spatial_join",
        annotations={
            "title": "Spatial Join",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def arcgis_spatial_join(params: SpatialJoinInput) -> str:
        """Join attributes from one feature class to another based on spatial relationship.

        Common use cases:
        - Attach soil type, land-use class, or slope class to each planting block
        - Assign Divisi/Afdeling attributes to survey points

        Args:
            params (SpatialJoinInput):
                - target_features (str): Feature class that receives attributes
                - join_features (str): Feature class that provides attributes
                - output_path (str): Output path
                - join_operation (str): 'JOIN_ONE_TO_ONE' or 'JOIN_ONE_TO_MANY'
                - match_option (str): 'INTERSECT', 'WITHIN', 'CONTAINS', 'CLOSEST', etc.

        Returns:
            str: JSON with success, output path, feature count
        """
        try:
            target = validate_path(params.target_features)
            join = validate_path(params.join_features)
            out = params.output_path.strip().replace("\\", "/")

            def _sjoin():
                import arcpy
                arcpy.analysis.SpatialJoin(
                    target_features=target,
                    join_features=join,
                    out_feature_class=out,
                    join_operation=params.join_operation,
                    match_option=params.match_option,
                )
                count = int(arcpy.management.GetCount(out).getOutput(0))
                return count

            count = await run_arcpy(_sjoin)
            return tool_result(True, f"Spatial join completed. {count} features in {out}", {
                "target": target, "join": join, "output": out,
                "join_operation": params.join_operation,
                "match_option": params.match_option,
                "feature_count": count,
            })
        except Exception as e:
            return format_error(e)

    # ------------------------------------------------------------------ #

    @mcp.tool(
        name="arcgis_project",
        annotations={
            "title": "Project / Reproject Dataset",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def arcgis_project(params: ProjectInput) -> str:
        """Reproject a feature class or raster to a different coordinate system.

        Common use cases in Indonesian plantations:
        - Convert WGS84 (4326) to UTM for area calculations
        - Convert between UTM zones (Sumatra: 47N/48N, Kalimantan: 49N/50N/49S/50S)
        - Convert from DGN95 to WGS84

        Args:
            params (ProjectInput):
                - input_dataset (str): Dataset to reproject
                - output_dataset (str): Output path
                - out_crs (str): Target EPSG/WKID code as string

        Returns:
            str: JSON with success, output path, and applied CRS info

        Common WKID codes for Indonesia:
            - 4326: WGS 1984 Geographic
            - 32647: WGS84 UTM Zone 47N (Sumatra barat)
            - 32748: WGS84 UTM Zone 48S (Kalimantan)
            - 32750: WGS84 UTM Zone 50S (Kalimantan Timur)
            - 23830: DGN95 / Indonesia TM-3 zone 49.1
        """
        try:
            in_ds = validate_path(params.input_dataset)
            out_ds = params.output_dataset.strip().replace("\\", "/")
            crs_code = params.out_crs.strip()

            def _project():
                import arcpy
                sr = arcpy.SpatialReference(int(crs_code))
                arcpy.management.Project(in_ds, out_ds, sr)
                desc = arcpy.Describe(out_ds)
                return desc.spatialReference.name

            sr_name = await run_arcpy(_project)
            return tool_result(True, f"Projected to {sr_name}", {
                "input": in_ds, "output": out_ds,
                "target_wkid": crs_code, "spatial_reference": sr_name,
            })
        except Exception as e:
            return format_error(e)

    # ------------------------------------------------------------------ #

    @mcp.tool(
        name="arcgis_select_by_attribute",
        annotations={
            "title": "Select Features by Attribute",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def arcgis_select_by_attribute(params: SelectByAttributeInput) -> str:
        """Export a subset of features matching a SQL WHERE clause to a new feature class.

        Args:
            params (SelectByAttributeInput):
                - input_features (str): Source feature class
                - output_path (str): Output path for selected features
                - where_clause (str): SQL expression, e.g. "DIVISI = 'ALPHA' AND LUAS_HA > 10"

        Returns:
            str: JSON with success, output path, selected feature count

        Examples:
            - Select all plots > 20 ha: where_clause="LUAS_HA > 20"
            - Select Afdeling 1 plots: where_clause="AFDELING = '1'"
            - Select plots needing replanting: where_clause="TAHUN_TANAM <= 1995"
        """
        try:
            in_fc = validate_path(params.input_features)
            out = params.output_path.strip().replace("\\", "/")
            where = params.where_clause

            def _select():
                import arcpy
                lyr = arcpy.management.MakeFeatureLayer(in_fc, "tmp_sel_lyr", where).getOutput(0)
                arcpy.management.CopyFeatures(lyr, out)
                arcpy.management.Delete(lyr)
                count = int(arcpy.management.GetCount(out).getOutput(0))
                return count

            count = await run_arcpy(_select)
            return tool_result(True, f"Selected {count} features matching '{where}'", {
                "input": in_fc, "output": out,
                "where_clause": where, "selected_count": count,
            })
        except Exception as e:
            return format_error(e)

    # ------------------------------------------------------------------ #

    @mcp.tool(
        name="arcgis_erase",
        annotations={
            "title": "Erase Features",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def arcgis_erase(params: EraseInput) -> str:
        """Erase areas from input features using an erase polygon (reverse of clip).

        Common uses:
        - Remove conservation zones (HCV, riparian) from plantable area
        - Subtract peat soil areas from planting blocks
        - Remove slope > 25 degrees areas from development plans

        Implementation note: Uses arcpy Geometry.difference() instead of
        arcpy.analysis.Erase() to avoid requiring ArcGIS Advanced license.
        This method is available at Basic/Standard license levels.

        Args:
            params (EraseInput):
                - input_features (str): Feature class to erase from
                - erase_features (str): Polygon mask defining areas to remove
                - output_path (str): Output path

        Returns:
            str: JSON with success, output path, feature count
        """
        try:
            in_fc = validate_path(params.input_features)
            erase_fc = validate_path(params.erase_features)
            out = params.output_path.strip().replace("\\", "/")

            def _erase():
                import arcpy

                # Step 1: Load and union all erase geometries into one shape.
                # Using Geometry.union() which is available at Basic license.
                erase_geoms = []
                with arcpy.da.SearchCursor(erase_fc, ["SHAPE@"]) as cur:
                    for (geom,) in cur:
                        if geom is not None:
                            erase_geoms.append(geom)

                # No erase features — copy input unchanged
                if not erase_geoms:
                    arcpy.management.CopyFeatures(in_fc, out)
                    return int(arcpy.management.GetCount(out).getOutput(0))

                erase_union = erase_geoms[0]
                for g in erase_geoms[1:]:
                    erase_union = erase_union.union(g)

                # Step 2: Read input schema
                desc = arcpy.Describe(in_fc)
                sr = desc.spatialReference
                geom_type = desc.shapeType.upper()  # POLYGON, POLYLINE, POINT

                # Identify fields to copy (skip OID, Shape, and derived fields)
                skip_upper = {"SHAPE_AREA", "SHAPE_LENGTH", "SHAPE.AREA", "SHAPE.LENGTH"}
                copy_fields = [
                    f for f in arcpy.ListFields(in_fc)
                    if f.type not in ("Geometry", "OID")
                    and f.name.upper() not in skip_upper
                ]
                fld_names = [f.name for f in copy_fields]

                # Step 3: Create output feature class with same schema as input
                out_ws = os.path.dirname(out)
                out_name = os.path.basename(out)
                arcpy.management.CreateFeatureclass(
                    out_ws, out_name, geom_type, spatial_reference=sr
                )
                for f in copy_fields:
                    arcpy.management.AddField(
                        out, f.name, f.type,
                        field_precision=f.precision,
                        field_scale=f.scale,
                        field_length=f.length,
                        field_alias=f.aliasName,
                        field_is_nullable="NULLABLE" if f.isNullable else "NON_NULLABLE",
                    )

                # Step 4: Compute Geometry.difference() for each input feature.
                # Geometry.difference() is available at Basic/Standard license.
                count = 0
                read_flds = ["SHAPE@"] + fld_names
                with arcpy.da.SearchCursor(in_fc, read_flds) as src, \
                        arcpy.da.InsertCursor(out, read_flds) as dst:
                    for row in src:
                        geom = row[0]
                        if geom is None:
                            continue
                        diff = geom.difference(erase_union)
                        if diff is not None and diff.pointCount > 0:
                            dst.insertRow((diff,) + row[1:])
                            count += 1

                return count

            count = await run_arcpy(_erase)
            return tool_result(True, f"Erase completed. {count} features in {out}", {
                "input": in_fc, "erase_mask": erase_fc,
                "output": out, "feature_count": count,
                "method": "geometry_difference (Basic/Standard license compatible)",
            })
        except Exception as e:
            return format_error(e)

    # ------------------------------------------------------------------ #

    @mcp.tool(
        name="arcgis_repair_geometry",
        annotations={
            "title": "Repair Geometry",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def arcgis_repair_geometry(params: RepairGeometryInput) -> str:
        """Fix invalid or null geometry in a feature class (self-intersections, null parts).

        Run this when geoprocessing tools report geometry errors.
        Modifies the feature class IN PLACE — no output path needed.

        Args:
            params (RepairGeometryInput):
                - input_features (str): Feature class with geometry problems

        Returns:
            str: JSON with success and count of repaired features
        """
        try:
            in_fc = validate_path(params.input_features)

            def _repair():
                import arcpy
                result = arcpy.management.RepairGeometry(in_fc, "DELETE_NULL")
                return arcpy.GetMessages()

            messages = await run_arcpy(_repair)
            return tool_result(True, "Geometry repaired successfully.", {
                "input": in_fc, "arcpy_messages": messages,
            })
        except Exception as e:
            return format_error(e)
