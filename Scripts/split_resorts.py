#!/usr/bin/env python3
"""
Preprocesses global OpenSkiData GeoJSON into per-resort bundles.

Downloads ski_areas, runs, and lifts GeoJSON from OpenSkiMap,
groups runs/lifts by ski area ID, and writes:
  - dist/{resort_id}.json.gz  (per-resort bundle with resort + runs + lifts)
  - dist/resort_index.json    (lightweight catalog of all resorts)

Usage:
    python3 Scripts/split_resorts.py [--output dist] [--skip-download]
"""

import json
import gzip
import os
import sys
import time
import argparse
import urllib.request
from collections import defaultdict
from pathlib import Path

BASE_URL = "https://tiles.openskimap.org/geojson"
FILES = {
    "ski_areas": f"{BASE_URL}/ski_areas.geojson",
    "runs": f"{BASE_URL}/runs.geojson",
    "lifts": f"{BASE_URL}/lifts.geojson",
}

DOWNLOAD_DIR = Path("/tmp/openskidata")
DEFAULT_OUTPUT = Path("dist")


def download_file(url: str, dest: Path) -> None:
    """Download a file with progress reporting."""
    if dest.exists():
        size_mb = dest.stat().st_size / (1024 * 1024)
        print(f"  Already downloaded: {dest.name} ({size_mb:.1f} MB)")
        return

    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"  Downloading {url}...")
    start = time.time()

    req = urllib.request.Request(url, headers={"User-Agent": "Carvable/1.0"})
    with urllib.request.urlopen(req, timeout=600) as response:
        total = int(response.headers.get("Content-Length", 0))
        downloaded = 0
        chunk_size = 1024 * 1024  # 1MB chunks

        with open(dest, "wb") as f:
            while True:
                chunk = response.read(chunk_size)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                if total > 0:
                    pct = downloaded / total * 100
                    print(f"\r  {downloaded / (1024*1024):.1f} / {total / (1024*1024):.1f} MB ({pct:.0f}%)", end="", flush=True)
                else:
                    print(f"\r  {downloaded / (1024*1024):.1f} MB", end="", flush=True)

    elapsed = time.time() - start
    size_mb = dest.stat().st_size / (1024 * 1024)
    print(f"\n  Done: {size_mb:.1f} MB in {elapsed:.0f}s")


def load_geojson(path: Path) -> dict:
    """Load and parse a GeoJSON file."""
    print(f"  Parsing {path.name}...")
    start = time.time()
    with open(path, "r") as f:
        data = json.load(f)
    elapsed = time.time() - start
    count = len(data.get("features", []))
    print(f"  Parsed {count:,} features in {elapsed:.1f}s")
    return data


def extract_ski_area_ids(feature: dict) -> list[str]:
    """Extract ski area IDs from a run or lift feature."""
    ski_areas = feature.get("properties", {}).get("skiAreas", [])
    ids = []
    for sa in ski_areas:
        if isinstance(sa, dict):
            props = sa.get("properties", {})
            sa_id = props.get("id")
            if sa_id:
                ids.append(sa_id)
    return ids


def get_resort_location(feature: dict) -> tuple[float, float] | None:
    """Extract lat/lng from a ski area feature geometry."""
    geom = feature.get("geometry")
    if not geom:
        return None

    geom_type = geom.get("type")
    coords = geom.get("coordinates")

    if geom_type == "Point" and coords and len(coords) >= 2:
        return (coords[1], coords[0])  # lat, lng
    elif geom_type == "Polygon" and coords and coords[0]:
        ring = coords[0]
        avg_lng = sum(c[0] for c in ring) / len(ring)
        avg_lat = sum(c[1] for c in ring) / len(ring)
        return (avg_lat, avg_lng)

    return None


def compute_difficulty_breakdown(runs: list[dict]) -> dict[str, int]:
    """Count runs by difficulty level."""
    counts = defaultdict(int)
    for run in runs:
        diff = run.get("properties", {}).get("difficulty", "other")
        counts[diff] += 1
    return dict(counts)


def main():
    parser = argparse.ArgumentParser(description="Split OpenSkiData into per-resort bundles")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output directory")
    parser.add_argument("--skip-download", action="store_true", help="Use existing downloaded files")
    args = parser.parse_args()

    output_dir = args.output
    output_dir.mkdir(parents=True, exist_ok=True)

    # Step 1: Download global GeoJSON files
    print("\n=== Step 1: Download GeoJSON ===")
    if not args.skip_download:
        for name, url in FILES.items():
            download_file(url, DOWNLOAD_DIR / f"{name}.geojson")
    else:
        print("  Skipping downloads (--skip-download)")

    # Step 2: Parse ski areas
    print("\n=== Step 2: Parse ski areas ===")
    areas_data = load_geojson(DOWNLOAD_DIR / "ski_areas.geojson")
    resorts = {}
    for feature in areas_data["features"]:
        props = feature.get("properties", {})
        resort_id = props.get("id")
        name = props.get("name")
        if not resort_id or not name:
            continue

        # Only include downhill ski areas
        activities = props.get("activities", [])
        if "downhill" not in activities:
            continue

        location = get_resort_location(feature)
        resorts[resort_id] = {
            "feature": feature,
            "name": name,
            "location": location,
            "statistics": props.get("statistics"),
            "status": props.get("status"),
            "websites": props.get("websites", []),
            "runConvention": props.get("runConvention"),
        }
    print(f"  Found {len(resorts):,} downhill ski areas")

    # Step 3: Parse and group runs by ski area
    print("\n=== Step 3: Parse and group runs ===")
    runs_data = load_geojson(DOWNLOAD_DIR / "runs.geojson")
    runs_by_area = defaultdict(list)
    orphan_runs = 0
    for feature in runs_data["features"]:
        area_ids = extract_ski_area_ids(feature)
        if not area_ids:
            orphan_runs += 1
            continue
        for area_id in area_ids:
            if area_id in resorts:
                runs_by_area[area_id].append(feature)
    print(f"  Grouped runs into {len(runs_by_area):,} resorts ({orphan_runs:,} orphans)")

    # Step 4: Parse and group lifts by ski area
    print("\n=== Step 4: Parse and group lifts ===")
    lifts_data = load_geojson(DOWNLOAD_DIR / "lifts.geojson")
    lifts_by_area = defaultdict(list)
    orphan_lifts = 0
    for feature in lifts_data["features"]:
        area_ids = extract_ski_area_ids(feature)
        if not area_ids:
            orphan_lifts += 1
            continue
        for area_id in area_ids:
            if area_id in resorts:
                lifts_by_area[area_id].append(feature)
    print(f"  Grouped lifts into {len(lifts_by_area):,} resorts ({orphan_lifts:,} orphans)")

    # Step 5: Write per-resort bundles
    print("\n=== Step 5: Write per-resort bundles ===")
    index_entries = []
    written = 0
    skipped = 0

    for resort_id, resort_info in resorts.items():
        runs = runs_by_area.get(resort_id, [])
        lifts = lifts_by_area.get(resort_id, [])

        # Skip resorts with no runs AND no lifts
        if not runs and not lifts:
            skipped += 1
            continue

        # Build the bundle
        bundle = {
            "resort": resort_info["feature"],
            "runs": runs,
            "lifts": lifts,
        }

        # Write compressed bundle
        bundle_path = output_dir / f"{resort_id}.json.gz"
        json_bytes = json.dumps(bundle, separators=(",", ":")).encode("utf-8")
        with gzip.open(bundle_path, "wb") as f:
            f.write(json_bytes)

        # Build index entry
        difficulty_breakdown = compute_difficulty_breakdown(runs)
        location = resort_info["location"]

        entry = {
            "id": resort_id,
            "name": resort_info["name"],
            "latitude": location[0] if location else None,
            "longitude": location[1] if location else None,
            "runCount": len(runs),
            "liftCount": len(lifts),
            "difficulty": difficulty_breakdown,
            "status": resort_info["status"],
        }

        # Add elevation data from statistics if available
        stats = resort_info.get("statistics")
        if stats:
            entry["maxElevation"] = stats.get("maxElevation")
            entry["minElevation"] = stats.get("minElevation")

        index_entries.append(entry)
        written += 1

    # Sort index by name
    index_entries.sort(key=lambda e: e["name"].lower())

    print(f"  Wrote {written:,} resort bundles, skipped {skipped:,} empty resorts")

    # Step 6: Write resort index
    print("\n=== Step 6: Write resort index ===")
    index_path = output_dir / "resort_index.json"
    with open(index_path, "w") as f:
        json.dump(index_entries, f, separators=(",", ":"))

    index_size = index_path.stat().st_size / 1024
    print(f"  Wrote {index_path} ({index_size:.0f} KB, {len(index_entries):,} resorts)")

    # Summary
    print(f"\n=== Done ===")
    print(f"  Output: {output_dir}")
    print(f"  Resorts: {written:,}")
    print(f"  Index: {index_size:.0f} KB")


if __name__ == "__main__":
    main()
