# carvable-data

Pre-processed OpenSkiData resort bundles for the [Carvable](https://github.com/nickpdawson/carvable) iOS app.

## How it works

A daily GitHub Action downloads global GeoJSON from [OpenSkiMap](https://openskimap.org), splits it into per-resort bundles, and publishes them as GitHub Release assets.

**Data source:** [OpenSkiData](https://www.openskidata.org/) (CC BY 4.0)

## Files

- `Scripts/split_resorts.py` -- Downloads and processes global GeoJSON into per-resort bundles
- `.github/workflows/update-data.yml` -- Daily cron job that runs the pipeline and publishes release assets

## Release assets

- `resort_index.json` -- Lightweight catalog of all resorts (name, location, run/lift counts)
- `{resort_id}.json.gz` -- Per-resort bundle containing resort metadata, runs, and lifts as GeoJSON features

## Running locally

```bash
python3 Scripts/split_resorts.py --output dist
```

Downloads ~230MB of GeoJSON to `/tmp/openskidata/`, processes into `dist/`.

Use `--skip-download` to reprocess without re-downloading.
