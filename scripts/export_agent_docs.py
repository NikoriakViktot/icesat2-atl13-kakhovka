#!/usr/bin/env python3
"""Regenerate the machine-readable API docs from the code.

    python scripts/export_agent_docs.py          # write docs/openapi.json + docs/agent-tools.json
    python scripts/export_agent_docs.py --check  # exit 1 if they are stale (CI / tests)

``agent-tools.json`` is a list of tool definitions (``name``, ``description``,
``input_schema`` JSON Schema, and ``http`` = how to call it) that LLM agent
frameworks can load directly (Anthropic ``tools``, OpenAI ``functions`` after
renaming ``input_schema`` to ``parameters``, MCP ``inputSchema``).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kakhovka_altimetry.service.api import JobIn, RegionIn, app  # noqa: E402

DOCS = Path(__file__).resolve().parents[1] / "docs"

_DATE = {"type": "string", "format": "date", "description": "YYYY-MM-DD, inclusive"}
_SLUG = {"type": "string", "pattern": "^[a-z0-9_]{2,64}$", "description": "region slug"}
_PRODUCT = {"type": "string", "enum": ["ATL13", "ATL08", "ATL03"]}


def _obj(props: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": props, "required": required or [],
            "additionalProperties": False}


def agent_tools() -> list[dict]:
    """Tool definitions for agents; one per useful endpoint."""
    return [
        {
            "name": "list_products",
            "description": "List the ICESat-2 products this service can ingest (ATL13 inland "
                           "water, ATL08 terrain + canopy, ATL03 photons), their raster "
                           "variables and the reference DEMs. Call once per session.",
            "input_schema": _obj({}),
            "http": {"method": "GET", "path": "/products"},
        },
        {
            "name": "list_regions",
            "description": "List configured and registered regions with their row counts.",
            "input_schema": _obj({}),
            "http": {"method": "GET", "path": "/regions"},
        },
        {
            "name": "register_region",
            "description": "Register (or update) an area of interest by slug. bbox or GeoJSON "
                           "polygon is required; coord (a point ON the water) is required for "
                           "ATL13. vertical: egm2008 anywhere, egg2015 only in Europe.",
            "input_schema": RegionIn.model_json_schema(),
            "http": {"method": "POST", "path": "/regions", "body": "input"},
        },
        {
            "name": "create_job",
            "description": "Queue an asynchronous ingest job and return its job_id. Always set "
                           "start/end; use limit for a first look. Then poll get_job until "
                           "status is 'done' or 'failed'. Re-submitting is safe: loaded "
                           "granules are skipped.",
            "input_schema": JobIn.model_json_schema(),
            "http": {"method": "POST", "path": "/jobs", "body": "input"},
        },
        {
            "name": "get_job",
            "description": "Job status (queued|running|done|failed), stage "
                           "(discover|acquire|process|load), stats (counts, dem_comparison, "
                           "rasters) and error. Poll every 5-10 s at first, then every 30 s.",
            "input_schema": _obj({"job_id": {"type": "string", "format": "uuid"}}, ["job_id"]),
            "http": {"method": "GET", "path": "/jobs/{job_id}"},
        },
        {
            "name": "list_jobs",
            "description": "Recent jobs, newest first, optionally filtered.",
            "input_schema": _obj({"region": _SLUG, "product": _PRODUCT,
                                  "limit": {"type": "integer", "minimum": 1, "maximum": 500}}),
            "http": {"method": "GET", "path": "/jobs", "query": "input"},
        },
        {
            "name": "get_pass_levels",
            "description": "ATL13 water levels, one per (date, rgt, beam): median_wse_m in "
                           "the region's vertical_datum, nmad_m, n_points, qc_pass. Use "
                           "qc_pass=true and format=csv for a time series.",
            "input_schema": _obj({"slug": _SLUG, "start": _DATE, "end": _DATE,
                                  "qc_pass": {"type": "boolean"},
                                  "format": {"type": "string", "enum": ["geojson", "csv"]}},
                                 ["slug"]),
            "http": {"method": "GET", "path": "/regions/{slug}/pass-levels", "query": "rest"},
        },
        {
            "name": "get_points",
            "description": "ATL13 or ATL08 point rows (heights: ellipsoidal, h_m/wse_m in the "
                           "region datum, h_egm2008_m, cop30_m/fabdem_m when compared). ATL03 "
                           "photons are not served here.",
            "input_schema": _obj({"slug": _SLUG,
                                  "product": {"type": "string", "enum": ["ATL13", "ATL08"]},
                                  "start": _DATE, "end": _DATE,
                                  "limit": {"type": "integer", "minimum": 1,
                                            "maximum": 1_000_000},
                                  "format": {"type": "string", "enum": ["csv", "json"]}},
                                 ["slug"]),
            "http": {"method": "GET", "path": "/regions/{slug}/points", "query": "rest"},
        },
        {
            "name": "get_dem_comparisons",
            "description": "ICESat-2 minus reference DEM (cop30, fabdem) statistics in EGM2008: "
                           "median_m = bias, nmad_m = robust spread.",
            "input_schema": _obj({"job_id": {"type": "string", "format": "uuid"},
                                  "region": _SLUG}),
            "http": {"method": "GET", "path": "/dem-comparisons", "query": "input"},
        },
        {
            "name": "list_rasters",
            "description": "ICESat-2 gridded rasters (dtm, chm, wse): resolution, UTM crs, "
                           "vertical_datum, stats, footprint. Download a COG with "
                           "GET /rasters/{raster_id}/download (band 1 value, band 2 count).",
            "input_schema": _obj({"region": _SLUG, "product": _PRODUCT,
                                  "variable": {"type": "string", "enum": ["dtm", "chm", "wse"]},
                                  "job_id": {"type": "string", "format": "uuid"}}),
            "http": {"method": "GET", "path": "/rasters", "query": "input"},
        },
        {
            "name": "list_granules",
            "description": "Per-granule status (pending|fetched|empty|loaded) for a region.",
            "input_schema": _obj({"region": _SLUG, "product": _PRODUCT,
                                  "status": {"type": "string",
                                             "enum": ["pending", "fetched", "empty", "loaded"]}}),
            "http": {"method": "GET", "path": "/granules", "query": "input"},
        },
    ]


def render() -> dict[Path, str]:
    return {
        DOCS / "openapi.json": json.dumps(app.openapi(), indent=2) + "\n",
        DOCS / "agent-tools.json": json.dumps({
            "info": "Tool definitions for the ICESat-2 ingest API. Every call needs header "
                    "X-API-Key. Guide: docs/agents-api.md, recipes: docs/agent-playbooks.md.",
            "auth": {"type": "header", "name": "X-API-Key"},
            "tools": agent_tools(),
        }, indent=2) + "\n",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    stale = []
    for path, text in render().items():
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != text:
                stale.append(path.name)
        else:
            path.write_text(text, encoding="utf-8")
            print(f"wrote {path}")
    if stale:
        print(f"stale: {', '.join(stale)} -- run scripts/export_agent_docs.py", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
