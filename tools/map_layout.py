"""
Map Layout tools for ArcGIS MCP Server.

Two layout patterns based on Indonesian plantation map conventions:

INFORMAL  (e.g. A3 landscape — working maps):
  ┌──────────────────────────────┬──────────────┐
  │                              │ TITLE BLOCK  │  title + subtitle + company
  │                              │──────────────│
  │      MAP FRAME (~74%)        │ NORTH ARROW  │
  │                              │──────────────│
  │         [SCALE BAR]          │  SCALE INFO  │  scale + projection
  │                              │──────────────│
  │                              │   LEGEND     │
  └──────────────────────────────┴──────────────┘
  Single neat line border.  No logo, no statistics table, no footer.

FORMAL  (e.g. A4 landscape — official submission maps):
  ╔══════════════════════════════════════════════╗ ← double neat line
  ║  STATISTICS TABLE (optional, left area top)  ║
  ║──────────────────────────────┬───────────────║
  ║                              │ COMPANY BLOCK ║  company name + location
  ║      MAP FRAME (~68%)        │ SCALE INFO    ║
  ║                              │ TITLE BLOCK   ║  prominent bold title
  ║                              │ LEGEND        ║
  ║──────────────────────────────│ INSET MAP     ║
  ║  [SCALE BAR]                 │  (locator)    ║
  ╠══════════════════════════════╧═══════════════╣
  ║ FOOTER: MAP REF · date created               ║
  ╚══════════════════════════════════════════════╝

Requires ArcGIS Pro 3.x (tested on 3.4).

ArcGIS Pro 3.x API notes (differs from 2.x):
  - project.createTextElement(lyt, arcpy.Point, "POINT", text, text_size, ...)
  - lyt.createMapSurroundElement(extent, surround_type_str, mf, si, name)
    surround_type_str: "NORTH_ARROW" | "SCALE_BAR" | "LEGEND"
  - project.createPredefinedGraphicElement(lyt, extent, "RECTANGLE", name=name)
  - project.deleteItem(layout)
  - listStyleItems style_class: "NORTH_ARROW", "SCALE_BAR", "LEGEND" (uppercase)
"""

from typing import Dict, List, Optional

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

VALID_PAPER_SIZES  = list(PAPER_SIZES.keys())
VALID_EXPORT_FORMATS = ["PDF", "PNG", "JPG", "TIFF"]


def register(mcp: FastMCP) -> None:
    """Register all map layout tools onto the FastMCP instance."""

    # ------------------------------------------------------------------ #
    # Input Models                                                         #
    # ------------------------------------------------------------------ #

    class CreateMapLayoutInput(BaseModel):
        """Input model for arcgis_create_map_layout."""
        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

        # ── Required ──────────────────────────────────────────────────────
        project_path: str = Field(
            ...,
            description="Full path to ArcGIS Pro project file (.aprx)",
        )
        map_name: str = Field(
            ...,
            description="Name of the map inside the project to display in the layout",
        )
        layout_name: str = Field(
            ...,
            description="Unique name for the new layout",
        )

        # ── Page setup ────────────────────────────────────────────────────
        paper_size: str = Field(
            default="A3",
            description=(
                f"Paper size. One of: {', '.join(VALID_PAPER_SIZES)}. "
                "Portrait inches: A4=8.27×11.69, A3=11.69×16.54, "
                "A2=16.54×23.39, A1=23.39×33.11, A0=33.11×46.81, "
                "Letter=8.5×11, Tabloid=11×17"
            ),
        )
        orientation: str = Field(
            default="landscape",
            description="'landscape' or 'portrait'",
        )
        layout_type: str = Field(
            default="formal",
            description=(
                "'informal': map frame ~74% width, right panel (title→north arrow→scale→legend), "
                "scale bar on map, single border — no logo, statistics, inset, or footer. "
                "'formal': map frame ~68% width, optional statistics table above map, "
                "right panel (company→scale→title→legend→inset map), scale bar below map, "
                "full-width footer, double border."
            ),
        )

        # ── Title block ───────────────────────────────────────────────────
        title: Optional[str] = Field(
            default=None,
            description="Main map title, e.g. 'PETA KAWASAN HUTAN'. Defaults to map_name.",
        )
        subtitle: Optional[str] = Field(
            default=None,
            description="Secondary title line (area name, permit number, year, etc.).",
        )
        company_name: Optional[str] = Field(
            default=None,
            description="Company / organisation name shown in the title block.",
        )

        # ── Formal-only extras ────────────────────────────────────────────
        company_info: Optional[Dict[str, str]] = Field(
            default=None,
            description=(
                "Company location dict for formal panel. "
                'Keys: "kecamatan", "kabupaten", "provinsi". '
                'E.g. {"kecamatan": "Kutai Barat", "kabupaten": "Kutai Kartanegara", '
                '"provinsi": "Kalimantan Timur"}'
            ),
        )
        show_statistics_table: bool = Field(
            default=False,
            description=(
                "Formal only. Add a summary statistics table above the map frame "
                "(e.g. road classification totals, area breakdown)."
            ),
        )
        statistics_data: Optional[List[Dict[str, str]]] = Field(
            default=None,
            description=(
                "Rows for the statistics table. Each dict may have keys: "
                '"label", "value", "unit". '
                'E.g. [{"label": "Jalan Produksi", "value": "45.23", "unit": "km"}]'
            ),
        )
        show_inset_map: bool = Field(
            default=True,
            description=(
                "Formal only. Add a locator/inset map at the bottom of the right panel. "
                "Uses the first map named 'Locator', 'Overview', or 'Inset' in the project; "
                "falls back to the main map at a smaller scale."
            ),
        )
        map_ref: Optional[str] = Field(
            default=None,
            description="Map reference code for the formal footer strip, e.g. 'EBL-2024-001'.",
        )

        # ── Element visibility ────────────────────────────────────────────
        show_north_arrow: bool = Field(
            default=True,
            description="Add a north arrow (informal: in right panel; formal: above legend).",
        )
        show_legend: bool = Field(
            default=True,
            description="Add a legend element linked to the map frame.",
        )
        show_approval_block: bool = Field(
            default=False,
            description=(
                "Formal only. Add an approval/revision block at the bottom of the right panel "
                "with fields: Dibuat oleh, Diperiksa, Disetujui, Tanggal. "
                "Default False — not all formal maps require this block."
            ),
        )

        # ── Scale ─────────────────────────────────────────────────────────
        scale: Optional[float] = Field(
            default=None,
            description=(
                "Map scale denominator, e.g. 75000 for 1:75,000. "
                "Shown as text in the scale/projection info box. "
                "If omitted the map frame fits all layers."
            ),
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

        project_path: str = Field(..., description="Full path to .aprx file")
        layout_name:  str = Field(..., description="Name of the layout to export")
        output_path:  str = Field(..., description="Full output file path including extension")
        format: str = Field(
            default="PDF",
            description=f"Export format: {', '.join(VALID_EXPORT_FORMATS)} (default: PDF)",
        )
        resolution: int = Field(
            default=300,
            description="Output resolution in DPI (default: 300, max: 2400)",
            gt=0, le=2400,
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
        project_path: str = Field(..., description="Full path to .aprx file")

    class UpdateLayoutElementsInput(BaseModel):
        """Input model for arcgis_update_layout_elements."""
        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

        project_path: str = Field(..., description="Full path to .aprx file")
        layout_name:  str = Field(..., description="Name of the layout to update")
        title: Optional[str] = Field(
            default=None,
            description=(
                "New title text. Targets TEXT_ELEMENTs whose name contains 'title'; "
                "falls back to the first text element if only one exists."
            ),
        )
        scale: Optional[float] = Field(
            default=None,
            description="New scale denominator for the first map frame, e.g. 25000",
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

        Two layout patterns:

        INFORMAL — right-panel layout (working maps):
          map frame left ~74%, right panel top-to-bottom:
          title/subtitle/company → north arrow → scale+projection → legend.
          Scale bar at bottom-left of map frame. Single neat line border.

        FORMAL — structured layout (official/submission maps):
          optional statistics table above map frame, map frame left ~68%,
          right panel top-to-bottom: company block → scale+projection →
          title → legend → inset map.
          Scale bar strip below map frame. Full-width footer (MAP REF + date).
          Double neat line border.

        North arrow, scale bar, and legend use style items from the project's
        ArcGIS 2D style. Elements that cannot be added are skipped silently;
        the returned JSON lists what was actually created.

        Args:
            params: See CreateMapLayoutInput for all fields.

        Returns:
            str: JSON with success, layout_name, page dimensions, map_frame bounds,
                 right_panel bounds, elements_added list

        Error responses:
            - "Validation error: Layout '...' already exists" — name taken
            - "Validation error: Map '...' not found" — map missing in project
        """
        try:
            project_path = validate_path(params.project_path)

            # Snapshot all params before entering thread
            map_name           = params.map_name
            layout_name        = params.layout_name
            paper_size         = params.paper_size
            orientation        = params.orientation
            layout_type        = params.layout_type
            title_str          = params.title or params.map_name
            subtitle_str       = params.subtitle or ""
            company_str        = params.company_name or ""
            company_info       = params.company_info or {}
            show_stats         = params.show_statistics_table
            stats_data         = params.statistics_data or []
            show_inset         = params.show_inset_map
            map_ref            = params.map_ref or ""
            show_north_arrow   = params.show_north_arrow
            show_legend        = params.show_legend
            show_approval      = params.show_approval_block
            scale              = params.scale

            def _create():
                import arcpy
                from datetime import date

                project = arcpy.mp.ArcGISProject(project_path)

                # ── Validate uniqueness ─────────────────────────────────
                if layout_name in [lyt.name for lyt in project.listLayouts()]:
                    raise ValueError(
                        f"Layout '{layout_name}' already exists in project. "
                        "Choose a different name or delete the existing layout first."
                    )

                # ── Page dimensions ─────────────────────────────────────
                pw, ph = PAPER_SIZES[paper_size]
                if orientation == "landscape":
                    pw, ph = ph, pw
                lyt = project.createLayout(pw, ph, "INCH", layout_name)

                # ── Target map ──────────────────────────────────────────
                all_maps = project.listMaps()
                matches  = [m for m in all_maps if m.name == map_name]
                if not matches:
                    raise ValueError(
                        f"Map '{map_name}' not found in project. "
                        f"Available: {[m.name for m in all_maps]}"
                    )
                m = matches[0]

                elements_added = []

                # ── Shared helpers ──────────────────────────────────────
                def _si(cats, query=""):
                    """First StyleItem matching any category from ArcGIS 2D style."""
                    for cat in cats:
                        try:
                            items = project.listStyleItems("ArcGIS 2D", cat, query)
                            if items:
                                return items[0]
                        except Exception:
                            pass
                    return None

                def _text(name, x0, y0, x1, y1, txt, size=8.0, bold=False, italic=False):
                    try:
                        _fs = ("Bold Italic" if bold and italic
                               else "Bold" if bold
                               else "Italic" if italic
                               else "Regular")
                        project.createTextElement(
                            lyt,
                            arcpy.Point((x0 + x1) / 2, (y0 + y1) / 2),
                            "POINT", txt,
                            text_size=size, font_family_name="Arial",
                            font_style_name=_fs, name=name,
                        )
                        elements_added.append(name)
                        return True
                    except Exception:
                        return False

                def _surround(name, x0, y0, x1, y1, si, surround_type, frame=None):
                    if si is None:
                        return False
                    try:
                        lyt.createMapSurroundElement(
                            arcpy.Extent(x0, y0, x1, y1),
                            surround_type, frame or mf, si, name,
                        )
                        elements_added.append(name)
                        return True
                    except Exception:
                        return False

                def _map_frame(name, x0, y0, x1, y1, target_map, cam_scale=None):
                    frame = lyt.createMapFrame(
                        arcpy.Extent(x0, y0, x1, y1), target_map, name
                    )
                    elements_added.append(name)
                    if cam_scale is not None:
                        try:
                            frame.camera.scale = cam_scale
                        except Exception:
                            pass
                    return frame

                # ── Layout-specific geometry ────────────────────────────
                if layout_type == "informal":
                    mf = _build_informal(
                        arcpy, lyt, m, pw, ph,
                        elements_added, _si, _text, _surround, _map_frame,
                        title_str, subtitle_str, company_str,
                        scale, show_north_arrow, show_legend,
                    )
                else:
                    mf = _build_formal(
                        arcpy, lyt, m, pw, ph,
                        elements_added, _si, _text, _surround, _map_frame,
                        project, all_maps,
                        title_str, subtitle_str, company_str,
                        company_info, show_stats, stats_data,
                        show_inset, map_ref, show_north_arrow, show_legend,
                        show_approval, scale,
                    )

                project.save()

                # ── Return summary ──────────────────────────────────────
                mf_elems = lyt.listElements("MAPFRAME_ELEMENT")
                mf_main  = mf_elems[0] if mf_elems else None
                return {
                    "layout_name": lyt.name,
                    "page_width":  round(lyt.pageWidth, 3),
                    "page_height": round(lyt.pageHeight, 3),
                    "page_units":  lyt.pageUnits,
                    "paper_size":  paper_size,
                    "orientation": orientation,
                    "layout_type": layout_type,
                    "elements_added": elements_added,
                }

            # ── Informal sub-builder ────────────────────────────────────
            def _build_informal(
                arcpy, lyt, m, pw, ph,
                elements_added, _si, _text, _surround, _map_frame,
                title_str, subtitle_str, company_str,
                scale, show_north_arrow, show_legend,
            ):
                margin     = 0.12
                panel_sep  = 0.06
                panel_frac = 0.255

                usable_w = pw - 2 * margin
                usable_h = ph - 2 * margin
                panel_w  = usable_w * panel_frac
                mf_w     = usable_w - panel_w - panel_sep

                mf_x0, mf_y0 = margin, margin
                mf_x1, mf_y1 = margin + mf_w, ph - margin
                px0 = mf_x1 + panel_sep
                px1 = pw - margin
                py0, py1, ph_ = margin, ph - margin, ph - margin - margin

                mf = _map_frame("Main Map Frame", mf_x0, mf_y0, mf_x1, mf_y1, m, scale)

                # ── Panel section heights (bottom → top) ────────────────
                gap = 0.05
                legend_h     = ph_ * 0.36
                scale_info_h = ph_ * 0.10
                na_h         = ph_ * 0.12
                title_h      = ph_ - legend_h - scale_info_h - na_h - gap * 4

                cur_bot = py1  # walk down from top

                # Title block (top of panel)
                _text("Title",   px0, cur_bot - title_h, px1, cur_bot,
                      title_str, size=12.0, bold=True)
                cur_y = cur_bot - title_h

                if subtitle_str:
                    sub_h = min(0.38, title_h * 0.30)
                    _text("Subtitle", px0, cur_y - sub_h, px1, cur_y, subtitle_str, size=8.5)
                    cur_y -= sub_h

                if company_str:
                    comp_h = min(0.38, max(0.18, cur_y - py0 - legend_h - scale_info_h - na_h - gap * 3))
                    _text("Company Name", px0, cur_y - comp_h, px1, cur_y,
                          company_str, size=8.5, bold=True)

                cur_bot -= (title_h + gap)

                # North arrow
                if show_north_arrow:
                    na_si   = _si(["NORTH_ARROW"], "ArcGIS North 1") \
                              or _si(["NORTH_ARROW"])
                    na_size = min(na_h * 0.78, (px1 - px0) * 0.50)
                    na_cx   = (px0 + px1) / 2
                    na_cy   = cur_bot - na_h / 2
                    _surround("North Arrow",
                              na_cx - na_size / 2, na_cy - na_size / 2,
                              na_cx + na_size / 2, na_cy + na_size / 2,
                              na_si, "NORTH_ARROW")
                cur_bot -= (na_h + gap)

                # Scale + projection info
                denom = int(scale) if scale else None
                proj  = (([f"Skala  1:{denom:,}"] if denom else []) +
                         ["Proyeksi : TM", "Spheroid : WGS 1984", "Datum    : WGS 1984"])
                _text("Scale and Projection Info",
                      px0, cur_bot - scale_info_h, px1, cur_bot,
                      "\n".join(proj), size=6.5)
                cur_bot -= (scale_info_h + gap)

                # Legend
                if show_legend:
                    _surround("Legend", px0, py0, px1, cur_bot,
                              _si(["LEGEND"]), "LEGEND")

                # Scale bar bottom-left of map
                sb_si = (_si(["SCALE_BAR"], "Alternating Scale Bar 1")
                         or _si(["SCALE_BAR"]))
                if sb_si:
                    sb_pad = 0.10
                    sb_w   = min(2.5, mf_w * 0.26)
                    _surround("Scale Bar",
                              mf_x0 + sb_pad, mf_y0 + sb_pad,
                              mf_x0 + sb_pad + sb_w, mf_y0 + sb_pad + 0.28,
                              sb_si, "SCALE_BAR")

                # Single neat line
                try:
                    project.createPredefinedGraphicElement(
                        lyt,
                        arcpy.Extent(margin * 0.5, margin * 0.5,
                                     pw - margin * 0.5, ph - margin * 0.5),
                        "RECTANGLE", name="Neat Line",
                    )
                    elements_added.append("Neat Line")
                except Exception:
                    pass

                return mf

            # ── Formal sub-builder ──────────────────────────────────────
            def _build_formal(
                arcpy, lyt, m, pw, ph,
                elements_added, _si, _text, _surround, _map_frame,
                project, all_maps,
                title_str, subtitle_str, company_str,
                company_info, show_stats, stats_data,
                show_inset, map_ref, show_north_arrow, show_legend,
                show_approval, scale,
            ):
                from datetime import date

                margin     = 0.12
                panel_sep  = 0.06
                panel_frac = 0.30      # right panel = 30% of usable
                footer_h   = 0.32
                footer_gap = 0.05
                sb_strip_h = 0.45      # scale bar strip below map frame
                sb_gap     = 0.05
                stats_h    = 0.72 if show_stats else 0.0
                stats_gap  = 0.05 if show_stats else 0.0

                usable_w = pw - 2 * margin
                usable_h = ph - 2 * margin

                panel_w  = usable_w * panel_frac
                left_w   = usable_w - panel_w - panel_sep

                # Vertical zones (bottom → top)
                footer_y0 = margin
                footer_y1 = margin + footer_h
                content_y0 = footer_y1 + footer_gap
                content_y1 = ph - margin

                # Left area (map + stats + scale bar)
                la_x0 = margin
                la_x1 = margin + left_w
                la_y0 = content_y0
                la_y1 = content_y1

                # Scale bar strip at bottom of left area
                sb_y0 = la_y0
                sb_y1 = la_y0 + sb_strip_h

                # Statistics table above scale bar (optional)
                stats_y0 = sb_y1 + sb_gap if show_stats else 0
                stats_y1 = stats_y0 + stats_h if show_stats else 0

                # Map frame above stats (or above scale bar if no stats)
                mf_y0 = (stats_y1 + stats_gap) if show_stats else (sb_y1 + sb_gap)
                mf_y1 = la_y1

                # Right panel
                px0 = la_x1 + panel_sep
                px1 = pw - margin
                rp_y0 = content_y0
                rp_y1 = content_y1
                rp_h  = rp_y1 - rp_y0

                # ── Map Frame ───────────────────────────────────────────
                mf = _map_frame("Main Map Frame", la_x0, mf_y0, la_x1, mf_y1, m, scale)

                # ── Scale bar strip ─────────────────────────────────────
                sb_si = (_si(["SCALE_BAR"], "Alternating Scale Bar 1")
                         or _si(["SCALE_BAR"]))
                if sb_si:
                    sb_pad = 0.10
                    sb_w   = min(2.8, left_w * 0.40)
                    _surround("Scale Bar",
                              la_x0 + sb_pad, sb_y0 + 0.08,
                              la_x0 + sb_pad + sb_w, sb_y0 + 0.08 + 0.28,
                              sb_si, "SCALE_BAR")

                # ── Statistics table (optional) ─────────────────────────
                if show_stats:
                    rows   = stats_data or []
                    header = f"{'Deskripsi':<28} {'Nilai':>10}  {'Satuan':<8}"
                    sep    = "─" * 50
                    lines  = [header, sep]
                    for row in rows:
                        lbl   = row.get("label", "")[:28]
                        val   = row.get("value", "")
                        unit  = row.get("unit", "")
                        lines.append(f"{lbl:<28} {val:>10}  {unit:<8}")
                    lines.append(sep)
                    _text("Statistics Table",
                          la_x0, stats_y0, la_x1, stats_y1,
                          "\n".join(lines), size=7.0)

                # ── Right panel sections (top → bottom) ─────────────────
                gap        = 0.05
                approval_h = rp_h * 0.12 if show_approval else 0.0
                sec  = {
                    "company":  0.20,
                    "scale":    0.12,
                    "title":    0.17,
                    "legend":   0.30,
                    "inset":    None,   # fills remaining
                }
                # Calculate heights
                fixed_h = sum(v for v in sec.values() if v) * rp_h
                n_gaps  = (len(sec) - 1 + (1 if show_approval else 0)) * gap
                inset_h = max(0.3, rp_h - fixed_h - n_gaps - approval_h)

                # Y positions (walk from top)
                cy = rp_y1

                # Company block
                comp_h  = sec["company"] * rp_h
                co_y0, co_y1 = cy - comp_h, cy
                cy -= (comp_h + gap)

                # Scale / projection info
                si_h    = sec["scale"] * rp_h
                si_y0, si_y1 = cy - si_h, cy
                cy -= (si_h + gap)

                # Title block
                ti_h    = sec["title"] * rp_h
                ti_y0, ti_y1 = cy - ti_h, cy
                cy -= (ti_h + gap)

                # Legend
                leg_h   = sec["legend"] * rp_h
                leg_y0, leg_y1 = cy - leg_h, cy
                cy -= (leg_h + gap)

                # Approval block at very bottom (optional)
                approval_y0 = rp_y0
                approval_y1 = rp_y0 + approval_h

                # Inset map fills the rest above approval block
                ins_y0 = approval_y1 + (gap if show_approval else 0)
                ins_y1 = cy

                # ── Company block ───────────────────────────────────────
                comp_lines = []
                if company_str:
                    comp_lines.append(company_str)
                if company_info:
                    for key in ("kecamatan", "kabupaten", "provinsi"):
                        if company_info.get(key):
                            comp_lines.append(company_info[key])
                if comp_lines:
                    _text("Company Block", px0, co_y0, px1, co_y1,
                          "\n".join(comp_lines), size=8.0, bold=bool(company_str))

                # ── Scale + projection info ─────────────────────────────
                denom = int(scale) if scale else None
                proj  = (([f"Skala  1:{denom:,}"] if denom else []) +
                         ["Proyeksi : Transverse Mercator",
                          "Spheroid : WGS 1984",
                          "Datum    : WGS 1984"])
                _text("Scale and Projection Info", px0, si_y0, px1, si_y1,
                      "\n".join(proj), size=6.5)

                # ── Title block ─────────────────────────────────────────
                cur_t = ti_y1
                t_h   = min(0.65, ti_h * 0.50)
                _text("Title", px0, cur_t - t_h, px1, cur_t,
                      title_str, size=13.0, bold=True)
                cur_t -= (t_h + 0.03)
                if subtitle_str and cur_t > ti_y0 + 0.15:
                    sub_h = min(0.35, cur_t - ti_y0)
                    _text("Subtitle", px0, cur_t - sub_h, px1, cur_t,
                          subtitle_str, size=8.5)

                # ── Legend ──────────────────────────────────────────────
                if show_legend:
                    # Optional north arrow above legend if space allows
                    if show_north_arrow and leg_h > 1.5:
                        na_si   = (_si(["NORTH_ARROW"], "ArcGIS North 1")
                                   or _si(["NORTH_ARROW"]))
                        na_size = min(0.70, (px1 - px0) * 0.30)
                        na_cx   = (px0 + px1) / 2
                        na_y1_  = leg_y1
                        _surround("North Arrow",
                                  na_cx - na_size / 2, na_y1_ - na_size,
                                  na_cx + na_size / 2, na_y1_,
                                  na_si, "NORTH_ARROW")
                        leg_y1 -= (na_size + 0.04)

                    _surround("Legend", px0, leg_y0, px1, leg_y1,
                              _si(["LEGEND"]), "LEGEND")

                # ── Inset / locator map ─────────────────────────────────
                if show_inset and ins_y1 > ins_y0 + 0.3:
                    # Find overview map (or fall back to same map)
                    locator_names = {"locator", "overview", "inset",
                                     "indonesia", "kalimantan"}
                    locator_map = next(
                        (mm for mm in all_maps
                         if mm.name.lower() in locator_names),
                        m,    # fall back: same map, smaller scale
                    )
                    inset_frame = _map_frame(
                        "Inset Map", px0, ins_y0, px1, ins_y1, locator_map
                    )
                    # Zoom out significantly if using the same map
                    if locator_map is m and scale:
                        try:
                            inset_frame.camera.scale = scale * 50
                        except Exception:
                            pass

                # ── Approval block (optional, bottom of right panel) ────
                if show_approval and approval_h > 0:
                    approval_text = (
                        "Dibuat oleh  : ________________\n"
                        "Diperiksa    : ________________\n"
                        "Disetujui    : ________________\n"
                        "Tanggal      : ________________"
                    )
                    _text("Approval Block", px0, approval_y0, px1, approval_y1,
                          approval_text, size=6.5)

                # ── Footer strip (full page width) ──────────────────────
                today    = date.today().strftime("%d %B %Y")
                ref_part = f"MAP REF: {map_ref}  |  " if map_ref else ""
                _text("Footer", margin, footer_y0, pw - margin, footer_y1,
                      f"{ref_part}Dibuat: {today}", size=6.5, italic=True)

                # ── Double neat line ────────────────────────────────────
                for name, off in [("Neat Line Outer", 0.05), ("Neat Line Inner", 0.13)]:
                    try:
                        project.createPredefinedGraphicElement(
                            lyt,
                            arcpy.Extent(off, off, pw - off, ph - off),
                            "RECTANGLE", name=name,
                        )
                        elements_added.append(name)
                    except Exception:
                        pass

                return mf

            # ── Run in thread pool ──────────────────────────────────────
            data = await run_arcpy(_create)
            return tool_result(
                True,
                f"Layout '{layout_name}' created ({paper_size} {orientation}, {layout_type})",
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

        Args:
            params (ExportMapLayoutInput):
                - project_path (str): Path to .aprx file
                - layout_name (str): Layout to export
                - output_path (str): Destination file path (with extension)
                - format (str): PDF/PNG/JPG/TIFF (default: PDF)
                - resolution (int): DPI (default: 300)

        Returns:
            str: JSON with success, output_path, format, resolution, layout_name
        """
        try:
            project_path = validate_path(params.project_path)
            layout_name  = params.layout_name
            output_path  = params.output_path.strip().replace("\\", "/")
            fmt          = params.format
            resolution   = params.resolution

            def _export():
                import arcpy
                project = arcpy.mp.ArcGISProject(project_path)
                layouts = [lyt for lyt in project.listLayouts() if lyt.name == layout_name]
                if not layouts:
                    raise ValueError(
                        f"Layout '{layout_name}' not found. "
                        f"Available: {[lyt.name for lyt in project.listLayouts()]}"
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
                {"output_path": out, "format": fmt,
                 "resolution": resolution, "layout_name": layout_name},
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

        Args:
            params (ListMapLayoutsInput):
                - project_path (str): Path to .aprx file

        Returns:
            str: JSON with project_path, layout_count, layouts list
                 (each: name, page_width, page_height, page_units,
                         element_count, elements)
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
                        "name":          lyt.name,
                        "page_width":    round(lyt.pageWidth, 3),
                        "page_height":   round(lyt.pageHeight, 3),
                        "page_units":    lyt.pageUnits,
                        "element_count": len(elems),
                        "elements":      [e.name for e in elems],
                    })
                return result

            layouts = await run_arcpy(_list)
            return success_json({
                "project_path": project_path,
                "layout_count": len(layouts),
                "layouts":      layouts,
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

        Title: targets TEXT_ELEMENTs whose name contains 'title' (case-insensitive);
               falls back to first text element if only one exists.
        Scale: sets camera.scale on the first MAPFRAME_ELEMENT.

        Args:
            params (UpdateLayoutElementsInput):
                - project_path (str): Path to .aprx file
                - layout_name (str): Layout to modify
                - title (Optional[str]): New title text
                - scale (Optional[float]): New scale denominator

        Returns:
            str: JSON with success, layout_name, changes list
        """
        try:
            project_path = validate_path(params.project_path)
            layout_name  = params.layout_name
            new_title    = params.title
            new_scale    = params.scale

            def _update():
                import arcpy
                project = arcpy.mp.ArcGISProject(project_path)
                layouts = [lyt for lyt in project.listLayouts() if lyt.name == layout_name]
                if not layouts:
                    raise ValueError(
                        f"Layout '{layout_name}' not found. "
                        f"Available: {[lyt.name for lyt in project.listLayouts()]}"
                    )
                lyt     = layouts[0]
                changes = []

                if new_title is not None:
                    text_elems  = lyt.listElements("TEXT_ELEMENT")
                    title_elems = [e for e in text_elems if "title" in e.name.lower()]
                    if title_elems:
                        for te in title_elems:
                            te.text = new_title
                        changes.append(f"title → '{new_title}'")
                    elif len(text_elems) == 1:
                        text_elems[0].text = new_title
                        changes.append(f"text element → '{new_title}'")
                    else:
                        changes.append(
                            f"title: no element named 'title' found "
                            f"(elements: {[e.name for e in text_elems]})"
                        )

                if new_scale is not None:
                    mf_elems = lyt.listElements("MAPFRAME_ELEMENT")
                    if mf_elems:
                        mf_elems[0].camera.scale = new_scale
                        changes.append(f"scale → 1:{int(new_scale):,}")
                    else:
                        changes.append("scale: no map frame element found")

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
