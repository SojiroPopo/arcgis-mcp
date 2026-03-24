#!/usr/bin/env python3
"""
Comprehensive test suite for ArcGIS MCP Server tools.

Tests all 32 tools by calling arcpy operations directly (not via MCP transport).
Designed to run under the arcgispro-py3 environment.

Usage:
    "C:/Program Files/ArcGIS/Pro/bin/Python/envs/arcgispro-py3/python.exe" test_all_tools.py

Output: PASS/FAIL per tool, summary at the end.
"""

import asyncio
import inspect
import os
import shutil
import sys
import tempfile
import traceback

# Ensure project root on path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ── Force UTF-8 output on Windows ──────────────────────────────────────────
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# ---------------------------------------------------------------------------
# Test infrastructure
# ---------------------------------------------------------------------------

RESULTS = []    # list of (tool_name, status, message)
TEMP_DIR = None
TEST_GDB = None
DEM_PATH = None       # synthetic DEM raster (.tif)
PLOTS_SHP = None      # input polygon shapefile
MASK_SHP = None       # erase / mask polygon shapefile
BOUNDARY_SHP = None   # clip boundary shapefile
RIVERS_SHP = None     # polyline shapefile
POINTS_SHP = None     # point shapefile
TEST_APRX = None      # .aprx project for map layout tests
TEST_MAP_NAME = None  # first map name found in TEST_APRX


def _pass(name):
    RESULTS.append((name, "PASS", ""))
    print(f"  [PASS] {name}")


def _fail(name, err):
    short = str(err)[:250].replace("\n", " ")
    RESULTS.append((name, "FAIL", short))
    print(f"  [FAIL] {name}: {short}")


# ---------------------------------------------------------------------------
# Setup – create minimal test datasets as shapefiles (real OS paths)
# ---------------------------------------------------------------------------

def setup_test_environment():
    """Create temp dir, shapefiles, DEM raster and output GDB."""
    global TEMP_DIR, TEST_GDB, DEM_PATH
    global PLOTS_SHP, MASK_SHP, BOUNDARY_SHP, RIVERS_SHP, POINTS_SHP

    import arcpy
    import numpy as np

    TEMP_DIR = tempfile.mkdtemp(prefix="arcgis_mcp_test_")
    TEST_GDB = os.path.join(TEMP_DIR, "out.gdb").replace("\\", "/")

    # Output geodatabase (for vector outputs)
    arcpy.management.CreateFileGDB(TEMP_DIR, "out.gdb")

    sr = arcpy.SpatialReference(32750)  # WGS84 UTM Zone 50S
    # Valid UTM 50S origin (Kalimantan Timur area)
    ox, oy = 500_000.0, 9_800_000.0

    def _shp(name):
        return os.path.join(TEMP_DIR, name).replace("\\", "/")

    # ── Plots (3 polygon features) ─────────────────────────────────────────
    PLOTS_SHP = _shp("plots.shp")
    arcpy.management.CreateFeatureclass(TEMP_DIR, "plots.shp", "POLYGON",
                                        spatial_reference=sr)
    arcpy.management.AddField(PLOTS_SHP, "BLOK", "TEXT", field_length=10)
    arcpy.management.AddField(PLOTS_SHP, "LUAS_HA", "DOUBLE")
    with arcpy.da.InsertCursor(PLOTS_SHP, ["SHAPE@", "BLOK", "LUAS_HA"]) as cur:
        for i, (dx, dy) in enumerate([(0, 0), (1000, 0), (0, 1000)]):
            pts = arcpy.Array([
                arcpy.Point(ox + dx,        oy + dy),
                arcpy.Point(ox + dx + 1000, oy + dy),
                arcpy.Point(ox + dx + 1000, oy + dy + 1000),
                arcpy.Point(ox + dx,        oy + dy + 1000),
                arcpy.Point(ox + dx,        oy + dy),
            ])
            cur.insertRow([arcpy.Polygon(pts, sr), f"A0{i+1}", 100.0])

    # ── Erase mask (overlaps corners of all 3 plots) ───────────────────────
    MASK_SHP = _shp("erase_mask.shp")
    arcpy.management.CreateFeatureclass(TEMP_DIR, "erase_mask.shp", "POLYGON",
                                        spatial_reference=sr)
    with arcpy.da.InsertCursor(MASK_SHP, ["SHAPE@"]) as cur:
        pts = arcpy.Array([
            arcpy.Point(ox + 500,  oy + 500),
            arcpy.Point(ox + 1500, oy + 500),
            arcpy.Point(ox + 1500, oy + 1500),
            arcpy.Point(ox + 500,  oy + 1500),
            arcpy.Point(ox + 500,  oy + 500),
        ])
        cur.insertRow([arcpy.Polygon(pts, sr)])

    # ── Clip boundary ──────────────────────────────────────────────────────
    BOUNDARY_SHP = _shp("boundary.shp")
    arcpy.management.CreateFeatureclass(TEMP_DIR, "boundary.shp", "POLYGON",
                                        spatial_reference=sr)
    with arcpy.da.InsertCursor(BOUNDARY_SHP, ["SHAPE@"]) as cur:
        pts = arcpy.Array([
            arcpy.Point(ox,        oy),
            arcpy.Point(ox + 1500, oy),
            arcpy.Point(ox + 1500, oy + 1500),
            arcpy.Point(ox,        oy + 1500),
            arcpy.Point(ox,        oy),
        ])
        cur.insertRow([arcpy.Polygon(pts, sr)])

    # ── Rivers (polyline) ──────────────────────────────────────────────────
    RIVERS_SHP = _shp("rivers.shp")
    arcpy.management.CreateFeatureclass(TEMP_DIR, "rivers.shp", "POLYLINE",
                                        spatial_reference=sr)
    arcpy.management.AddField(RIVERS_SHP, "NAMA", "TEXT", field_length=50)
    with arcpy.da.InsertCursor(RIVERS_SHP, ["SHAPE@", "NAMA"]) as cur:
        pts = arcpy.Array([arcpy.Point(ox, oy + 500), arcpy.Point(ox + 2000, oy + 500)])
        cur.insertRow([arcpy.Polyline(pts, sr), "Sungai_Test"])

    # ── Sample points ──────────────────────────────────────────────────────
    POINTS_SHP = _shp("points.shp")
    arcpy.management.CreateFeatureclass(TEMP_DIR, "points.shp", "POINT",
                                        spatial_reference=sr)
    arcpy.management.AddField(POINTS_SHP, "SAMPLE_ID", "LONG")
    with arcpy.da.InsertCursor(POINTS_SHP, ["SHAPE@", "SAMPLE_ID"]) as cur:
        for sid, (dx, dy) in enumerate([(500, 500), (1500, 500), (500, 1500)], 1):
            cur.insertRow([arcpy.PointGeometry(arcpy.Point(ox + dx, oy + dy), sr), sid])

    # ── Synthetic DEM (30x30 cells, 100 m resolution) ─────────────────────
    DEM_PATH = _shp("dem.tif")
    row_vals = np.linspace(100, 390, 30, dtype="float32")
    dem_array = np.tile(row_vals, (30, 1))   # shape (30, 30)
    ras = arcpy.NumPyArrayToRaster(dem_array, arcpy.Point(ox, oy), 100, 100, -9999)
    ras.save(DEM_PATH)
    arcpy.management.DefineProjection(DEM_PATH, sr)

    print(f"  Temp dir  : {TEMP_DIR}")
    print(f"  Plots SHP : {PLOTS_SHP}")
    print(f"  DEM raster: {DEM_PATH}")
    print(f"  Output GDB: {TEST_GDB}")


def teardown_test_environment():
    """Remove temp directory."""
    if TEMP_DIR and os.path.exists(TEMP_DIR):
        shutil.rmtree(TEMP_DIR, ignore_errors=True)


def setup_test_aprx():
    """Find an existing .aprx and copy it to TEMP_DIR for map layout tests.

    Searches common ArcGIS Pro project locations.  Sets TEST_APRX and
    TEST_MAP_NAME globals; leaves them None when no .aprx is found.
    """
    global TEST_APRX, TEST_MAP_NAME
    import arcpy

    user_docs = os.path.expanduser("~/Documents")
    search_dirs = [
        os.path.join(user_docs, "ArcGIS", "Projects"),
        os.path.join(os.path.expanduser("~"), "ArcGIS", "Projects"),
        "C:/Users/Public/Documents/ArcGIS/Projects",
    ]

    source_aprx = None
    for search_dir in search_dirs:
        if not os.path.isdir(search_dir):
            continue
        for entry in os.listdir(search_dir):
            candidate = os.path.join(search_dir, entry, entry + ".aprx")
            if os.path.isfile(candidate):
                source_aprx = candidate
                break
        if source_aprx:
            break

    if source_aprx is None:
        print("  [SKIP] No .aprx found – map layout tests will be skipped")
        return

    dest = os.path.join(TEMP_DIR, "test_project.aprx").replace("\\", "/")
    import shutil
    shutil.copy2(source_aprx, dest)
    TEST_APRX = dest

    # Discover the first map name so tests can reference it
    try:
        prj = arcpy.mp.ArcGISProject(TEST_APRX)
        maps = prj.listMaps()
        TEST_MAP_NAME = maps[0].name if maps else None
        print(f"  Test .aprx : {TEST_APRX}")
        print(f"  Test map   : {TEST_MAP_NAME}")
    except Exception as ex:
        print(f"  [WARN] Could not read map names from .aprx: {ex}")
        TEST_APRX = None


def _skip(name, reason="no .aprx available"):
    RESULTS.append((name, "SKIP", reason))
    print(f"  [SKIP] {name}: {reason}")


def gdb(name):
    """Output path inside the test GDB."""
    return (TEST_GDB + "/" + name).replace("\\", "/")


def tmp(name):
    """Output path in TEMP_DIR (for rasters / shapefiles)."""
    return os.path.join(TEMP_DIR, name).replace("\\", "/")


# ---------------------------------------------------------------------------
# Wrap MCP tools: Pydantic model → callable
# ---------------------------------------------------------------------------

def import_tools():
    """Register all tools on a FastMCP instance and return {name: caller}."""
    from mcp.server.fastmcp import FastMCP
    import tools.data_io as data_io_mod
    import tools.geoprocessing as geo_mod
    import tools.terrain as terrain_mod
    import tools.raster_analysis as raster_mod
    import tools.map_layout as map_layout_mod

    mcp = FastMCP(name="test_mcp")
    data_io_mod.register(mcp)
    geo_mod.register(mcp)
    terrain_mod.register(mcp)
    raster_mod.register(mcp)
    map_layout_mod.register(mcp)

    # Extract tool functions
    raw = {t.name: t.fn for t in mcp._tool_manager.list_tools()}

    def make_caller(fn):
        sig = inspect.signature(fn)
        param = list(sig.parameters.values())[0]
        model_cls = param.annotation
        async def call(data):
            return await fn(model_cls(**data))
        return call

    return {name: make_caller(fn) for name, fn in raw.items()}


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

async def run_tool(tools, name, params):
    """Run a tool and return the result string."""
    return await tools[name](params)


async def test_tool(tools, name, params, check_fn=None):
    """Run a single tool test. Returns True on pass."""
    try:
        result = await run_tool(tools, name, params)
        if check_fn:
            check_fn(result)
        else:
            assert '"success": true' in result, result[:300]
        _pass(name)
        return True
    except Exception as e:
        _fail(name, e)
        return False


# ---------------------------------------------------------------------------
# Test groups
# ---------------------------------------------------------------------------

async def test_data_io(tools):
    # These tools return raw JSON (success_json), not {"success": true, ...}
    await test_tool(tools, "arcgis_describe_data",
        {"dataset_path": PLOTS_SHP},
        check_fn=lambda r: None if ('"dataType"' in r and "Error" not in r[:30]) else (_ for _ in ()).throw(AssertionError(r[:200])))

    await test_tool(tools, "arcgis_list_workspace",
        {"workspace_path": TEMP_DIR, "data_type": "All"},
        check_fn=lambda r: None if ('"workspace"' in r and '"items"' in r) else (_ for _ in ()).throw(AssertionError(r[:200])))

    await test_tool(tools, "arcgis_list_fields",
        {"dataset_path": PLOTS_SHP},
        check_fn=lambda r: None if ('"fields"' in r and '"field_count"' in r) else (_ for _ in ()).throw(AssertionError(r[:200])))

    await test_tool(tools, "arcgis_get_feature_count",
        {"dataset_path": PLOTS_SHP},
        check_fn=lambda r: None if ('"count"' in r and "3" in r) else (_ for _ in ()).throw(AssertionError(r[:200])))

    await test_tool(tools, "arcgis_export_data",
        {"input_path": PLOTS_SHP,
         "output_path": gdb("plots_exported")})

    await test_tool(tools, "arcgis_create_gdb",
        {"folder_path": TEMP_DIR,
         "gdb_name": "extra_gdb"})


async def test_geoprocessing(tools):
    await test_tool(tools, "arcgis_clip",
        {"input_features": PLOTS_SHP,
         "clip_features": BOUNDARY_SHP,
         "output_path": gdb("clipped_plots")})

    await test_tool(tools, "arcgis_buffer",
        {"input_features": RIVERS_SHP,
         "output_path": gdb("river_buffer"),
         "distance": 30.0,
         "distance_unit": "Meters",
         "dissolve_option": "ALL"})

    await test_tool(tools, "arcgis_intersect",
        {"input_features": [PLOTS_SHP, BOUNDARY_SHP],
         "output_path": gdb("intersect_result"),
         "join_attributes": "ALL"})

    await test_tool(tools, "arcgis_union",
        {"input_features": [PLOTS_SHP, MASK_SHP],
         "output_path": gdb("union_result")})

    await test_tool(tools, "arcgis_dissolve",
        {"input_features": PLOTS_SHP,
         "output_path": gdb("dissolved_plots"),
         "dissolve_fields": ["BLOK"],
         "statistics_fields": ["LUAS_HA SUM"]})

    await test_tool(tools, "arcgis_spatial_join",
        {"target_features": POINTS_SHP,
         "join_features": PLOTS_SHP,
         "output_path": gdb("sj_result"),
         "join_operation": "JOIN_ONE_TO_ONE",
         "match_option": "INTERSECT"})

    await test_tool(tools, "arcgis_project",
        {"input_dataset": PLOTS_SHP,
         "output_dataset": gdb("plots_4326"),
         "out_crs": "4326"})

    await test_tool(tools, "arcgis_select_by_attribute",
        {"input_features": PLOTS_SHP,
         "output_path": gdb("selected_plots"),
         "where_clause": "LUAS_HA >= 100"})

    # arcgis_erase: workaround via Geometry.difference()
    await test_tool(tools, "arcgis_erase",
        {"input_features": PLOTS_SHP,
         "erase_features": MASK_SHP,
         "output_path": gdb("erased_plots")})

    await test_tool(tools, "arcgis_repair_geometry",
        {"input_features": PLOTS_SHP})


async def test_terrain(tools):
    await test_tool(tools, "arcgis_slope",
        {"dem_path": DEM_PATH,
         "output_path": tmp("slope.tif"),
         "output_measurement": "DEGREE"})

    await test_tool(tools, "arcgis_aspect",
        {"dem_path": DEM_PATH,
         "output_path": tmp("aspect.tif")})

    await test_tool(tools, "arcgis_hillshade",
        {"dem_path": DEM_PATH,
         "output_path": tmp("hillshade.tif")})

    await test_tool(tools, "arcgis_contour",
        {"dem_path": DEM_PATH,
         "output_path": gdb("contour_lines"),
         "contour_interval": 50.0})

    await test_tool(tools, "arcgis_fill_dem",
        {"dem_path": DEM_PATH,
         "output_path": tmp("fill.tif")})

    # flow direction needs filled DEM
    fill_path = tmp("fill.tif")
    flowdir_path = tmp("flowdir.tif")
    src = fill_path if os.path.exists(fill_path) else DEM_PATH
    await test_tool(tools, "arcgis_flow_direction",
        {"filled_dem_path": src,
         "output_path": flowdir_path})

    await test_tool(tools, "arcgis_flow_accumulation",
        {"flow_direction_path": flowdir_path if os.path.exists(flowdir_path) else DEM_PATH,
         "output_path": tmp("flowacc.tif")})

    await test_tool(tools, "arcgis_watershed",
        {"flow_direction_path": flowdir_path if os.path.exists(flowdir_path) else DEM_PATH,
         "pour_points_path": POINTS_SHP,
         "output_path": tmp("watershed.tif")})

    await test_tool(tools, "arcgis_slope_classification",
        {"dem_path": DEM_PATH,
         "output_path": tmp("slope_class.tif"),
         "classification_scheme": "PLANTATION"})


async def test_map_layout(tools):
    """Tests for map layout tools.  All tests are skipped when no .aprx is found."""
    TOOL_LIST = [
        "arcgis_list_map_layouts",
        "arcgis_create_map_layout",
        "arcgis_update_layout_elements",
        "arcgis_export_map_layout",
    ]

    if TEST_APRX is None or TEST_MAP_NAME is None:
        for name in TOOL_LIST:
            _skip(name)
        return

    # ── list_map_layouts (read-only, always safe) ──────────────────────
    await test_tool(
        tools,
        "arcgis_list_map_layouts",
        {"project_path": TEST_APRX},
        check_fn=lambda r: None
            if ('"layout_count"' in r and '"layouts"' in r and "Error" not in r[:20])
            else (_ for _ in ()).throw(AssertionError(r[:300])),
    )

    # ── create_map_layout – formal A3 landscape ────────────────────────
    layout_formal = "TestFormalLayout_MCP"
    await test_tool(
        tools,
        "arcgis_create_map_layout",
        {
            "project_path": TEST_APRX,
            "map_name": TEST_MAP_NAME,
            "layout_name": layout_formal,
            "paper_size": "A3",
            "orientation": "landscape",
            "layout_type": "formal",
            "title": "Test Formal Layout",
        },
        check_fn=lambda r: None
            if ('"success": true' in r and "Map Frame" in r)
            else (_ for _ in ()).throw(AssertionError(r[:300])),
    )

    # ── update_layout_elements – change title and scale ────────────────
    await test_tool(
        tools,
        "arcgis_update_layout_elements",
        {
            "project_path": TEST_APRX,
            "layout_name": layout_formal,
            "title": "Updated Title",
            "scale": 50000.0,
        },
        check_fn=lambda r: None
            if ('"success": true' in r and '"changes"' in r)
            else (_ for _ in ()).throw(AssertionError(r[:300])),
    )

    # ── export_map_layout – PDF ────────────────────────────────────────
    pdf_path = tmp("test_layout_export.pdf")
    await test_tool(
        tools,
        "arcgis_export_map_layout",
        {
            "project_path": TEST_APRX,
            "layout_name": layout_formal,
            "output_path": pdf_path,
            "format": "PDF",
            "resolution": 96,
        },
        check_fn=lambda r: None
            if ('"success": true' in r and os.path.exists(pdf_path))
            else (_ for _ in ()).throw(AssertionError(r[:300])),
    )


async def test_raster(tools):
    await test_tool(tools, "arcgis_zonal_statistics_as_table",
        {"zone_features": PLOTS_SHP,
         "zone_field": "BLOK",
         "value_raster": DEM_PATH,
         "output_table": gdb("zonal_stats")})

    await test_tool(tools, "arcgis_reclassify",
        {"input_raster": DEM_PATH,
         "output_path": tmp("reclassified.tif"),
         "reclass_field": "Value",
         "remap_table": ["100 200 1", "200 300 2", "300 400 3"],
         "remap_type": "RANGE"})

    await test_tool(tools, "arcgis_extract_by_mask",
        {"input_raster": DEM_PATH,
         "mask_path": BOUNDARY_SHP,
         "output_path": tmp("extracted.tif")})

    await test_tool(tools, "arcgis_raster_calculator",
        {"expression": f'Raster("{DEM_PATH}") * 0.001',
         "output_path": tmp("calc_result.tif")})

    # raster_to_polygon needs integer raster
    import arcpy
    int_path = tmp("int_dem.tif")
    if not os.path.exists(int_path):
        r = arcpy.sa.Int(arcpy.Raster(DEM_PATH))
        r.save(int_path)

    await test_tool(tools, "arcgis_raster_to_polygon",
        {"input_raster": int_path,
         "output_path": gdb("dem_poly"),
         "simplify": True,
         "raster_field": "Value"})

    await test_tool(tools, "arcgis_polygon_to_raster",
        {"input_features": PLOTS_SHP,
         "value_field": "LUAS_HA",
         "output_path": tmp("poly_to_ras.tif"),
         "cell_size": 100.0})

    await test_tool(tools, "arcgis_resample_raster",
        {"input_raster": DEM_PATH,
         "output_path": tmp("resampled_50m.tif"),
         "cell_size": 50.0,
         "resampling_type": "BILINEAR"})


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("ArcGIS MCP Tool Test Suite")
    print("=" * 60)

    # Verify arcpy
    try:
        import arcpy
        ver = arcpy.GetInstallInfo().get("Version", "unknown")
        print(f"\narcpy: ArcGIS Pro {ver}")
    except ImportError:
        print("\nERROR: arcpy not found. Run under arcgispro-py3.")
        sys.exit(1)

    # Spatial Analyst
    try:
        arcpy.CheckOutExtension("Spatial")
        print("Spatial Analyst: available")
    except Exception as ex:
        print(f"Spatial Analyst: NOT available ({ex})")
        print("  -> terrain/raster tools will FAIL")

    # Setup test data
    print("\n[Setup] Creating test datasets...")
    try:
        setup_test_environment()
    except Exception as e:
        print(f"FATAL setup error: {e}")
        traceback.print_exc()
        return 1

    print("\n[Setup] Locating .aprx for map layout tests...")
    setup_test_aprx()

    # Load tools
    print("\n[Import] Loading tool modules...")
    try:
        tools = import_tools()
        print(f"  {len(tools)} tools registered")
    except Exception as e:
        print(f"FATAL import error: {e}")
        traceback.print_exc()
        teardown_test_environment()
        return 1

    loop = asyncio.get_event_loop()

    print("\n[1/5] Data I/O Tools")
    loop.run_until_complete(test_data_io(tools))

    print("\n[2/5] Geoprocessing Tools")
    loop.run_until_complete(test_geoprocessing(tools))

    print("\n[3/5] Terrain Tools")
    loop.run_until_complete(test_terrain(tools))

    print("\n[4/5] Raster Analysis Tools")
    loop.run_until_complete(test_raster(tools))

    print("\n[5/5] Map Layout Tools")
    loop.run_until_complete(test_map_layout(tools))

    # Teardown
    print("\n[Teardown] Cleaning up...")
    teardown_test_environment()

    # Summary
    passed = [r for r in RESULTS if r[1] == "PASS"]
    failed = [r for r in RESULTS if r[1] == "FAIL"]
    skipped = [r for r in RESULTS if r[1] == "SKIP"]

    print("\n" + "=" * 60)
    print(
        f"RESULTS: {len(passed)} PASS / {len(failed)} FAIL / "
        f"{len(skipped)} SKIP / {len(RESULTS)} total"
    )
    print("=" * 60)

    if failed:
        print("\nFailed tools:")
        for name, _, msg in failed:
            print(f"  FAIL  {name}: {msg}")

    if skipped:
        print("\nSkipped tools:")
        for name, _, msg in skipped:
            print(f"  SKIP  {name}: {msg}")

    print("\nAll results:")
    for name, status, _ in RESULTS:
        mark = "OK" if status == "PASS" else ("--" if status == "SKIP" else "!!")
        print(f"  [{mark}] {name}")

    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
