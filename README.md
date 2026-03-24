# ArcGIS MCP Server

MCP (Model Context Protocol) server yang mengekspos ArcGIS Pro geoprocessing via `arcpy` ke Claude dan LLM lainnya.

Dirancang untuk tim GIS perkebunan kelapa sawit yang menggunakan ArcGIS Pro 3.x.

---

## Status Instalasi

| Komponen | Status |
|---|---|
| ArcGIS Pro | 3.4.0 — `C:\Program Files\ArcGIS\Pro\` |
| Python Environment | arcgispro-py3 (Python 3.11.10) |
| arcpy | Tersedia |

---

## Struktur Project

```
arcgis-mcp/
├── server.py                   # Entry point — FastMCP server
├── tools/
│   ├── __init__.py
│   ├── data_io.py              # Describe, list, export, create GDB
│   ├── geoprocessing.py        # Clip, buffer, intersect, dissolve, dll
│   ├── terrain.py              # Slope, aspect, hillshade, hidrologi
│   └── raster_analysis.py     # Zonal stats, reclassify, extract, kalkulator
├── utils/
│   ├── __init__.py
│   └── helpers.py              # Shared utilities (run_arcpy, error handling)
├── requirements.txt
├── claude_desktop_config.json  # Contoh config untuk Claude Desktop
└── README.md
```

---

## Daftar Tools (30 tools)

### Data I/O
| Tool | Deskripsi |
|---|---|
| `arcgis_describe_data` | Deskripsi lengkap dataset: geometry, CRS, extent, fields |
| `arcgis_list_workspace` | List semua dataset dalam folder/GDB/GeoPackage |
| `arcgis_list_fields` | List semua field/kolom beserta tipe dan panjangnya |
| `arcgis_get_feature_count` | Hitung jumlah feature, opsional dengan filter WHERE |
| `arcgis_export_data` | Export feature class ke format lain (SHP/GDB/GPKG) |
| `arcgis_create_gdb` | Buat File Geodatabase baru |

### Geoprocessing Vector
| Tool | Deskripsi |
|---|---|
| `arcgis_clip` | Potong features menggunakan boundary polygon |
| `arcgis_buffer` | Buat buffer di sekeliling features |
| `arcgis_intersect` | Overlay intersect 2+ feature class |
| `arcgis_union` | Gabung semua geometry dari 2+ polygon |
| `arcgis_dissolve` | Merge polygon berdasarkan atribut + statistik |
| `arcgis_spatial_join` | Gabung atribut berdasarkan relasi spasial |
| `arcgis_project` | Reproject ke sistem koordinat lain (EPSG/WKID) |
| `arcgis_select_by_attribute` | Pilih dan export features berdasarkan SQL |
| `arcgis_erase` | Hapus area tertentu dari features (kebalikan clip) |
| `arcgis_repair_geometry` | Perbaiki geometry yang rusak/invalid |

### Terrain Analysis (Butuh Spatial Analyst)
| Tool | Deskripsi |
|---|---|
| `arcgis_slope` | Hitung kemiringan lereng dari DEM (derajat / persen) |
| `arcgis_aspect` | Hitung arah hadap lereng dari DEM |
| `arcgis_hillshade` | Buat hillshade/bayangan relief untuk visualisasi |
| `arcgis_contour` | Generate garis kontur dari DEM |
| `arcgis_fill_dem` | Isi sink di DEM untuk analisis hidrologi |
| `arcgis_flow_direction` | Hitung arah aliran air per sel |
| `arcgis_flow_accumulation` | Hitung akumulasi aliran (jumlah sel hulu) |
| `arcgis_watershed` | Delineasi DAS / catchment area |
| `arcgis_slope_classification` | Klasifikasi kemiringan untuk perencanaan kebun |

### Raster Analysis (Butuh Spatial Analyst)
| Tool | Deskripsi |
|---|---|
| `arcgis_zonal_statistics_as_table` | Statistik raster per zona (blok, afdeling) |
| `arcgis_reclassify` | Reklasifikasi nilai raster ke kelas baru |
| `arcgis_extract_by_mask` | Potong raster menggunakan mask polygon/raster |
| `arcgis_raster_calculator` | Kalkulasi map algebra (NDVI, conditional, diff) |
| `arcgis_raster_to_polygon` | Konversi raster terklasifikasi ke polygon |
| `arcgis_polygon_to_raster` | Konversi polygon ke raster |
| `arcgis_resample_raster` | Ubah resolusi/cell size raster |

---

## Instalasi

### 1. Install dependensi MCP ke arcgispro-py3

```bash
# Aktifkan environment arcgispro-py3
"C:/Program Files/ArcGIS/Pro/bin/Python/Scripts/conda.exe" activate arcgispro-py3

# Install mcp
"C:/Program Files/ArcGIS/Pro/bin/Python/envs/arcgispro-py3/python.exe" -m pip install mcp pydantic
```

### 2. Test server berjalan

```bash
"C:/Program Files/ArcGIS/Pro/bin/Python/envs/arcgispro-py3/python.exe" "D:/04 Claude/arcgis-mcp/server.py"
```

### 3. Konfigurasi Claude Desktop

Edit file `%APPDATA%\Claude\claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "arcgis": {
      "command": "C:/Program Files/ArcGIS/Pro/bin/Python/envs/arcgispro-py3/python.exe",
      "args": ["D:/04 Claude/arcgis-mcp/server.py"]
    }
  }
}
```

Restart Claude Desktop setelah mengubah config.

---

## Contoh Penggunaan

### Analisis terrain untuk perencanaan kebun

```
1. arcgis_slope (DEM → slope raster)
2. arcgis_slope_classification (slope → kelas kemiringan)
3. arcgis_raster_to_polygon (kelas → polygon)
4. arcgis_intersect ([blok_tanam, kelas_lereng] → overlay)
5. arcgis_dissolve (overlay → luas per kelas per blok)
```

### Buffer riparian dan erase dari plantable area

```
1. arcgis_buffer (sungai → buffer 30m)
2. arcgis_erase (blok_tanam, buffer → blok tanpa riparian)
3. arcgis_get_feature_count (verifikasi hasil)
```

### Zonal statistics slope per plot

```
1. arcgis_describe_data (cek CRS plot dan DEM sama)
2. arcgis_slope (DEM → slope raster)
3. arcgis_zonal_statistics_as_table (slope, plots → tabel statistik)
```

---

## Sistem Koordinat Indonesia yang Umum

| WKID | Nama | Digunakan di |
|---|---|---|
| 4326 | WGS 1984 | GPS, data umum |
| 32647 | WGS84 UTM Zone 47N | Sumatra Barat, sebagian Sumatra |
| 32648 | WGS84 UTM Zone 48N | Sumatra Tengah-Timur |
| 32649 | WGS84 UTM Zone 49N | Kalimantan Barat-Tengah |
| 32650 | WGS84 UTM Zone 50N | Kalimantan Timur-Utara |
| 32748 | WGS84 UTM Zone 48S | Sumatra bagian selatan |
| 32750 | WGS84 UTM Zone 50S | Kalimantan Timur bagian selatan |
| 23830 | DGN95/TM Zone 50N | Kadastral Indonesia |

---

## Catatan Penting

- Semua path harus menggunakan **forward slash** `/` atau **double backslash** `\\`
- Tool terrain dan raster membutuhkan lisensi **Spatial Analyst**
- Server berjalan sebagai **subprocess stdio** — satu koneksi per client
- arcpy bersifat **synchronous**; semua panggilan dijalankan di thread pool agar tidak memblokir event loop
- Untuk data besar, pastikan koneksi ArcGIS Pro tidak terputus selama eksekusi
