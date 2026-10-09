# Frontend and BFF integration

How a web frontend uses this API. Short version: **the browser should not hold a
read/write API key.** Put a backend (BFF) in between that authenticates your users,
checks their rights, and calls this API with its own key and `X-Requested-By`.

```
browser (SPA) ──JWT/session──▶ BFF (e.g. Django)  ──X-API-Key: <bff key>──▶ ingest API
                               · who is the user?    X-Requested-By: user:<id>
                               · may they do this?
                               · audit
```

## 1. Keys and scopes

`API_KEYS` is a comma-separated list; each entry is one of

| entry | client name | may |
|---|---|---|
| `<key>` | `default` | read + write |
| `<name>:<key>` | `<name>` | read + write; use this for the BFF (`django:…`) |
| `<name>:<key>:ro` | `<name>` | **read only**: writes get 403 |

```
API_KEYS=django:3f9c...e1,frontend:7a2b...90:ro
```

Every job and registered region records `client` (the key's name) and
`requested_by` (the `X-Requested-By` header, if sent). A registered region can be
updated only by the same client **and** the same `requested_by`; anyone else
gets `409`.

### Option A: BFF (recommended)

- Only the BFF knows the read/write key; it never reaches the browser.
- The BFF sends `X-Requested-By: user:<id>` (any stable string, ≤ 200 chars) on
  every write, and filters reads with `?requested_by=user:<id>`.
- Region slugs are global in this API. Namespace them in the BFF, e.g.
  `p<project_id_hex>` or `u<user_id>_<name>`.
- Permissions (who may run jobs in which project) live in the BFF. The ingest API
  trusts its clients.

### Option B: browser talks to the API directly (internal tools only)

- Give the frontend a **read-only** key (`frontend:<key>:ro`). It can browse regions,
  jobs and results, but cannot start jobs.
- Anyone who opens DevTools sees that key, so use this only on a closed network.

## 2. CORS

Only needed when a browser calls the API directly (option B, or the BFF on another
origin). Set the allowed origins:

```
CORS_ORIGINS=https://geohydroai.org,http://localhost:5173
```

Allowed: methods `GET, POST`; request headers `X-API-Key`, `X-Requested-By`,
`Content-Type`; exposed header `Content-Disposition` (download file names);
preflight cached 10 min. With `CORS_ORIGINS` empty, no CORS headers are sent.
Changing it requires an API restart.

## 3. The flow a UI implements

1. **Area**: draw a bbox or polygon (EPSG:4326, GeoJSON). For water levels (ATL13),
   also ask for a point **on the water** (`coord`). `POST /regions`, or pass the
   region inline in the job.
2. **Job**: `POST /jobs` → `202 {job_id, status: "queued"}`. Always send `start` and
   `end`; default `limit` 5–10.
3. **Progress**: poll `GET /jobs/{job_id}` every 5–10 s, then 30 s after the first
   minute, until `status` ∈ {`done`, `failed`}. Show `stage` as a stepper
   (`discover → acquire → process → load`). There is no cancel, WebSocket or SSE.
4. **Results**:

| view | call | notes |
|---|---|---|
| water-level chart | `GET /regions/{slug}/pass-levels?qc_pass=true&format=csv` | per date: median of `median_wse_m` across beams |
| water-level map | same, default `format=geojson` | LineString per pass; properties = the row |
| points table/map | `GET /regions/{slug}/points?product=ATL08&format=json&limit=…` | ≤ 1 000 000 rows; default 100 000 |
| DEM validation card | `GET /dem-comparisons?job_id=…` | show `median_m` (bias) and `nmad_m` (spread) |
| raster list / footprints | `GET /rasters?job_id=…` | `footprint` is GeoJSON; `crs` is UTM |
| raster file | `GET /rasters/{id}/download` | whole COG (no HTTP Range): band 1 value, band 2 point count |

### Form rules (mirror them client-side)

- `slug`: `^[a-z0-9_]{2,64}$`.
- ATL13 requires `region.coord`; ATL08 / ATL03 don't.
- `atl03` options only with `product: "ATL03"`; keep ATL03 areas small and `limit` ≤ 5.
- `vertical: "egg2015"` only for Europe; default `egm2008`.
- `dem.resolution_m` 10–10 000; `dem.variables`: ATL13 `wse`, ATL08 `dtm` / `chm`,
  ATL03 `dtm`.
- `compare` ⊂ {`cop30`, `fabdem`}.

### Errors

FastAPI shape `{"detail": …}`:
- **422**: `detail` is a list `[{loc: ["body","region","coord"], msg, type}]`; map
  `loc` to form fields.
- **401**: bad key. **403**: the key is read-only. **404**: unknown region, job or
  raster. **409**: slug owned by someone else, or a configured region.
- A job with `status: "failed"` has `error` (exception + stage).
- `stats.to_fetch == 0` is not an error: nothing new in that window.

### Display rules

- Show the datum next to every height: `vertical_datum` (`EGM2008` |
  `EVRS_EGG2015`); for Kakhovka regions also `period`.
- Rasters are **sparse** (values only along ICESat-2 tracks, ~3 km apart). Render
  NaN as transparent and show band 2 (point count) on hover. Don't present them
  as complete maps.
- Units: metres; EPSG:4326 lon/lat; timestamps UTC ISO-8601.

## 4. Types

```bash
npx openapi-typescript docs/openapi.json -o src/api/icesat2.ts
```

`docs/openapi.json` is kept in sync with the code by
`tests/test_docs_in_sync.py`. Live copies: `/openapi.json` and `/docs`.

## 5. Minimal TypeScript client

```ts
const BASE = import.meta.env.VITE_ICESAT2_URL;           // BFF route or the API
const headers = { "Content-Type": "application/json" };  // BFF adds the key server-side

export async function createJob(body: unknown) {
  const r = await fetch(`${BASE}/jobs`, { method: "POST", headers, body: JSON.stringify(body) });
  if (!r.ok) throw Object.assign(new Error("job rejected"), { status: r.status, body: await r.json() });
  return (await r.json()) as { job_id: string; status: string };
}

export async function waitForJob(id: string, onUpdate?: (j: any) => void) {
  const t0 = Date.now();
  for (;;) {
    const j = await (await fetch(`${BASE}/jobs/${id}`, { headers })).json();
    onUpdate?.(j);
    if (j.status === "done" || j.status === "failed") return j;
    await new Promise(res => setTimeout(res, Date.now() - t0 < 60_000 ? 5_000 : 30_000));
  }
}
```
