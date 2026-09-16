import gzip
import json
import os
from datetime import date, datetime, timedelta

import pandas as pd
import requests
import streamlit as st
from google import genai
from google.genai import types

st.set_page_config(page_title="Coach IA – Intervals.icu", page_icon="🏃", layout="wide")

# ---------------------------------------------------------------- Config
INTERVALS_API_KEY = st.secrets["INTERVALS_API_KEY"]
ATHLETE_ID = st.secrets["ATHLETE_ID"]
GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]

BASE = "https://intervals.icu/api/v1"
AUTH = ("API_KEY", INTERVALS_API_KEY)  # intervals.icu : user = "API_KEY", password = la clé
MEMORY_FILE = "memoire_coach.json"
MAX_HIST = 20  # nb d'échanges passés renvoyés à l'IA

CHAMPS_SEANCE = [
    "name", "type", "start_date_local", "distance", "moving_time", "elapsed_time",
    "total_elevation_gain", "average_speed", "max_speed", "average_heartrate",
    "max_heartrate", "average_cadence", "icu_average_watts", "icu_weighted_avg_watts",
    "icu_ftp", "icu_training_load", "icu_intensity", "trimp", "calories",
    "icu_hr_zone_times", "icu_zone_times", "perceived_exertion", "feel", "description",
]
CHAMPS_INTERVALLE = [
    "type", "label", "moving_time", "distance", "average_speed", "average_heartrate",
    "max_heartrate", "average_watts", "average_cadence", "total_elevation_gain",
]
STREAMS = ["time", "distance", "heartrate", "watts", "cadence", "velocity_smooth", "altitude"]


# ---------------------------------------------------------------- Utilitaires
def fmt_duree(s):
    if not s:
        return "-"
    h, r = divmod(int(s), 3600)
    m, sec = divmod(r, 60)
    return f"{h}h{m:02d}" if h else f"{m}min{sec:02d}"


def fmt_allure(v):
    if not v:
        return "-"
    p = 1000 / v
    return f"{int(p // 60)}:{int(p % 60):02d}/km"


def est_course(t):
    return "Run" in (t or "")


def est_velo(t):
    return "Ride" in (t or "")


def resume_court(a):
    t = a.get("type", "?")
    parts = [
        (a.get("start_date_local") or "")[:16].replace("T", " "),
        t,
        a.get("name", ""),
        f"{(a.get('distance') or 0) / 1000:.1f} km",
        fmt_duree(a.get("moving_time")),
    ]
    if a.get("average_heartrate"):
        parts.append(f"FC moy {a['average_heartrate']:.0f}")
    if est_course(t):
        parts.append(fmt_allure(a.get("average_speed")))
    elif a.get("icu_average_watts"):
        parts.append(f"{a['icu_average_watts']:.0f} W")
    if a.get("total_elevation_gain"):
        parts.append(f"D+ {a['total_elevation_gain']:.0f} m")
    if a.get("icu_training_load"):
        parts.append(f"charge {a['icu_training_load']}")
    return " | ".join(str(p) for p in parts)


# ---------------------------------------------------------------- Intervals.icu
def _get(path, **params):
    r = requests.get(f"{BASE}{path}", auth=AUTH, params=params, timeout=60)
    r.raise_for_status()
    return r


@st.cache_data(ttl=600)
def get_activities(oldest, newest):
    return _get(f"/athlete/{ATHLETE_ID}/activities", oldest=oldest, newest=newest).json()


@st.cache_data(ttl=3600)
def get_detail(act_id):
    return _get(f"/activity/{act_id}", intervals="true").json()


@st.cache_data(ttl=3600)
def get_streams(act_id):
    try:
        data = _get(f"/activity/{act_id}/streams", types=",".join(STREAMS)).json()
    except requests.HTTPError:
        return pd.DataFrame()
    cols = {s["type"]: pd.Series(s["data"]) for s in data if s.get("type") in STREAMS and s.get("data")}
    return pd.DataFrame(cols)


@st.cache_data(ttl=3600)
def get_fichier_original(act_id):
    try:
        contenu = _get(f"/activity/{act_id}/file").content
    except requests.HTTPError:
        return None
    if contenu[:2] == b"\x1f\x8b":  # gzip
        contenu = gzip.decompress(contenu)
    return contenu


def streams_agreges(df):
    """Réduit les streams à ~300 lignes pour limiter les tokens envoyés à Gemini."""
    if df.empty or "time" not in df:
        return "Pas de streams disponibles."
    d = df.dropna(subset=["time"]).copy()
    pas = max(10, int(d["time"].max() // 300) + 1)
    d["t_s"] = (d["time"] // pas * pas).astype(int)
    cols = [c for c in STREAMS if c in d and c != "time"]
    return d.groupby("t_s")[cols].mean().round(1).to_csv()


def contexte_seance(act_id):
    a = get_detail(act_id)
    infos = {k: a.get(k) for k in CHAMPS_SEANCE if a.get(k) not in (None, "", [])}
    intervalles = [
        {k: i.get(k) for k in CHAMPS_INTERVALLE if i.get(k) is not None}
        for i in (a.get("icu_intervals") or [])
    ]
    return (
        f"### Séance {act_id}\n"
        f"Résumé : {resume_court(a)}\n"
        f"Données : {json.dumps(infos, ensure_ascii=False, default=str)}\n"
        f"Intervalles : {json.dumps(intervalles, ensure_ascii=False, default=str)}\n"
        f"Streams agrégés (vitesse en m/s, distance en m) :\n{streams_agreges(get_streams(act_id))}"
    )


# ---------------------------------------------------------------- Mémoire
def charger_memoire():
    if os.path.exists(MEMORY_FILE):
        with open(MEMORY_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {"seances": {}, "echanges": []}


def sauver_memoire(mem):
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(mem, f, ensure_ascii=False, indent=2)


if "mem" not in st.session_state:
    st.session_state.mem = charger_memoire()
mem = st.session_state.mem


# ---------------------------------------------------------------- Gemini
@st.cache_resource
def client_gemini():
    return genai.Client(api_key=GEMINI_API_KEY)


def demander(question, ids, modele):
    seances_memo = "\n".join(f"- {v}" for v in mem["seances"].values()) or "aucune"
    system = (
        "Tu es un coach expert en course à pied et en cyclisme. Tu analyses des données "
        "issues d'intervals.icu (FC, puissance, allure, cadence, intervalles, charge). "
        "Réponds en français, de façon concise et chiffrée, et compare avec les séances "
        "passées quand c'est pertinent.\n\n"
        f"Séances déjà analysées (mémoire) :\n{seances_memo}"
    )
    contents = []
    for e in mem["echanges"][-MAX_HIST:]:
        seances = ", ".join(e["seances"]) or "aucune"
        contents.append({"role": "user", "parts": [{"text": f"[{e['date']}] (séances {seances}) {e['question']}"}]})
        contents.append({"role": "model", "parts": [{"text": e["reponse"]}]})

    ctx = "\n\n".join(contexte_seance(i) for i in ids) or "Aucune séance sélectionnée."
    contents.append({"role": "user", "parts": [{"text": f"Séances sélectionnées :\n{ctx}\n\nQuestion : {question}"}]})

    rep = client_gemini().models.generate_content(
        model=modele,
        contents=contents,
        config=types.GenerateContentConfig(system_instruction=system, temperature=0.4),
    )
    return rep.text or "(réponse vide)"


# ---------------------------------------------------------------- Sidebar
with st.sidebar:
    st.header("⚙️ Filtres")
    plage = st.date_input("Période", (date.today() - timedelta(days=7), date.today()))
    debut, fin = (plage[0], plage[-1]) if isinstance(plage, (list, tuple)) else (plage, plage)
    sport = st.radio("Sport", ["Tous", "Course", "Vélo"], horizontal=True)
    modele = st.text_input("Modèle Gemini", "gemini-2.5-flash")

    st.header("🧠 Mémoire")
    st.caption(f"{len(mem['seances'])} séances · {len(mem['echanges'])} échanges")
    st.download_button(
        "💾 Sauvegarder la mémoire",
        json.dumps(mem, ensure_ascii=False, indent=2),
        file_name="memoire_coach.json",
        mime="application/json",
    )
    upload = st.file_uploader("Restaurer une sauvegarde", type="json")
    if upload and st.button("Restaurer"):
        st.session_state.mem = json.load(upload)
        sauver_memoire(st.session_state.mem)
        st.rerun()
    if st.button("🗑️ Effacer la mémoire"):
        st.session_state.mem = {"seances": {}, "echanges": []}
        sauver_memoire(st.session_state.mem)
        st.rerun()

# ---------------------------------------------------------------- Récupération
st.title("🏃🚴 Coach IA – Intervals.icu")

try:
    activites = get_activities(debut.isoformat(), fin.isoformat())
except requests.HTTPError as e:
    st.error(f"Erreur intervals.icu : {e}")
    st.stop()

bloquees = [a for a in activites if a.get("_note")]
activites = [a for a in activites if not a.get("_note")]
if bloquees:
    st.warning(
        f"{len(bloquees)} activité(s) importée(s) depuis Strava ne sont pas accessibles via l'API. "
        "Synchronise Garmin/Wahoo directement avec intervals.icu pour les récupérer."
    )
if sport == "Course":
    activites = [a for a in activites if est_course(a.get("type"))]
elif sport == "Vélo":
    activites = [a for a in activites if est_velo(a.get("type"))]

labels = {str(a["id"]): resume_court(a) for a in activites}

# Nettoie la sélection si la période a changé
if "selection" in st.session_state:
    st.session_state.selection = [i for i in st.session_state.selection if i in labels]

selection = st.multiselect(
    "Séances à analyser",
    options=list(labels),
    format_func=labels.get,
    key="selection",
    placeholder="Choisis une ou plusieurs séances",
)

tab_seances, tab_coach, tab_memoire = st.tabs(["📊 Séances", "💬 Coach IA", "🧠 Mémoire"])

# ---------------------------------------------------------------- Onglet séances
with tab_seances:
    if not selection:
        st.info("Sélectionne au moins une séance ci-dessus.")
    for act_id in selection:
        a = get_detail(act_id)
        with st.expander(resume_court(a), expanded=len(selection) == 1):
            c = st.columns(5)
            c[0].metric("Distance", f"{(a.get('distance') or 0) / 1000:.2f} km")
            c[1].metric("Durée", fmt_duree(a.get("moving_time")))
            c[2].metric("FC moy", f"{a.get('average_heartrate') or 0:.0f} bpm")
            if est_course(a.get("type")):
                c[3].metric("Allure", fmt_allure(a.get("average_speed")))
            else:
                c[3].metric("Puissance", f"{a.get('icu_average_watts') or 0:.0f} W")
            c[4].metric("Charge", a.get("icu_training_load") or "-")

            df = get_streams(act_id)
            if not df.empty and "time" in df:
                dispo = [x for x in STREAMS if x in df and x not in ("time", "distance")]
                courbes = st.multiselect("Courbes", dispo, default=dispo[:1], key=f"c_{act_id}")
                if courbes:
                    st.line_chart(df.set_index("time")[courbes])

            if a.get("icu_intervals"):
                st.dataframe(
                    pd.DataFrame(a["icu_intervals"])[
                        [k for k in CHAMPS_INTERVALLE if k in pd.DataFrame(a["icu_intervals"])]
                    ],
                    use_container_width=True,
                )

            d1, d2 = st.columns(2)
            if not df.empty:
                d1.download_button(
                    "⬇️ Streams (CSV)", df.to_csv(index=False),
                    file_name=f"{act_id}_streams.csv", key=f"csv_{act_id}",
                )
            fichier = get_fichier_original(act_id)
            if fichier:
                d2.download_button(
                    "⬇️ Fichier original", fichier,
                    file_name=f"{act_id}.{a.get('file_type') or 'fit'}", key=f"fit_{act_id}",
                )

# ---------------------------------------------------------------- Onglet coach
with tab_coach:
    for e in mem["echanges"][-MAX_HIST:]:
        with st.chat_message("user"):
            st.caption(f"{e['date']} · séances : {', '.join(e['seances']) or 'aucune'}")
            st.markdown(e["question"])
        with st.chat_message("assistant"):
            st.markdown(e["reponse"])

    question = st.chat_input("Pose ta question sur les séances sélectionnées…")
    if question:
        with st.chat_message("user"):
            st.markdown(question)
        with st.chat_message("assistant"):
            with st.spinner("Analyse en cours…"):
                try:
                    reponse = demander(question, selection, modele)
                except Exception as e:
                    st.error(f"Erreur Gemini : {e}")
                    st.stop()
            st.markdown(reponse)

        for act_id in selection:
            mem["seances"][act_id] = resume_court(get_detail(act_id))
        mem["echanges"].append({
            "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "seances": selection,
            "question": question,
            "reponse": reponse,
        })
        sauver_memoire(mem)

# ---------------------------------------------------------------- Onglet mémoire
with tab_memoire:
    if mem["seances"]:
        st.dataframe(
            pd.DataFrame([{"id": k, "résumé": v} for k, v in mem["seances"].items()]),
            use_container_width=True, hide_index=True,
        )
    else:
        st.info("Aucune séance mémorisée pour l'instant.")
