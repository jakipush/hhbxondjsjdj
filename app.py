"""
F1 + Firenze Air Radar — dashboard touch in Python
Avvio:
    pip install streamlit streamlit-folium folium requests pandas
    streamlit run f1_air_dashboard.py

Note:
- I dati aerei arrivano dall'API pubblica adsb.lol (internet necessario).
- I dati F1 arrivano dall'API OpenF1. La disponibilità dei tempi live dipende
  dalla sessione e dall'API; fuori da una sessione live vengono mostrati calendario
  e prossima sessione.
- Le API pubbliche possono cambiare o imporre limiti. Non è un sistema certificato.
"""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import math
import requests
import pandas as pd
import streamlit as st
import folium
from streamlit_folium import st_folium

ROME = ZoneInfo("Europe/Rome")
FLORENCE = (43.8099, 11.2051)  # Aeroporto di Firenze-Peretola (LIRQ)
RADIUS_NM = 80
RADIUS_KM = RADIUS_NM * 1.852
OPENF1 = "https://api.openf1.org/v1"
ADSBLOL = "https://api.adsb.lol/v2"

st.set_page_config(page_title="F1 + Radar Firenze", page_icon="🏁", layout="centered", initial_sidebar_state="collapsed")

# Touch-friendly styling
st.markdown("""
<style>
html, body, [class*="css"] { font-size: 16px; }
.stButton > button { min-height: 3.1rem; font-size: 1rem; border-radius: 14px; width: 100%; }
div[data-testid="stMetricValue"] { font-size: 1.45rem; }
.block-container { padding-top: 1rem; padding-bottom: 1.2rem; max-width: 100%; }
@media (max-width: 700px) { .block-container { padding-left: 0.8rem; padding-right: 0.8rem; } h1 { font-size: 1.6rem !important; } h2 { font-size: 1.35rem !important; } div[data-testid="stDataFrame"] { font-size: 0.8rem; } }
</style>
""", unsafe_allow_html=True)


def get_json(url, params=None, timeout=12):
    try:
        response = requests.get(url, params=params, timeout=timeout,
                                headers={"User-Agent": "F1-Air-Radar/1.0"})
        response.raise_for_status()
        return response.json()
    except (requests.RequestException, ValueError):
        return None


def local_time(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(ROME)
    except (ValueError, TypeError):
        return None


def fmt_countdown(target):
    if not target:
        return "Orario non disponibile"
    seconds = max(0, int((target - datetime.now(ROME).astimezone(target.tzinfo)).total_seconds()))
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    mins, secs = divmod(rem, 60)
    prefix = f"{days}g " if days else ""
    return f"{prefix}{hours:02d}:{mins:02d}:{secs:02d}"


def next_f1_session():
    """Restituisce la prossima sessione pubblicata da OpenF1, in orario italiano."""
    sessions = get_json(f"{OPENF1}/sessions", {"year": datetime.now(ROME).year})
    if not isinstance(sessions, list):
        return None, []
    now = datetime.now(ROME)
    upcoming = []
    for s in sessions:
        start = local_time(s.get("date_start"))
        if start and start >= now:
            s["_start_local"] = start
            upcoming.append(s)
    upcoming.sort(key=lambda s: s["_start_local"])
    return (upcoming[0] if upcoming else None), sessions


def fetch_live_f1():
    """Legge la sessione più recente e, quando disponibile, dati di posizione/intervallo."""
    sessions = get_json(f"{OPENF1}/sessions", {"session_key": "latest"})
    if not isinstance(sessions, list) or not sessions:
        return None, [], [], []
    session = sessions[-1]
    key = session.get("session_key")
    positions = get_json(f"{OPENF1}/position", {"session_key": key})
    intervals = get_json(f"{OPENF1}/intervals", {"session_key": key})
    drivers = get_json(f"{OPENF1}/drivers", {"session_key": key})
    return session, positions or [], intervals or [], drivers or []


def fetch_aircraft():
    lat, lon = FLORENCE
    data = get_json(f"{ADSBLOL}/lat/{lat}/lon/{lon}/dist/{RADIUS_KM}")
    if not isinstance(data, dict):
        return []
    aircraft = []
    for p in data.get("aircraft", []):
        plat, plon = p.get("lat"), p.get("lon")
        if plat is None or plon is None:
            continue
        aircraft.append({
            "hex": p.get("hex", "—"),
            "callsign": (p.get("flight") or "").strip() or "Sconosciuto",
            "lat": plat, "lon": plon,
            "altitude": p.get("alt_baro", p.get("alt_geom", "—")),
            "speed": p.get("gs", "—"),
            "track": p.get("track", "—"),
            "squawk": p.get("squawk", "—"),
            "registration": p.get("r", "—"),
            "type": p.get("t", "—"),
            "category": p.get("category", "—"),
            "seen": p.get("seen", "—"),
            "emergency": p.get("emergency", "—"),
        })
    return aircraft


def distance_nm(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2-lat1)
    dl = math.radians(lon2-lon1)
    a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return (2*r*math.asin(math.sqrt(a))) / 1.852


def aircraft_map(aircraft):
    m = folium.Map(location=FLORENCE, zoom_start=8, tiles="CartoDB dark_matter",
                   control_scale=True)
    folium.Circle(FLORENCE, radius=RADIUS_NM*1852, color="#33d6ff",
                  weight=2, fill=False, tooltip="Raggio 80 NM").add_to(m)
    folium.Marker(FLORENCE, tooltip="Aeroporto di Firenze-Peretola (LIRQ)",
                  icon=folium.Icon(color="red", icon="plane", prefix="fa")).add_to(m)
    for a in aircraft:
        alt = a["altitude"]
        alt_text = f"{alt:,} ft" if isinstance(alt, (int, float)) else str(alt)
        speed_text = f"{a['speed']} kt" if isinstance(a["speed"], (int, float)) else str(a["speed"])
        popup = folium.Popup(
            f"<b>{a['callsign']}</b><br>Tipo: {a['type']}<br>Registrazione: {a['registration']}"
            f"<br>Quota: {alt_text}<br>Velocità: {speed_text}<br>Hex: {a['hex']}",
            max_width=300)
        folium.Marker(
            [a["lat"], a["lon"]], tooltip=f"{a['callsign']} · {a['type']}",
            popup=popup,
            icon=folium.DivIcon(html=f"""<div style="font-size:22px;color:#42e8f5;
              text-shadow:0 0 5px #000;transform:rotate({(a['track'] if isinstance(a['track'], (int,float)) else 0)}deg)">✈</div>""")
        ).add_to(m)
    return m


def f1_map():
    """Mappa indicativa del circuito: la posizione live è mostrata nella tabella."""
    m = folium.Map(location=[46.5, 8.0], zoom_start=4, tiles="CartoDB dark_matter")
    folium.Marker([46.5, 8.0], tooltip="Mappa F1: seleziona una sessione live per i dati disponibili",
                  icon=folium.Icon(color="green", icon="flag-checkered", prefix="fa")).add_to(m)
    return m


st.title("🏁 F1 Timing  |  ✈ Radar aereo Firenze")
st.caption("Pannello touch · orari italiani · aggiornamento manuale con i pulsanti qui sotto")

if "screen" not in st.session_state:
    st.session_state.screen = "F1"

nav1, nav2, nav3 = st.columns([1, 1, 1])
with nav1:
    if st.button("🏁 FORMULA 1", use_container_width=True):
        st.session_state.screen = "F1"
with nav2:
    if st.button("✈ RADAR AEREO", use_container_width=True):
        st.session_state.screen = "AIR"
with nav3:
    if st.button("↻ AGGIORNA", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

st.divider()

if st.session_state.screen == "AIR":
    st.subheader("Radar aereo · Firenze-Peretola (LIRQ)")
    st.write(f"Area di copertura: **{RADIUS_NM} miglia nautiche** (circa {RADIUS_KM:.1f} km).")
    with st.spinner("Caricamento aeromobili…"):
        aircraft = fetch_aircraft()
    c1, c2, c3 = st.columns(3)
    c1.metric("Aeromobili rilevati", len(aircraft))
    c2.metric("Raggio", "80 NM")
    c3.metric("Ultimo aggiornamento", datetime.now(ROME).strftime("%H:%M:%S"))
    st_folium(aircraft_map(aircraft), height=560, use_container_width=True,
              returned_objects=[], key="air_map")
    st.markdown("### Aeromobili nell'area")
    if aircraft:
        rows = []
        for a in aircraft:
            d = distance_nm(FLORENCE[0], FLORENCE[1], a["lat"], a["lon"])
            alt = a["altitude"]
            rows.append({
                "Volo / callsign": a["callsign"], "Tipo": a["type"],
                "Compagnia": "Non sempre disponibile via ADS-B",
                "Registrazione": a["registration"], "Quota (ft)": alt,
                "Velocità al suolo (kt)": a["speed"], "Direzione (°)": a["track"],
                "Distanza da Firenze (NM)": round(d, 1), "ICAO hex": a["hex"],
                "Squawk": a["squawk"]
            })
        df = pd.DataFrame(rows).sort_values("Distanza da Firenze (NM)")
        st.dataframe(df, use_container_width=True, hide_index=True)
        st.info("Tocca un simbolo ✈ sulla mappa per aprire i dettagli rapidi. La compagnia aerea non è garantita dai dati ADS-B: il callsign può aiutare a identificarla.")
    else:
        st.warning("Nessun aeromobile disponibile o servizio temporaneamente non raggiungibile. Premi AGGIORNA tra poco.")
    st.caption("Fonte: adsb.lol. Copertura e completezza dipendono dai ricevitori e dalla disponibilità del servizio.")

else:
    st.subheader("Formula 1 · calendario e tempi")
    with st.spinner("Recupero calendario e dati sessione…"):
        next_session, all_sessions = next_f1_session()
        live_session, positions, intervals, drivers = fetch_live_f1()

    if next_session:
        start = next_session["_start_local"]
        st.markdown(f"### Prossima sessione: {next_session.get('session_name', 'Sessione F1')}")
        a, b, c = st.columns(3)
        a.metric("Countdown", fmt_countdown(start))
        b.metric("Data", start.strftime("%d/%m/%Y"))
        c.metric("Ora italiana", start.strftime("%H:%M"))
        st.write(f"**Gran premio:** {next_session.get('meeting_name', '—')} · **Circuito:** {next_session.get('circuit_short_name', '—')}")
    else:
        st.warning("Calendario non disponibile oppure nessuna sessione futura trovata dall'API.")

    st.markdown("### Sessione più recente disponibile")
    if live_session:
        start = local_time(live_session.get("date_start"))
        st.write(f"**{live_session.get('meeting_name', 'Gran Premio')}** — {live_session.get('session_name', 'Sessione')}"
                 + (f" · iniziata {start.strftime('%d/%m %H:%M')} (ora italiana)" if start else ""))
        if positions:
            latest = {}
            for p in positions:
                num = p.get("driver_number")
                t = local_time(p.get("date"))
                if num is not None and (num not in latest or (t and t > latest[num].get("_time", t))):
                    p["_time"] = t
                    latest[num] = p
            int_latest = {}
            for item in intervals:
                num = item.get("driver_number")
                t = local_time(item.get("date"))
                if num is not None and (num not in int_latest or (t and t > int_latest[num].get("_time", t))):
                    item["_time"] = t
                    int_latest[num] = item
            driver_lookup = {d.get("driver_number"): d for d in drivers}
            rows = []
            for num, p in latest.items():
                d = driver_lookup.get(num, {})
                gap = int_latest.get(num, {}).get("gap_to_leader", "—")
                rows.append({
                    "Pos.": p.get("position", "—"),
                    "Pilota": d.get("full_name", d.get("name_acronym", str(num))),
                    "Team": d.get("team_name", "—"),
                    "Numero": num,
                    "Gap leader": gap,
                    "Ultimo aggiornamento": p.get("_time").strftime("%H:%M:%S") if p.get("_time") else "—"
                })
            table = pd.DataFrame(rows)
            if not table.empty:
                table = table.sort_values("Pos.")
                st.dataframe(table, use_container_width=True, hide_index=True)
            st.caption("Le posizioni e i gap sono gli ultimi valori disponibili dall'API, non necessariamente una classifica ufficiale in tempo reale.")
        else:
            st.info("Al momento l'API non restituisce posizioni live per questa sessione. Durante una sessione attiva riprova con AGGIORNA.")
    else:
        st.info("Dati di sessione non disponibili. Il calendario e il countdown possono comunque essere visualizzati se l'API risponde.")

    st.markdown("### Calendario del weekend")
    if isinstance(all_sessions, list) and all_sessions:
        future_rows = []
        for s in all_sessions:
            dt = local_time(s.get("date_start"))
            if dt:
                future_rows.append({
                    "Data": dt.strftime("%d/%m/%Y"),
                    "Ora italiana": dt.strftime("%H:%M"),
                    "Sessione": s.get("session_name", "—"),
                    "Gran Premio": s.get("meeting_name", "—"),
                    "Circuito": s.get("circuit_short_name", "—")
                })
        if future_rows:
            st.dataframe(pd.DataFrame(future_rows), use_container_width=True, hide_index=True)
    st.markdown("### Mappa")
    st.caption("La traccia del circuito e le posizioni GPS dei piloti richiedono i dati specifici della sessione selezionata. Questa prima versione mostra timing e calendario quando l'API li rende disponibili.")
    st_folium(f1_map(), height=300, use_container_width=True, returned_objects=[], key="f1_map")

st.divider()
st.caption("Prototipo non ufficiale. Non affiliato a Formula 1, FIA o aeroporti. Richiede una connessione internet.")
