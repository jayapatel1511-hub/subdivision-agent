"""
Tests for the FastAPI web backend (webapp.py).

Uses FastAPI's TestClient. Generation runs in a real background thread, so the
tests poll /api/status until the job is done (bounded retries).

The test parcel is a ~300×200 m rectangle expressed in EPSG:4326 (lat/lng) near
Halifax, NS — the same path a user takes when drawing in the Leaflet UI. The
intake pipeline reprojects it to the engine's working CRS (EPSG:2959), and the
serializer reprojects results back to 4326 for display.
"""

import time
import shutil

import pytest
from fastapi.testclient import TestClient

import webapp
from webapp import app, SCENARIOS_DIR


# ── Fixtures ────────────────────────────────────────────────────────────────

# ~300 m (E-W) × 200 m (N-S) rectangle near Halifax, NS in EPSG:4326.
# lng span 0.0038° (~300 m at lat 44.65), lat span 0.0018° (~200 m).
HALIFAX_PARCEL_4326 = {
    "type": "FeatureCollection",
    "features": [{
        "type": "Feature",
        "geometry": {
            "type": "Polygon",
            "coordinates": [[
                [-63.5750, 44.6490],
                [-63.5712, 44.6490],
                [-63.5712, 44.6508],
                [-63.5750, 44.6508],
                [-63.5750, 44.6490],
            ]],
        },
        "properties": {"zone_code": "R-2", "servicing_type": "serviced"},
    }],
}


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def job_id(client):
    """Run a generate job and yield its job_id once it's done."""
    res = client.post("/api/generate", json={
        "parcel_geojson": HALIFAX_PARCEL_4326,
        "zone": "R-2",
        "servicing": "serviced",
        "patterns": ["single_road"],
        "road_length": None,
    })
    assert res.status_code == 200, res.text
    jid = res.json()["job_id"]
    # Poll to completion
    for _ in range(80):
        s = client.get(f"/api/status/{jid}").json()
        if s["status"] in ("done", "error"):
            break
        time.sleep(0.1)
    yield jid


# ── Tests ────────────────────────────────────────────────────────────────────

def test_generate_returns_job_id(client):
    res = client.post("/api/generate", json={
        "parcel_geojson": HALIFAX_PARCEL_4326,
        "zone": "R-2",
        "servicing": "serviced",
        "patterns": ["single_road"],
        "road_length": None,
    })
    assert res.status_code == 200
    data = res.json()
    assert "job_id" in data
    assert isinstance(data["job_id"], str)


def test_status_eventually_done(client, job_id):
    s = client.get(f"/api/status/{job_id}").json()
    assert s["status"] == "done", f"job errored: {s.get('error')}"
    assert isinstance(s["results"], list)
    assert len(s["results"]) >= 1
    r = s["results"][0]
    # Core fields present
    assert "pattern" in r
    assert "score" in r
    assert "geojson" in r
    assert "total_lots" in r


def test_status_unknown_job_404(client):
    res = client.get("/api/status/does-not-exist")
    assert res.status_code == 404


def test_generate_missing_parcel_400(client):
    res = client.post("/api/generate", json={"zone": "R-2", "servicing": "serviced"})
    assert res.status_code == 400


def test_export_geojson(client, job_id):
    s = client.get(f"/api/status/{job_id}").json()
    pattern = s["results"][0]["pattern"]
    res = client.post("/api/export", json={
        "format": "geojson", "job_id": job_id, "pattern": pattern,
    })
    assert res.status_code == 200, res.text
    gj = res.json()
    assert gj["type"] == "FeatureCollection"
    assert isinstance(gj.get("features"), list)


def test_export_unknown_format_400(client, job_id):
    res = client.post("/api/export", json={
        "format": "weird", "job_id": job_id, "pattern": "single_road",
    })
    assert res.status_code == 400


def test_options(client):
    res = client.get("/api/options")
    assert res.status_code == 200
    data = res.json()
    assert "R-2" in data["zones"]
    assert "serviced" in data["servicing_types"]
    labels = {p["value"] for p in data["road_patterns"]}
    assert "single_road" in labels


def test_scenarios_list_empty_or_dict(client):
    res = client.get("/api/scenarios")
    assert res.status_code == 200
    data = res.json()
    assert "scenarios" in data
    assert isinstance(data["scenarios"], list)


def test_scenario_save_and_load_roundtrip(client):
    name = "test_roundtrip"
    folder = SCENARIOS_DIR / name
    try:
        res = client.post("/api/scenarios/save", json={
            "name": name,
            "meta": {"zone": "R-2", "servicing": "serviced"},
            "parcel_geojson": HALIFAX_PARCEL_4326,
            "layouts": [{"pattern": "single_road", "score": {"total_score": 50.0}}],
        })
        assert res.status_code == 200, res.text
        assert res.json()["saved"] is True

        # It shows up in the listing
        listing = client.get("/api/scenarios").json()["scenarios"]
        names = [s["name"] for s in listing]
        assert name in names

        # And loads back with the saved data
        loaded = client.get(f"/api/scenarios/{name}").json()
        assert loaded["name"] == name
        assert loaded["parcel_geojson"]["type"] == "FeatureCollection"
        assert loaded["meta"]["zone"] == "R-2"
        assert isinstance(loaded["layouts"], list)
    finally:
        if folder.exists():
            shutil.rmtree(folder, ignore_errors=True)


def test_scenario_get_unknown_404(client):
    res = client.get("/api/scenarios/definitely_not_there_xyz")
    assert res.status_code == 404


def test_index_html_served(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "Subdivision Agent" in res.text
    assert "leaflet" in res.text.lower()