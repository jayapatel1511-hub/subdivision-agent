"""
Subdivision Agent — FastAPI Web Backend.

Serves the static frontend (web/) and a JSON API that drives the subdivision
engine in a background thread. No external services, no auth — single-user
local tool.

Endpoints:
  POST /api/generate          — run the engine in a thread, returns job_id
  GET  /api/status/{job_id}   — poll job status + results
  POST /api/export             — export a layout (geojson / dxf / qgis)
  GET  /api/scenarios          — list saved scenarios
  POST /api/scenarios/save     — save a scenario
  GET  /api/scenarios/{name}   — load a scenario
  GET  /api/options             — zones, servicing types, road patterns
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from shapely.geometry import shape as shp_shape

from models import (
    Parcel, AccessPoint, LayoutRules, RoadPattern,
)
from constraints import ConstraintEngine
from generator import LayoutGenerator
from checker import LotChecker, LayoutScorer
from export import export_geojson, export_dxf
from export_qgis import export_qgis
from intake_geojson import load_geojson_parcel
from serialize import layout_result_to_web, parcel_to_dict

# ── App setup ───────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).resolve().parent
WEB_DIR = BASE_DIR / "web"
SCENARIOS_DIR = BASE_DIR / "scenarios"
SCENARIOS_DIR.mkdir(exist_ok=True)

app = FastAPI(title="Subdivision Agent", version="1.0.0")

# In-memory job store: job_id -> {status, results(dicts), objects, parcel, error}
jobs: dict = {}
jobs_lock = threading.Lock()

# Cached constraint engine (thread-safe after load())
_engine: ConstraintEngine | None = None
_engine_lock = threading.Lock()


def _get_engine() -> ConstraintEngine:
    global _engine
    with _engine_lock:
        if _engine is None:
            _engine = ConstraintEngine("hrm")
            _engine.load()
        return _engine


# ── Helpers ─────────────────────────────────────────────────────────────────

# Human labels for the road patterns (frontend dropdowns / tables)
PATTERN_LABELS = {
    "existing_road": "Existing Road",
    "single_road": "Single Road",
    "cul_de_sac": "Cul-de-sac",
    "loop_road": "Loop Road",
    "t_road": "T-Road",
    "spine_branch": "Spine + Branch",
    "cluster": "Cluster",
    "large_lot_rural": "Large Lot Rural",
}


def _normalize_parcel_geojson(geojson: dict, zone: str, servicing: str) -> dict:
    """Coerce arbitrary GeoJSON input into a FeatureCollection the engine accepts.

    Accepts FeatureCollection, single Feature, or bare Polygon/MultiPolygon
    geometry. Ensures the first polygon feature carries zone_code and
    servicing_type properties (load_geojson_parcel requires them). Preserves any
    access-point / constraint features already present.
    """
    if not isinstance(geojson, dict):
        raise ValueError("parcel_geojson must be an object")

    gtype = geojson.get("type")
    if gtype == "FeatureCollection":
        features = list(geojson.get("features", []))
    elif gtype == "Feature":
        features = [geojson]
    elif gtype in ("Polygon", "MultiPolygon"):
        features = [{"type": "Feature", "geometry": geojson, "properties": {}}]
    else:
        raise ValueError(f"Unsupported GeoJSON type: {gtype!r}")

    parcel_found = False
    for feat in features:
        if not isinstance(feat, dict):
            continue
        geom = feat.get("geometry") or {}
        if geom.get("type") in ("Polygon", "MultiPolygon") and not parcel_found:
            props = feat.setdefault("properties", {}) or {}
            props.setdefault("zone_code", zone)
            props.setdefault("servicing_type", servicing)
            parcel_found = True

    if not parcel_found:
        raise ValueError("No Polygon/MultiPolygon feature found in parcel_geojson")

    return {"type": "FeatureCollection", "features": features}


def _load_parcel_from_geojson(geojson: dict, zone: str, servicing: str) -> Parcel:
    """Write the parcel GeoJSON to a temp file and run the intake pipeline."""
    normalized = _normalize_parcel_geojson(geojson, zone, servicing)
    fd, tmp_path = tempfile.mkstemp(suffix=".geojson")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(normalized, f)
        parcel = load_geojson_parcel(tmp_path)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
    # Stamp zone/servicing from the request if the file didn't carry them
    parcel.zone_code = parcel.zone_code or zone
    return parcel


# ── Generate ────────────────────────────────────────────────────────────────

@app.post("/api/generate")
async def generate(params: dict):
    """Kick off a layout generation job. Returns {job_id}.

    Body: { parcel_geojson: {...}, zone: "R-2", servicing: "serviced",
            patterns: ["single_road", ...], road_length: null }
    """
    parcel_geojson = params.get("parcel_geojson")
    if not isinstance(parcel_geojson, dict):
        raise HTTPException(400, "parcel_geojson is required and must be an object")

    zone = params.get("zone", "R-2")
    servicing = params.get("servicing", "serviced")
    patterns = params.get("patterns") or ["single_road"]
    if isinstance(patterns, str):
        patterns = [p.strip() for p in patterns.split(",") if p.strip()]
    road_length = params.get("road_length")
    if road_length in ("", "null", None):
        road_length = None
    road_length = float(road_length) if road_length is not None else None

    job_id = str(uuid.uuid4())
    with jobs_lock:
        jobs[job_id] = {"status": "running", "results": None,
                         "objects": None, "parcel": None, "error": None}

    def run_engine():
        try:
            parcel = _load_parcel_from_geojson(parcel_geojson, zone, servicing)

            engine = _get_engine()
            pc = engine.resolve(zone, servicing)
            rules = LayoutRules.from_constraint_engine(pc)

            # Validate requested patterns
            valid = []
            for p in patterns:
                try:
                    valid.append(RoadPattern(p))
                except ValueError:
                    pass  # skip unknown patterns
            if not valid:
                valid = [RoadPattern.SINGLE_ROAD]

            gen = LayoutGenerator(parcel, rules)
            results = []
            for p in valid:
                try:
                    results.append(gen.generate_layout(p, road_length=road_length))
                except Exception:
                    continue

            checker = LotChecker(rules, parcel.constraint_areas)
            scorer = LayoutScorer(rules)
            for r in results:
                checker.check_layout(r)
                scorer.score_layout(r)
            results.sort(key=lambda r: r.score.total_score, reverse=True)

            serialized = [layout_result_to_web(r, parcel, dst_crs=4326)
                          for r in results]

            with jobs_lock:
                jobs[job_id].update({
                    "status": "done",
                    "results": serialized,
                    "objects": results,
                    "parcel": parcel,
                    "error": None,
                })
        except Exception as e:  # noqa: BLE001
            with jobs_lock:
                jobs[job_id].update({"status": "error", "error": str(e)})

    thread = threading.Thread(target=run_engine, daemon=True)
    thread.start()
    return {"job_id": job_id}


# ── Status ───────────────────────────────────────────────────────────────────

@app.get("/api/status/{job_id}")
async def status(job_id: str):
    with jobs_lock:
        job = jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "Unknown job_id")
    # Return a snapshot (omit the live shapely objects)
    return {
        "status": job["status"],
        "results": job["results"],
        "error": job["error"],
    }


# ── Export ───────────────────────────────────────────────────────────────────

def _resolve_result(body: dict):
    """Resolve a LayoutResult (and Parcel) for export.

    Preferred path: {job_id, pattern} — use the stored engine objects.
    Fallback path: {result, parcel} — not supported (engine objects can't be
    losslessly reconstructed from the slim web dict); returns 400.
    """
    job_id = body.get("job_id")
    pattern = body.get("pattern")
    if job_id and pattern:
        with jobs_lock:
            job = jobs.get(job_id)
        if job is None:
            raise HTTPException(404, "Unknown job_id")
        if job.get("objects") is None:
            raise HTTPException(400, "Job has no results to export")
        for r in job["objects"]:
            if r.pattern.value == pattern:
                return r, job.get("parcel")
        raise HTTPException(404, f"Pattern {pattern!r} not found in job results")
    raise HTTPException(400, "Provide job_id and pattern to identify the layout")


@app.post("/api/export")
async def export_endpoint(body: dict):
    fmt = (body.get("format") or "geojson").lower()
    result, parcel = _resolve_result(body)

    if fmt == "geojson":
        gj = export_geojson(result)
        return JSONResponse(gj)

    if fmt == "dxf":
        fd, path = tempfile.mkstemp(suffix=".dxf")
        os.close(fd)
        export_dxf(result, path)
        return FileResponse(path, filename=f"{result.pattern.value}.dxf",
                             media_type="application/dxf")

    if fmt == "qgis":
        tmpdir = tempfile.mkdtemp(prefix="qgis_")
        try:
            export_qgis(result, tmpdir, parcel=parcel)
            zip_path = shutil.make_archive(tmpdir, "zip", tmpdir)
        finally:
            # remove the unpacked folder; keep the zip
            shutil.rmtree(tmpdir, ignore_errors=True)
        return FileResponse(zip_path, filename=f"{result.pattern.value}_qgis.zip",
                            media_type="application/zip")

    raise HTTPException(400, f"Unknown format: {fmt!r}")


# ── Scenarios ───────────────────────────────────────────────────────────────

def _safe_name(name: str) -> str:
    """Strip path separators / unsafe chars from a scenario name."""
    safe = "".join(c for c in name if c.isalnum() or c in "-_")
    if not safe:
        raise HTTPException(400, "Invalid scenario name")
    return safe[:80]


@app.get("/api/scenarios")
async def list_scenarios():
    out = []
    if SCENARIOS_DIR.exists():
        for d in sorted(SCENARIOS_DIR.iterdir()):
            if not d.is_dir():
                continue
            meta_path = d / "meta.json"
            meta = {}
            if meta_path.exists():
                try:
                    meta = json.loads(meta_path.read_text())
                except Exception:  # noqa: BLE001
                    meta = {}
            out.append({"name": d.name, "meta": meta})
    return {"scenarios": out}


@app.post("/api/scenarios/save")
async def save_scenario(body: dict):
    name = body.get("name")
    if not name:
        raise HTTPException(400, "name is required")
    safe = _safe_name(name)
    folder = SCENARIOS_DIR / safe
    folder.mkdir(parents=True, exist_ok=True)

    meta = body.get("meta") or {}
    (folder / "meta.json").write_text(json.dumps(meta, indent=2))

    if isinstance(body.get("parcel_geojson"), dict):
        (folder / "parcel.geojson").write_text(
            json.dumps(body["parcel_geojson"], indent=2))

    if isinstance(body.get("layouts"), (dict, list)):
        (folder / "layouts.json").write_text(
            json.dumps(body["layouts"], indent=2))

    return {"name": safe, "saved": True}


@app.get("/api/scenarios/{name}")
async def get_scenario(name: str):
    safe = _safe_name(name)
    folder = SCENARIOS_DIR / safe
    if not folder.is_dir():
        raise HTTPException(404, "Scenario not found")

    meta = {}
    meta_path = folder / "meta.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text())

    parcel_geojson = None
    parcel_path = folder / "parcel.geojson"
    if parcel_path.exists():
        parcel_geojson = json.loads(parcel_path.read_text())

    layouts = None
    layouts_path = folder / "layouts.json"
    if layouts_path.exists():
        layouts = json.loads(layouts_path.read_text())

    return {"name": safe, "meta": meta,
            "parcel_geojson": parcel_geojson, "layouts": layouts}


# ── Options ─────────────────────────────────────────────────────────────────

@app.get("/api/options")
async def options():
    engine = _get_engine()
    return {
        "zones": engine.list_zones(),
        "servicing_types": engine.list_servicing_types(),
        "road_patterns": [
            {"value": p.value, "label": PATTERN_LABELS.get(p.value, p.value)}
            for p in RoadPattern
        ],
    }


# ── Static frontend (mounted last so /api/* routes take precedence) ─────────

if WEB_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")