"""
Journey Distance & Fare Calculator — New Delhi Central Division
==================================================================
Streamlit app. Local road journeys within Delhi, Rs. 11/km, Mode = "By Road".

Three ways to add a journey:
  1. Speak it — st.audio_input records from the browser's mic (works over
     HTTPS, incl. Streamlit Community Cloud), Gemini transcribes + extracts
     the fields in one call.
  2. Photo — upload or camera-capture a travel note/slip; Gemini reads it
     (OCR + field extraction) directly.
  3. Type manually — the shared form below is always editable directly.

Distance between the two Delhi locations is estimated by asking Gemini
(as a Delhi roads/geography expert) for a realistic road-driving distance.

Output: an .xlsx download with the same columns as the original template:
From Date | From Time | From Place | To Date | To Time | To Place |
Mode | Distance (Km) | Fare Paid | Remarks

--------------------------------------------------------------------
RUN LOCALLY
--------------------------------------------------------------------
    pip install -r requirements.txt
    streamlit run app.py

Get a free Gemini API key at https://aistudio.google.com/apikey and paste
it in the sidebar (or set it as a secret / env var, see below).

--------------------------------------------------------------------
DEPLOY ON STREAMLIT COMMUNITY CLOUD
--------------------------------------------------------------------
Push this file + requirements.txt to a GitHub repo, deploy as usual. Then,
instead of typing the key each time, add it once under
App settings → Secrets:

    GEMINI_API_KEY = "your-key-here"
    GEMINI_MODEL   = "gemini-3.6-flash"   # optional: default model in the dropdown

The app picks the key up automatically and never asks for it. (Locally, the
same names also work as environment variables or in .streamlit/secrets.toml.)

The sidebar "Gemini model" dropdown lists the models your key can use
(fetched live); change it any time without redeploying.
--------------------------------------------------------------------
"""

import io
import json
import os
from datetime import date, datetime

import pandas as pd
import streamlit as st
import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from PIL import Image

from google import genai
from google.genai import types

# -----------------------------------------------------------------------
# Config
# -----------------------------------------------------------------------
DEFAULT_GEMINI_MODEL = "gemini-3.6-flash"   # default selection; can be overridden via secrets
# Fallback choices, used when the live model list can't be fetched.
FALLBACK_MODELS = [DEFAULT_GEMINI_MODEL, "gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.5-pro"]
CUSTOM_MODEL_LABEL = "Other (type a model name)…"
RATE_PER_KM = 11
HEADERS = ["From Date", "From Time", "From Place", "To Date", "To Time",
           "To Place", "Mode", "Distance (Km)", "Fare Paid", "Remarks"]
FORM_KEYS = ["from_place", "from_date", "from_time", "to_place", "to_date", "to_time", "remarks"]

MAROON = "#6b1e26"
MAROON_DARK = "#4a1319"
GOLD = "#c8a24a"
GOLD_SOFT = "#e8d9b0"
PAPER = "#f7f2e7"
PAPER_DIM = "#efe7d6"
LINE = "#ddd0b3"

st.set_page_config(page_title="Journey Distance & Fare Calculator — NDCD",
                    page_icon="🛣️", layout="centered")

st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@600;700&family=Inter:wght@400;500;600&family=IBM+Plex+Mono:wght@500&display=swap');
html, body, [class*="css"] {{ font-family: 'Inter', sans-serif; }}
.stApp {{ background-color: {PAPER}; }}
.ndcd-topbar {{
  border-bottom: 3px solid {MAROON}; padding-bottom: 12px; margin-bottom: 18px;
}}
.ndcd-topbar h1 {{
  font-family: 'Space Grotesk', sans-serif; color: {MAROON_DARK};
  font-size: 26px; margin-bottom: 2px; font-weight:700;
}}
.ndcd-topbar .sub {{ color:#6b6255; font-size: 13px; }}
.ndcd-badge {{
  display:inline-block; background:{MAROON}; color:{GOLD_SOFT};
  font-family:'IBM Plex Mono', monospace; font-size:12px; font-weight:600;
  padding:5px 12px; border-radius:999px; margin-top:6px;
}}
section[data-testid="stSidebar"] {{ background-color: {PAPER_DIM}; }}
.stButton>button[kind="primary"] {{
  background-color: {MAROON}; border-color: {MAROON};
}}
.stButton>button[kind="primary"]:hover {{
  background-color: {MAROON_DARK}; border-color: {MAROON_DARK};
}}
div[data-testid="stMetric"] {{
  background: {GOLD_SOFT}; border: 1px solid {GOLD}; border-radius: 8px; padding: 10px 14px;
}}
hr {{ border-color: {LINE}; }}
</style>
""", unsafe_allow_html=True)

st.markdown(f"""
<div class="ndcd-topbar">
  <h1>Journey Distance &amp; Fare Calculator</h1>
  <div class="sub">New Delhi Central Division · local road journeys within Delhi</div>
  <div class="ndcd-badge">RATE: ₹{RATE_PER_KM}/KM &nbsp;·&nbsp; MODE: BY ROAD</div>
</div>
""", unsafe_allow_html=True)

# -----------------------------------------------------------------------
# Session state
# -----------------------------------------------------------------------
if "journeys" not in st.session_state:
    st.session_state.journeys = []
for k in FORM_KEYS:
    if k not in st.session_state:
        st.session_state[k] = ""
if "last_calc" not in st.session_state:
    st.session_state.last_calc = None

# -----------------------------------------------------------------------
# Gemini client / API key
# -----------------------------------------------------------------------
def get_secret(name: str) -> str:
    """Read a value from Streamlit secrets, falling back to an environment variable.

    st.secrets raises if no secrets file exists (e.g. running locally), so guard it.
    """
    try:
        val = st.secrets.get(name)
    except Exception:
        val = None
    val = val or os.environ.get(name)
    return str(val).strip() if val else ""


@st.cache_data(ttl=3600, show_spinner=False)
def list_gemini_models(key: str) -> list:
    """Models that support generateContent, fetched live with the given key."""
    c = genai.Client(api_key=key)
    names = []
    for m in c.models.list():
        actions = getattr(m, "supported_actions", None) or []
        if "generateContent" in actions:
            names.append(m.name.removeprefix("models/"))
    return sorted(set(names))


secret_key = get_secret("GEMINI_API_KEY")

with st.sidebar:
    st.markdown("### Gemini API key")
    if secret_key:
        api_key = secret_key
        st.success("API key loaded from app secrets ✓")
    else:
        api_key = st.text_input("Paste your key", type="password", key="api_key_input",
                                 help="Get one free at https://aistudio.google.com/apikey")
        st.caption("To avoid typing this, add `GEMINI_API_KEY` under "
                   "**App settings → Secrets** — the app will then use it automatically.")

    # --- Model picker -----------------------------------------------------
    st.markdown("### Gemini model")
    default_model = get_secret("GEMINI_MODEL") or DEFAULT_GEMINI_MODEL
    model_options = list(FALLBACK_MODELS)
    if api_key:
        try:
            live = list_gemini_models(api_key)
            # keep only text/multimodal Gemini models; drop embeddings, imagen, etc.
            live = [m for m in live if m.startswith("gemini") and "embedding" not in m]
            if live:
                model_options = live
        except Exception:
            pass  # fall back to the static list
    if default_model not in model_options:
        model_options.insert(0, default_model)
    model_options = model_options + [CUSTOM_MODEL_LABEL]

    choice = st.selectbox("Model", model_options, index=model_options.index(default_model),
                          key="model_choice",
                          help="Used for voice, photo and distance estimation.")
    if choice == CUSTOM_MODEL_LABEL:
        GEMINI_MODEL = st.text_input("Model name", value=default_model, key="model_custom").strip() \
            or default_model
    else:
        GEMINI_MODEL = choice
    st.markdown("---")
    st.caption("Distances are AI-estimated road distances within Delhi. "
               "Review each entry before exporting for reimbursement.")

client = genai.Client(api_key=api_key) if api_key else None


def strip_fence(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw
        if raw.endswith("```"):
            raw = raw[:-3]
        if raw.lower().startswith("json"):
            raw = raw[4:]
    return raw.strip()


def json_call(contents):
    resp = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=contents,
        config=types.GenerateContentConfig(response_mime_type="application/json"),
    )
    return json.loads(strip_fence(resp.text))


def dmy(iso_or_text: str) -> str:
    if not iso_or_text:
        return ""
    try:
        return datetime.strptime(iso_or_text.strip(), "%Y-%m-%d").strftime("%d/%m/%Y")
    except ValueError:
        return iso_or_text  # already DD/MM/YYYY or free text


def apply_extraction(result: dict):
    for k in ["from_place", "from_time", "to_place", "to_time", "remarks"]:
        v = result.get(k, "")
        if v:
            st.session_state[k] = v
    for k in ["from_date", "to_date"]:
        v = result.get(k, "")
        if v:
            st.session_state[k] = dmy(v)


EXTRACTION_SCHEMA_NOTE = (
    'Respond with ONLY raw JSON in exactly this shape (use "" for anything not found, '
    'times in 24-hour HH:MM, dates in ISO YYYY-MM-DD):\n'
    '{"from_place":"","from_date":"","from_time":"","to_place":"","to_date":"","to_time":"","remarks":""}'
)

# -----------------------------------------------------------------------
# Voice / Photo capture tabs
# -----------------------------------------------------------------------
tab_voice, tab_photo = st.tabs(["🎙️ Speak", "📷 Photo"])

with tab_voice:
    st.caption('Record something like: "From Karol Bagh to Sansad Marg on 20 August, '
               'left at 9 in the morning, back at 6 in the evening."')
    audio_value = st.audio_input("Record the journey")
    if audio_value is not None:
        if st.button("Extract from recording", key="extract_voice"):
            if client is None:
                st.warning("Add your Gemini API key in the sidebar first.")
            else:
                with st.spinner("Transcribing and extracting…"):
                    try:
                        today_iso = date.today().isoformat()
                        prompt = (
                            "Listen to this audio. A person is describing a local road journey "
                            "within Delhi, India, for a travel-reimbursement form.\n\n"
                            "Transcribe what they said, then extract the journey details.\n\n"
                            f"Today's date is {today_iso} (ISO format) — use this to resolve "
                            'relative or partial dates (e.g. "20 August" with no year, or '
                            '"today"/"yesterday"). If no date is mentioned at all, use today\'s date.\n\n'
                            + EXTRACTION_SCHEMA_NOTE
                        )
                        part = types.Part.from_bytes(data=audio_value.getvalue(), mime_type="audio/wav")
                        result = json_call([prompt, part])
                        apply_extraction(result)
                        st.success("Fields filled in below — please review before calculating.")
                    except Exception as e:
                        st.error(f"Could not parse the recording: {e}")

with tab_photo:
    uploaded = st.file_uploader("Upload a photo of a travel note/slip",
                                 type=["jpg", "jpeg", "png", "webp"])
    cam = st.camera_input("…or take a photo now")
    photo_file = uploaded or cam
    if photo_file is not None:
        st.image(photo_file, width=220)
        if st.button("Extract from photo", key="extract_photo"):
            if client is None:
                st.warning("Add your Gemini API key in the sidebar first.")
            else:
                with st.spinner("Reading photo…"):
                    try:
                        img = Image.open(photo_file)
                        today_iso = date.today().isoformat()
                        prompt = (
                            "This photo shows a note, slip, or screenshot describing a local "
                            "road journey within Delhi, India, for a travel-reimbursement form. "
                            "Read any text in the image (OCR) and extract the journey details.\n\n"
                            f"Today's date is {today_iso} (ISO format) — use this to resolve "
                            "relative or partial dates. If no date is found, use today's date.\n\n"
                            + EXTRACTION_SCHEMA_NOTE
                        )
                        result = json_call([prompt, img])
                        apply_extraction(result)
                        st.success("Fields filled in below — please review before calculating.")
                    except Exception as e:
                        st.error(f"Could not read the photo: {e}")

# -----------------------------------------------------------------------
# Shared form (type manually, or review/edit what voice/photo filled in)
# -----------------------------------------------------------------------
st.markdown("#### Journey details")

c1, c2, c3 = st.columns(3)
with c1:
    st.text_input("From place (Delhi)", key="from_place", placeholder="e.g. Karol Bagh SO")
    st.text_input("To place (Delhi)", key="to_place", placeholder="e.g. Sansad Marg HO")
with c2:
    st.text_input("From date (DD/MM/YYYY)", key="from_date", placeholder="20/08/2026")
    st.text_input("To date (DD/MM/YYYY)", key="to_date", placeholder="20/08/2026")
with c3:
    st.text_input("From time (HH:MM)", key="from_time", placeholder="09:00")
    st.text_input("To time (HH:MM)", key="to_time", placeholder="18:00")

st.text_input("Remarks (optional)", key="remarks", placeholder="e.g. Divisional inspection visit")
st.caption("Mode: **By Road** (fixed)")

col_calc, col_clear = st.columns([1, 1])
calc_clicked = col_calc.button("Calculate distance & fare", type="primary", use_container_width=True)
if col_clear.button("Clear form", use_container_width=True):
    for k in FORM_KEYS:
        st.session_state[k] = ""
    st.session_state.last_calc = None
    st.rerun()

if calc_clicked:
    if client is None:
        st.warning("Add your Gemini API key in the sidebar first.")
    elif not st.session_state.from_place or not st.session_state.to_place:
        st.error("Please enter both From and To locations.")
    elif not st.session_state.from_date or not st.session_state.to_date:
        st.error("Please enter both dates.")
    else:
        with st.spinner("Estimating road distance within Delhi…"):
            try:
                prompt = f"""You are a Delhi/NCR local geography and road-routing expert used inside a
government office reimbursement tool.

Two locations are given. Both must be within Delhi (NCT of Delhi) premises —
localities, roads, government offices, post offices, landmarks, or well-known
areas of Delhi.

FROM: "{st.session_state.from_place}"
TO: "{st.session_state.to_place}"

Task:
1. Decide if each location is plausibly within Delhi (not another city/state).
   If ambiguous, assume it is a locality/office within Delhi unless it clearly
   names another city.
2. Estimate a realistic one-way ROAD driving distance in kilometers between
   these two points, following typical road routes (not straight-line
   distance). Use your knowledge of Delhi's roads, ring roads, and localities.
3. Round the distance to the nearest whole kilometer, minimum 1.

Respond with ONLY raw JSON in exactly this shape:
{{"from_in_delhi": true, "to_in_delhi": true, "distance_km": 12, "note": ""}}

If either location does not appear to be in Delhi, set that field to false
and briefly explain in "note"."""
                result = json_call(prompt)
                if result.get("from_in_delhi") is False or result.get("to_in_delhi") is False:
                    st.error("⚠ " + (result.get("note")
                              or "One of the locations does not appear to be within Delhi."))
                    st.session_state.last_calc = None
                else:
                    distance = max(1, round(float(result.get("distance_km", 0))))
                    fare = round(distance * RATE_PER_KM)
                    st.session_state.last_calc = {"distance": distance, "fare": fare}
            except Exception as e:
                st.error(f"Could not estimate distance: {e}")
                st.session_state.last_calc = None

if st.session_state.last_calc:
    lc = st.session_state.last_calc
    m1, m2, m3 = st.columns([1, 1, 1.4])
    m1.metric("Distance", f"{lc['distance']} km")
    m2.metric("Fare", f"₹{lc['fare']}")
    with m3:
        st.write("")
        st.write("")
        if st.button("➕ Add to journey list", type="primary", use_container_width=True):
            entry = {
                "From Date": st.session_state.from_date,
                "From Time": st.session_state.from_time,
                "From Place": st.session_state.from_place,
                "To Date": st.session_state.to_date,
                "To Time": st.session_state.to_time,
                "To Place": st.session_state.to_place,
                "Mode": "By Road",
                "Distance (Km)": lc["distance"],
                "Fare Paid": lc["fare"],
                "Remarks": st.session_state.remarks,
            }
            st.session_state.journeys.append(entry)
            for k in FORM_KEYS:
                st.session_state[k] = ""
            st.session_state.last_calc = None
            st.rerun()

# -----------------------------------------------------------------------
# Journey list + export
# -----------------------------------------------------------------------
st.markdown("---")
st.markdown("#### Journey list")

if st.session_state.journeys:
    df = pd.DataFrame(st.session_state.journeys, columns=HEADERS)
    edited = st.data_editor(
        df, num_rows="dynamic", use_container_width=True, key="journey_editor",
        column_config={
            "Distance (Km)": st.column_config.NumberColumn(min_value=0, step=1),
            "Fare Paid": st.column_config.NumberColumn(min_value=0, step=1),
        },
    )
    st.session_state.journeys = edited.to_dict("records")

    total_dist = int(edited["Distance (Km)"].fillna(0).sum()) if len(edited) else 0
    total_fare = int(edited["Fare Paid"].fillna(0).sum()) if len(edited) else 0
    st.markdown(f"**Total: {total_dist} km · ₹{total_fare}**  "
                f"<span style='color:#6b6255;font-size:12px;'>(edit or delete rows directly in the table above)</span>",
                unsafe_allow_html=True)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "JourneyDetails"
    ws.append(HEADERS)
    header_fill = PatternFill(start_color="C8A24A", end_color="C8A24A", fill_type="solid")
    header_font = Font(bold=True, color="4A1319")
    for cell in ws[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center")
    for _, row in edited.iterrows():
        ws.append([row.get(h, "") for h in HEADERS])
    for i, w in enumerate([12, 10, 22, 12, 10, 22, 10, 14, 12, 30], start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    st.download_button(
        "⬇ Download Journey_Details.xlsx",
        data=buf,
        file_name=f"Journey_Details_{date.today().isoformat()}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary",
    )
else:
    st.info("No journeys added yet — calculate one above and add it to the list.")
