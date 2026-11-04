# India Post — Smart TA Bill Generator

Record journeys in Hindi, English or Hinglish, review official office matches and download the prescribed JourneyDetails workbook. This replacement lives alongside the original Streamlit `app.py` and `requirements.txt`; neither legacy file is modified. Do not switch the existing production deployment until acceptance checks below pass.

## Architecture and repository audit

The original Streamlit app used a browser-supplied API key, voice/photo/manual entry, and Gemini-estimated road kilometres. Its default model ID was `gemini-3.6-flash`; spreadsheet output was built afresh. The replacement removes photo/manual journey submission and AI distance estimation.

- `web/`: lightweight static HTML, CSS and JavaScript, with native MediaRecorder, no framework build, no browser secrets. The modest interface does not need React or a Node runtime. Mobile cards adapt to desktop; red India Post branding and supplied logo at top right.
- `backend/main.py`: FastAPI; same-origin private session cookies, audio validation and Gemini REST structured extraction. No local speech model. Follow-up recordings receive the corrected current journey context.
- `backend/core.py`: Pydantic schemas, official-ID matching, conservative fuzzy candidates, validated Hindi/English aliases, deterministic time rules, routing and Decimal fares, template-based openpyxl export.
- `data/offices.json`: all 696 records imported from the supplied HTML-as-XLS file. Only seven required source columns and a derived coordinate-validation flag are retained; emails, telephone numbers and unrelated personal fields are excluded. All IDs are unique; all coordinates pass India bounding checks. This validates range, not geographic accuracy.
- `data/Journey_Details_Template.xlsx`: unchanged supplied workbook. Export copies row styles, preserves sheet/ten headers/column widths, removes example rows and writes no summary rows. Dates remain DD/MM/YYYY text and times HH:MM text, as in the actual template; distances/fares are numeric. Literal text cannot become an Excel formula.
- SQLite cache stores office-pair distances only, keyed by direction, method, routing version, source coordinates and endpoint. Claims and recordings never enter this cache.

## Run locally

Use Python 3.12 and install FFmpeg from your operating system package manager (e.g. `sudo apt install ffmpeg` on Debian/Ubuntu). Docker includes FFmpeg automatically.

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
# Edit .env privately; never commit it.
set -a
. ./.env
set +a
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --workers 1
```

Open http://localhost:8000. Localhost supports microphone access; remote devices require HTTPS. In local configuration set `COOKIE_SECURE=false`, `APP_ORIGIN=http://localhost:8000`. Production must use `COOKIE_SECURE=true`. Do not use multiple workers or replicas with in-memory sessions.

```sh
pytest -q
# Or build/run the complete deployable image:
docker build -t smart-ta .
docker run --rm -p 8000:10000 --env-file .env smart-ta
```

## Required administrator configuration

| Variable | Meaning |
| --- | --- |
| `GEMINI_API_KEY` | Backend secret from Google AI Studio; never enter it in the app or commit it |
| `GEMINI_MODEL` | Default `gemini-3.5-flash-lite`; verify availability with your account |
| `APP_ORIGIN` | Exact public HTTPS origin; no trailing slash |
| `COOKIE_SECURE` | `true` for HTTPS; `false` only for localhost |
| `DISTANCE_METHOD` | `road` by default, or explicitly approved `haversine` |
| `ROUTING_URL` | Approved OSRM-compatible service origin, supporting `/route/v1/driving/{lon,lat;lon,lat}`; do not use an unapproved public demo endpoint |
| `ROUTING_DATA_VERSION` | Mandatory routing-dataset version such as the provider's published map build ID; change when maps change |
| `ALLOW_HAVERSINE` | Must be exactly `true` to authorize configured straight-line calculation; never enabled by default |
| `MAX_AUDIO_PER_HOUR` | 20 processing attempts per source IP per hour by default; shared departmental networks may need adjustment |
| `DISTANCE_CACHE` | Default `/tmp/ta-distance.sqlite3`; ephemeral cache is safe to rebuild |
| `FFMPEG_BINARY` | Optional absolute path, default `ffmpeg` |

Road routing fails closed if unconfigured or unavailable. No multiplier, AI guess or automatic straight-line fallback is used. A private/provider OSRM endpoint is the implemented adapter; services with other authentication or request formats need a small server-side adapter. A verified distance cache is used only for responses from the configured provider, not an assertion of human survey verification.

Model checked against [Google's model documentation](https://aistudio.google.com/docs/models/gemini-3.5-flash-lite) on 4 November 2026: audio input and structured output are supported. `gemini-3.6-flash-lite` was not established as a documented model; `gemini-3.5-flash-lite` is used instead. [Listed Gemini API pricing](https://aistudio.google.com/docs/pricing#gemini-3.5-flash-lite): US$0.30 per million input tokens (including audio) and US$2.50 per million output tokens. Cost varies with audio length/output and account tier. No grounding, search or billable routing is enabled automatically. Use the paid API tier if departmental data handling requires Google's documented paid-tier data terms.

## Deploy a separate Render preview

Use the connected GitHub repository `NewDelhiCentralDivision/TABill`, development branch `codex/smart-ta-modernization`, Docker runtime, Singapore region and the included Dockerfile. No frontend build is required. Start one process; the Docker command binds `$PORT` on `0.0.0.0`. Set HTTP health-check path `/api/health` in the Dashboard.

The smallest Render plan (`free`, 512 MB) is suitable for preview and sleeps when idle. For an always-on departmental service, choose the 512 MB paid plan (listed at US$7/month on 4 November 2026) after measuring actual load. See [current plans](https://render.com/docs/compute-plans) and [prices](https://render.com/pricing). A single service avoids a second backend bill and cross-origin cookie complications. Cloudflare can front a custom domain later; the frontend remains static and can be moved to Cloudflare with a same-origin API proxy. Do not expose secrets through static build variables.

Add `GEMINI_API_KEY`, the exact `APP_ORIGIN`, `GEMINI_MODEL`, `COOKIE_SECURE=true`, and the approved routing variables through Render's Environment screen. API secrets are intentionally not present in GitHub. Saving environment changes must result in a new deployment before they take effect. The preview can serve the interface without a key, but voice processing and road-distance export stay blocked until configured.

## Workflow, limits and recovery

1. Start recording (permissions requested only now); speak dates, office names and visits; stop. MediaRecorder negotiates WebM/Opus, MP4 or Ogg based on browser support and sends its actual MIME type. Duration and waveform are visible.
2. Listen, discard/rerecord or process. Audio survives API/network errors in the current tab and can be retried. Five minutes and 8 MB maximum; decoding validates actual duration, including WebM without container duration. Browser requests 32 kbps audio, though implementations may choose another bitrate.
3. Gemini returns schema-validated transcript and ordered legs, with date evidence. It receives no responsibility for distance or fares. Unclear dates, missing years and date conflicts require review. The spoken year is never silently replaced by the current year.
4. The server resolves exact names and explicit aliases against the master, then conservatively accepts high-confidence unique matches; otherwise candidates require selection. Search all offices by name, division or PIN. Office IDs remain internal. Hindi variants beyond the curated alias list may require candidate correction; unvalidated Hindi transcription quality is not claimed.
5. Defaults start 10:00/10:30, 11:00/11:30, etc. for each date. Explicit times remain intact; missing times are inferred only if chronological. Cross-midnight defaults require clarification. Correct dates, times, office matches, remarks, remove/reorder legs, or record missing details/additional visits. Rate changes recalculate the whole bill.
6. Server validates again on export. `Road` is written to every row. Distance is rounded to two decimals first; fare is that value × rate, rounded half-up to two decimals; displayed total sums the exact exported row fares.

A short-lived random HttpOnly/SameSite cookie isolates each session. Server state expires after 30 minutes of inactivity and is removed on subsequent requests. Audio is decoded in an automatically deleted temporary file, then sent to Gemini; it is not stored in server sessions. Generated XLSX is streamed from memory. Browser audio lasts until discarded/replaced or the tab closes; tab reload loses unsaved local state. No cross-device claim storage or login is provided. For restricted departmental access place the service behind the organization's access gateway before rollout.

Three audio jobs execute concurrently to bound memory; at least ten officials can hold independent sessions with additional jobs waiting. This is an architecture limit, not a measured 512 MB production load guarantee. The session cap is 200 and the HTTP concurrency cap 40. A per-session lock and recording hash prevent repeat-click duplicate processing; failed calls can be retried. Gemini timeouts/quota errors are shown without automatic potentially billable retries. Office master is public data; journey data is not logged by the application. Standard host access logs contain endpoint paths/statuses only.

## Update the office master

For future files in the same HTML-as-XLS format:

```sh
python scripts/import_offices.py '/path/to/new/master.xls' data/offices.json
pytest -q
```

Review `data/office_import_report.json` and master differences. Invalid coordinates are retained with a flag and block calculation. Duplicate office IDs abort the import. Native XLSX sources should first be normalized to the same seven-column JSON shape by an administrator. `data/aliases.json` maps validated office IDs to curated names/abbreviations; never map a similar-sounding office without checking the master. Restart/redeploy after data updates.

## Verification and rollout gate

Run `pytest -q` for mocked extraction, follow-up context, retry idempotence, isolated sessions, missing dates/export blocking, date/time sequencing, Hindi alias matching, fares, routing cache direction/failure and exact workbook headers/types/sample removal. Automated fixtures do not prove real Hindi/Hinglish speech recognition or routing accuracy.

Before promoting the development branch, complete real-device acceptance on desktop Chrome, Android Chrome and iPhone Safari: allow/deny mic, pause/stop, review/listen/rerecord, retry after disconnect, short missing-date follow-up, multi-day and overnight journeys, spoken Hindi/Hinglish and ambiguous offices. Open an exported claim in Excel and LibreOffice and import it into the actual reimbursement application. Those external applications and physical phones are not part of the automated test environment. Compare several road routes against the approved authority's known distances. Measure memory and latency with ten concurrent recordings using your quota; adjust the plan or queue accordingly.

Do not merge until these acceptance checks and administrator configuration are complete.
