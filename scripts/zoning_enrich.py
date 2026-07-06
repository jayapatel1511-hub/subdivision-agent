#!/usr/bin/env python3
"""Paginate HRM zoning FeatureServer and spatial-join fixture parcels to real zones."""
import json, os, time, urllib.request, urllib.parse
from shapely.geometry import shape, Point
import sys

REPO = "/Volumes/SSD/subdivision-agent"
QUERY_URL = "https://services2.arcgis.com/11XBiaBYA9Ep0yNJ/arcgis/rest/services/ZoningBoundaries/FeatureServer/0/query"

# Step 1: Paginate all features with geometry
all_features = []
offset = 0
page_size = 2000

while True:
    params = {
        "where": "1=1",
        "outFields": "ZONE,DESCRIPTION",
        "outSR": "4326",
        "f": "geojson",
        "resultOffset": str(offset),
        "resultRecordCount": str(page_size),
    }
    url = QUERY_URL + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "SubdivisionAgent/1.0 (research)"})
    with urllib.request.urlopen(req, timeout=60) as r:
        gj = json.loads(r.read())
    feats = gj.get("features", [])
    if not feats:
        break
    all_features.extend(feats)
    print(f"  Fetched {len(feats)} (total: {len(all_features)})")
    if len(feats) < page_size:
        break
    offset += page_size
    time.sleep(1.5)

print(f"\nTotal fetched: {len(all_features)} features")

# Save full zoning
os.makedirs(f"{REPO}/data/raw/zoning", exist_ok=True)
outpath = f"{REPO}/data/raw/zoning/hrm_zoning_full.geojson"
with open(outpath, "w") as f:
    json.dump({"type": "FeatureCollection", "features": all_features}, f)
print(f"Saved to {outpath} ({os.path.getsize(outpath)/(1024*1024):.1f} MB)")

# Check zone codes
zones = set()
for feat in all_features:
    z = feat.get("properties", {}).get("ZONE")
    if z:
        zones.add(str(z).strip())
print(f"Unique zone codes: {len(zones)}")

# Step 2: Spatial-join each fixture parcel to its zone
print("\n--- Spatial-joining fixture parcels ---")
zone_polys = []
for feat in all_features:
    geom = feat.get("geometry")
    zcode = feat.get("properties", {}).get("ZONE")
    if geom and zcode:
        try:
            poly = shape(geom)
            zone_polys.append((str(zcode).strip(), poly))
        except Exception:
            pass
print(f"Valid zone polygons: {len(zone_polys)}")

import glob
parcel_files = sorted(glob.glob(f"{REPO}/tests/fixtures/real/parcel_*.geojson"))
print(f"Fixture parcels: {len(parcel_files)}")

# Zone mapping: HRM FeatureServer codes → our constraint engine codes
# Our engine has: R-1, R-1a, R-2, R-2a, R-3, C-1, C-2, C-3, MU-1, MU-2, I-1, I-2
ZONE_MAP = {
    "R-1": "R-1", "R-1-0": "R-1", "R-1_82": "R-1",
    "R-1a": "R-1a", "R-1b": "R-1a", "R-1c": "R-1a", "R-1d": "R-1a", "R-1e": "R-1a",
    "R-2": "R-2", "R-2A": "R-2", "R-2P": "R-2", "R-2T": "R-2", "R-2TA": "R-2", "R-2b": "R-2a", "R-2AM": "R-2a",
    "R-3": "R-3", "R-3A": "R-3",
    "R-4": "R-3", "R-4A": "R-3", "R-4B": "R-3", "R-5": "R-3", "R-6": "R-3", "R-6A": "R-3", "R-7": "R-3", "R-8": "R-3",
    "C-1": "C-1", "C-1A": "C-1", "C-1B": "C-1",
    "C-2": "C-2", "C-2A": "C-2", "C-2B": "C-2", "C-2C": "C-2", "C-2D": "C-2",
    "C-3": "C-3", "C-4": "C-3", "C-5": "C-3",
    "MU-1": "MU-1", "MU-2": "MU-2", "MU": "MU-1", "RMU": "MU-1",
    "I-1": "I-1", "I-2": "I-2", "I-3": "I-2", "I-4": "I-2",
    # Bedford legacy zones → closest HRM equivalent
    "RSU": "R-1", "RTU": "R-2", "RTU_RTH": "R-2", "RTH": "R-2",
    "RMU": "MU-1", "RCDD": "R-3", "RR": "R-1", "RR-1": "R-1",
}

enriched = 0
zone_distribution = {}
for pf in parcel_files:
    with open(pf) as f:
        pgj = json.load(f)
    feat = pgj["features"][0] if pgj.get("features") else pgj
    geom = feat.get("geometry", pgj.get("geometry"))
    parcel_poly = shape(geom)
    centroid = parcel_poly.centroid

    found_zone = None
    for zcode, zpoly in zone_polys:
        if zpoly.contains(centroid):
            found_zone = zcode
            break

    if found_zone is None:
        for zcode, zpoly in zone_polys:
            if zpoly.intersects(parcel_poly):
                found_zone = zcode
                break

    old_zone = feat.get("properties", {}).get("zone_code", "NONE")
    if found_zone:
        mapped_zone = ZONE_MAP.get(found_zone, "R-1")
        feat["properties"]["zone_code"] = mapped_zone
        feat["properties"]["zone_code_raw"] = found_zone
        with open(pf, "w") as f:
            json.dump(pgj, f)
        enriched += 1
        zone_distribution[mapped_zone] = zone_distribution.get(mapped_zone, 0) + 1
        print(f"  {os.path.basename(pf)}: {old_zone} → {mapped_zone} (raw: {found_zone})")
    else:
        feat["properties"]["zone_code"] = "R-1"
        feat["properties"]["zone_code_raw"] = "NONE"
        with open(pf, "w") as f:
            json.dump(pgj, f)
        zone_distribution["R-1"] = zone_distribution.get("R-1", 0) + 1
        print(f"  {os.path.basename(pf)}: {old_zone} → R-1 (no zone found)")

print(f"\nEnriched: {enriched}/{len(parcel_files)}")
print(f"Zone distribution: {zone_distribution}")

# Step 3: Re-baseline scoreboard with mapped zones
print("\n--- Re-baselining scoreboard ---")
sys.path.insert(0, REPO)
from intake_geojson import load_geojson_parcel
from generator import LayoutGenerator
from constraints import ConstraintEngine
from models import LayoutRules, RoadPattern
from checker import LotChecker

engine = ConstraintEngine("hrm")
engine.load()
available_zones = set(engine._zones.keys())
print(f"Constraint engine zones: {sorted(available_zones)}")

patterns = [RoadPattern.SINGLE_ROAD, RoadPattern.CUL_DE_SAC, RoadPattern.EXISTING_ROAD]
passed = 0
for pf in parcel_files:
    parcel = load_geojson_parcel(pf, rules=None)
    zc = parcel.zone_code or "R-1"
    if zc not in available_zones:
        zc = "R-1"
    try:
        pc = engine.resolve(zc, "serviced")
        rules = LayoutRules.from_constraint_engine(pc)
    except Exception:
        pc = engine.resolve("R-1", "serviced")
        rules = LayoutRules.from_constraint_engine(pc)
        zc = "R-1"
    parcel.zone_code = zc
    best = 0
    for pat in patterns:
        try:
            gen = LayoutGenerator(parcel, rules)
            result = gen.generate_layout(pat)
            checker = LotChecker(rules)
            checker.check_layout(result)
            best = max(best, result.passing_lots)
        except Exception:
            continue
    if best >= 1:
        passed += 1
    print(f"  {os.path.basename(pf)}: zone={zc} best={best}")

print(f"\nRe-baselined scoreboard: {passed}/{len(parcel_files)}")