"""
Map Layout tools for ArcGIS MCP Server.

Provides tools for creating, listing, updating, and exporting map layouts
in ArcGIS Pro (.aprx) projects using the arcpy.mp Mapping module.

Requires ArcGIS Pro 2.6+ (createLayout API).
"""

from typing import Optional

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field, field_validator

from utils.helpers import format_error, run_arcpy, success_json, tool_result, validate_path

# Paper sizes: name → (portrait_width_inches, portrait_height_inches)
PAPER_SIZES = {
    "A4":      (8.27,  11.69),
    "A3":      (11.69, 16.54),
    "A2":      (16.54, 23.39),
    "A1":      (23.39, 33.11),
    "A0":      (33.11, 46.81),
    "Letter":  (8.5,   11.0),
    "Tabloid": (11.0,  17.0),
}

VALID_PAPER_SIZES = list(PAPER_SIZES.keys())
VALID_EXPORT_FORMATS = ["PDF", "PNG", "JPG", "TIFF"]


def register(mcp: FastMCP) -> None:
    """Register all map layout tools onto the FastMCP instance."""

    # ------------------------------------------------------------------ #
    # Input Models                                                         #
    # ------------------------------------------------------------------ #

    class CreateMapLayoutInput(BaseModel):
        """Input model for arcgis_create_map_layout."""
        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

        project_path: str = Field(
            ...,
            description="Full path to ArcGIS Pro project file (.aprx), e.g. 'D:/projects/MyMap.aprx'",
        )
        map_name: str = Field(
            ...,
            description="Name of the map inside the project to display in the layout",
        )
        layout_name: str = Field(
            ...,
            description="Name for the new layout (must be unique within the project)",
        )
        paper_size: str = Field(
            default="A3",
            description=(
                f"Paper size. One of: {', '.join(VALID_PAPER_SIZES)}. "
                "Dimensions in inches (portrait): A4=8.27x11.69, A3=11.69x16.54, "
                "A2=16.54x23.39, A1=23.39x33.11, A0=33.11x46.81, "
                "Letter=8.5x11, Tabloid=11x17"
            ),
        )
        orientation: str = Field(
            default="landscape",
            description="Page orientation: 'landscape' or 'portrait'",
        )
        layout_type: str = Field(
            default="formal",
            description=(
                "Layout style: "
                "'formal' includes title, map frame with margins for legend/scale/north arrow, and neat line border; "
                "'informal' uses maximum map frame area with minimal margins, suitable for working maps"
            ),
        )
        title: Optional[str] = Field(
            default=None,
            description="Map title text. Used as title element text in formal layouts. Defaults to map_name if not provided.",
        )
        scale: Optional[float] = Field(
            default=None,
            description="Map scale denominator, e.g. 10000 for 1:10,000. If omitted, the map frame will show all layers.",
            gt=0,
        )

        @field_validator("paper_size")
        @classmethod
        def validate_paper_size(cls, v: str) -> str:
            if v not in PAPER_SIZES:
                raise ValueError(
                    f"Invalid paper_size '{v}'. Choose from: {', '.join(VALID_PAPER_SIZES)}"
                )
            return v

        @field_validator("orientation")
        @classmethod
        def validate_orientation(cls, v: str) -> str:
            v = v.lower()
            if v not in ("landscape", "portrait"):
                raise ValueError("orientation must be 'landscape' or 'portrait'")
            return v

        @field_validator("layout_type")
        @classmethod
        def validate_layout_type(cls, v: str) -> str:
            v = v.lower()
            if v not in ("formal", "informal"):
                raise ValueError("layout_type must be 'formal' or 'informal'")
            return v

    class ExportMapLayoutInput(BaseModel):
        """Input model for arcgis_export_map_layout."""
        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

        project_path: str = Field(
            ...,
            description="Full path to .aprx ArcGIS Pro project file",
        )
        layout_name: str = Field(
            ...,
            description="Name of the layout to export",
        )
        output_path: str = Field(
            ...,
            description="Full output file path including extension, e.g. 'D:/output/map.pdf'",
        )
        format: str = Field(
            default="PDF",
            description=f"Export format: {', '.join(VALID_EXPORT_FORMATS)} (default: PDF)",
        )
        resolution: int = Field(
            default=300,
            description="Output resolution in DPI (default: 300, max: 2400)",
            gt=0,
            le=2400,
        )

        @field_validator("format")
        @classmethod
        def validate_format(cls, v: str) -> str:
            v = v.upper()
            if v not in VALID_EXPORT_FORMATS:
                raise ValueError(
                    f"Invalid format '{v}'. Choose from: {', '.join(VALID_EXPORT_FORMATS)}"
                )
            return v

    class ListMapLayoutsInput(BaseModel):
        """Input model for arcgis_list_map_layouts."""
        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

        project_path: str = Field(
            ...,
            description="Full path to .aprx ArcGIS Pro project file",
        )

    class UpdateLayoutElementsInput(BaseModel):
        """Input model for arcgis_update_layout_elements."""
        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

        project_path: str = Field(
            ...,
            description="Full path to .aprx ArcGIS Pro project file",
        )
        layout_name: str = Field(
            ...,
            description="Name of the layout to update",
        )
        title: Optional[str] = Field(
            default=None,
            description=(
                "New title text for the title text element. "
                "Targets elements with 'title' in their name (case-insensitive); "
                "falls back to the first text element if only one exists."
            ),
        )
        scale: Optional[float] = Field(
            default=None,
            description="New map scale denominator for the first map frame, e.g. 25000 for 1:25,000",
            gt=0,
        )

    # ------------------------------------------------------------------ #
    # Tool Implementations                                                 #
    # ------------------------------------------------------------------ #

    @mcp.tool(
        name="arcgis_create_map_layout",
        annotations={
            "title": "Create Map Layout",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def arcgis_create_map_layout(params: CreateMapLayoutInput) -> str:
        """Create a new map layout in an ArcGIS Pro project using arcpy.mp.

        Builds the layout from scratch: sets the page size, creates a map frame
        linked to the specified map, and adds a title text element (ArcGIS Pro 3.x+).

        Formal layout reserves margins for title (top), scale bar / legend strip
        (bottom), and a neat line border. Informal layout maximises the map frame
        with minimal margins and a smaller title strip.

        Args:
            params (CreateMapLayoutInput):
                - project_path (str): Path to .aprx file
                - map_name (str): Map to display
                - layout_name (str): Unique name for the new layout
                - paper_size (str): A4/A3/A2/A1/A0/Letter/Tabloid (default: A3)
                - orientation (str): landscape/portrait (default: landscape)
                - layout_type (str): formal/informal (default: formal)
                - title (Optional[str]): Title text (defaults to map_name)
                - scale (Optional[float]): Scale denominator, e.g. 10000

        Returns:
            str: JSON with success, layout_name, page_width, page_height, page_units,
                 paper_size, orientation, layout_type, elements_added

        Error responses:
            - "Validation error: ..." for invalid parameters
            - "Validation error: Layout '...' already exists..." if name taken
            - "Validation error: Map '...' not found..." if map missing
        """
        try:
            project_path = validate_path(params.project_path)
            map_name = params.map_name
            layout_name = params.layout_name
            paper_size = params.paper_size
            orientation = params.orientation
            layout_type = params.layout_type
            title_text = params.title or params.map_name
            scale = params.scale

            def _create():
                import arcpy

                project = arcpy.mp.ArcGISProject(project_path)

                # Guard: layout name must be unique
                existing_names = [lyt.name for lyt in project.listLayouts()]
                if layout_name in existing_names:
                    raise ValueError(
                        f"Layout '{layout_name}' already exists in project. "
                        f"Choose a different name or delete the existing layout first."
                    )

                # Page dimensions (portrait base, swap for landscape)
                pw, ph = PAPER_SIZES[paper_size]
                if orientation == "landscape":
                    pw, ph = ph, pw

                # Create the layout
                lyt = project.createLayout(pw, ph, "INCH", layout_name)

                # Find the target map
                all_maps = project.listMaps()
                target = [m for m in all_maps if m.name == map_name]
                if not target:
                    available = [m.name for m in all_maps]
                    raise ValueError(
                        f"Map '{map_name}' not found in project. "
                        f"Available maps: {available}"
                    )
                m = target[0]

                elements_added = []

                # --- Layout geometry ---
                if layout_type == "formal":
                    margin = 0.4          # outer margin
                    title_h = 0.65        # top title strip height
                    bottom_h = 0.75       # bottom strip for scale bar / legend
                else:
                    margin = 0.15
                    title_h = 0.35
                    bottom_h = 0.45

                # Map frame
                mf_ext = arcpy.Extent(
                    margin,
                    margin + bottom_h,
                    pw - margin,
                    ph - margin - title_h,
                )
                mf = lyt.createMapFrame(mf_ext, m, "Main Map Frame")
                elements_added.append("Map Frame")

                # Set scale if requested
                if scale is not None:
                    mf.camera.scale = scale

                # --- Title text element (ArcGIS Pro 3.x) ---
                title_ext = arcpy.Extent(
                    margin,
                    ph - margin - title_h,
                    pw - margin,
                    ph - margin,
                )
                try:
                    arcpy.mp.CreateTextElement(
                        lyt,
                        title_ext,
                        None,
                        title_text,
                        font_size=(18.0 if layout_type == "formal" else 12.0),
                        bold=(layout_type == "formal"),
                        element_name="Title",
                    )
                    elements_added.append("Title")
                except (AttributeError, TypeError, Exception):
                    # CreateTextElement not available (<Pro 3.x) — skip silently
                    pass

                project.save()

                return {
                    "layout_name": lyt.name,
                    "page_width": round(lyt.pageWidth, 3),
                    "page_height": round(lyt.pageHeight, 3),
                    "page_units": lyt.pageUnits,
                    "paper_size": paper_size,
                    "orientation": orientation,
                    "layout_type": layout_type,
                    "elements_added": elements_added,
                }

            data = await run_arcpy(_create)
            return tool_result(
                True,
                f"Layout '{layout_name}' created ({paper_size} {orientation})",
                data,
            )

        except Exception as e:
            return format_error(e)

    # ------------------------------------------------------------------ #

    @mcp.tool(
        name="arcgis_export_map_layout",
        annotations={
            "title": "Export Map Layout",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def arcgis_export_map_layout(params: ExportMapLayoutInput) -> str:
        """Export a named layout from an ArcGIS Pro project to a file.

        Supports PDF (vector), PNG, JPG, and TIFF output at any DPI.
        The output file is written to the path specified by output_path.

        Args:
            params (ExportMapLayoutInput):
                - project_path (str): Path to .aprx file
                - layout_name (str): Layout to export
                - output_path (str): Destination file path (with extension)
                - format (str): PDF/PNG/JPG/TIFF (default: PDF)
                - resolution (int): DPI (default: 300)

        Returns:
            str: JSON with success, output_path, format, resolution, layout_name

        Error responses:
            - "Validation error: Layout '...' not found" if layout missing
        """
        try:
            project_path = validate_path(params.project_path)
            layout_name = params.layout_name
            output_path = params.output_path.strip().replace("\\", "/")
            fmt = params.format
            resolution = params.resolution

            def _export():
                import arcpy

                project = arcpy.mp.ArcGISProject(project_path)
                layouts = [lyt for lyt in project.listLayouts() if lyt.name == layout_name]
                if not layouts:
                    available = [lyt.name for lyt in project.listLayouts()]
                    raise ValueError(
                        f"Layout '{layout_name}' not found in project. "
                        f"Available: {available}"
                    )
                lyt = layouts[0]

                if fmt == "PDF":
                    lyt.exportToPDF(output_path, resolution=resolution)
                elif fmt == "PNG":
                    lyt.exportToPNG(output_path, resolution=resolution)
                elif fmt == "JPG":
                    lyt.exportToJPEG(output_path, resolution=resolution)
                elif fmt == "TIFF":
                    lyt.exportToTIFF(output_path, resolution=resolution)

                return output_path

            out = await run_arcpy(_export)
            return tool_result(
                True,
                f"Exported '{layout_name}' to {out} ({fmt}, {resolution} DPI)",
                {
                    "output_path": out,
                    "format": fmt,
                    "resolution": resolution,
                    "layout_name": layout_name,
                },
            )

        except Exception as e:
            return format_error(e)

    # ------------------------------------------------------------------ #

    @mcp.tool(
        name="arcgis_list_map_layouts",
        annotations={
            "title": "List Map Layouts",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def arcgis_list_map_layouts(params: ListMapLayoutsInput) -> str:
        """List all layouts in an ArcGIS Pro project (.aprx).

        Returns name, page dimensions, units, and element inventory for each layout.

        Args:
            params (ListMapLayoutsInput):
                - project_path (str): Path to .aprx file

        Returns:
            str: JSON with:
                - project_path: normalised path
                - layout_count: int
                - layouts: list of {name, page_width, page_height, page_units,
                                    element_count, elements}
        """
        try:
            project_path = validate_path(params.project_path)

            def _list():
                import arcpy

                project = arcpy.mp.ArcGISProject(project_path)
                result = []
                for lyt in project.listLayouts():
                    elems = lyt.listElements()
                    result.append({
                        "name": lyt.name,
                        "page_width": round(lyt.pageWidth, 3),
                        "page_height": round(lyt.pageHeight, 3),
                        "page_units": lyt.pageUnits,
                        "element_count": len(elems),
                        "elements": [e.name for e in elems],
                    })
                return result

            layouts = await run_arcpy(_list)
            return success_json({
                "project_path": project_path,
                "layout_count": len(layouts),
                "layouts": layouts,
            })

        except Exception as e:
            return format_error(e)

    # ------------------------------------------------------------------ #

    @mcp.tool(
        name="arcgis_update_layout_elements",
        annotations={
            "title": "Update Layout Elements",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def arcgis_update_layout_elements(params: UpdateLayoutElementsInput) -> str:
        """Update elements in an existing layout: change the title text or map scale.

        Title update: targets TEXT_ELEMENTs whose name contains 'title'
        (case-insensitive). Falls back to the first text element when only one exists.

        Scale update: sets the camera scale on the first MAPFRAME_ELEMENT.

        Args:
            params (UpdateLayoutElementsInput):
                - project_path (str): Path to .aprx file
                - layout_name (str): Layout to modify
                - title (Optional[str]): New title text
                - scale (Optional[float]): New scale denominator

        Returns:
            str: JSON with success, layout_name, changes (list of applied changes)

        Error responses:
            - "Validation error: Layout '...' not found" if layout missing
        """
        try:
            project_path = validate_path(params.project_path)
            layout_name = params.layout_name
            new_title = params.title
            new_scale = params.scale

            def _update():
                import arcpy

                project = arcpy.mp.ArcGISProject(project_path)
                layouts = [lyt for lyt in project.listLayouts() if lyt.name == layout_name]
                if not layouts:
                    available = [lyt.name for lyt in project.listLayouts()]
                    raise ValueError(
                        f"Layout '{layout_name}' not found. "
                        f"Available: {available}"
                    )
                lyt = layouts[0]
                changes = []

                # --- Update title ---
                if new_title is not None:
                    text_elems = lyt.listElements("TEXT_ELEMENT")
                    title_elems = [
                        e for e in text_elems if "title" in e.name.lower()
                    ]
                    if title_elems:
                        for te in title_elems:
                            te.text = new_title
                        changes.append(f"title → '{new_title}'")
                    elif len(text_elems) == 1:
                        text_elems[0].text = new_title
                        changes.append(f"text element → '{new_title}'")
                    else:
                        changes.append(
                            "title: no element named 'title' found "
                            f"(text elements present: {[e.name for e in text_elems]})"
                        )

                # --- Update scale ---
                if new_scale is not None:
                    mf_elems = lyt.listElements("MAPFRAME_ELEMENT")
                    if mf_elems:
                        mf_elems[0].camera.scale = new_scale
                        changes.append(f"scale → 1:{int(new_scale):,}")
                    else:
                        changes.append("scale: no map frame element found in layout")

                project.save()
                return changes

            changes = await run_arcpy(_update)
            return tool_result(
                True,
                f"Updated layout '{layout_name}': {len(changes)} change(s)",
                {"layout_name": layout_name, "changes": changes},
            )

        except Exception as e:
            return format_error(e)
