# Validation record — 4 November 2026

- 41 automated tests pass, with Gemini/routing mocked; no paid API calls made.
- Ten simulated officials use independent session cookies and fare rates concurrently.
- Actual locally encoded 2-second WebM/Opus, Ogg/Opus, MP4/AAC and WAV/PCM files pass the duration decoder. These tone files test encoding, not speech recognition or physical microphones.
- Browser preview inspected at desktop and phone widths; no horizontal overflow at a 375px content width. JavaScript syntax check passes.
- Export reloaded with openpyxl: exact ten headers and JourneyDetails worksheet; template text dates/times; numeric distance/fare; no sample rows; Road literal; formula-like remarks stored as text.
- Office import: 696 unique IDs, no invalid coordinate ranges; original source hash in data/office_import_report.json.
- One third-party Starlette TestClient deprecation warning remains in this dependency release; tests pass.

## Checks still required before production promotion

- Real Gemini calls with the administrator's configured key, including Hindi/Hinglish and ambiguous dates.
- Approved road provider setup and measured comparison against known road distances.
- Desktop Chrome, physical Android Chrome and physical iPhone Safari microphone/permission/network-recovery tests.
- Open exported claims in Excel and LibreOffice, then test the actual reimbursement application's importer.
- Production memory/latency measurements on the chosen 512 MB plan with ten recordings and actual API quota.

The preview is not a completed departmental acceptance test. The original production files remain untouched and the pull request should remain a draft until these checks are complete.
