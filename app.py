import streamlit as st
import requests
import google.generativeai as genai

# Configurer la page Streamlit
st.set_page_config(
    page_title="Coach IA Running & Trail",
    page_icon="🏃‍♂️",
    layout="wide"
)

# ---------------------------------------------------------
# CONFIGURATION & CLEFS API
# ---------------------------------------------------------
# Récupération depuis les secrets Streamlit Cloud
INTERVALS_API_KEY = st.secrets.get("INTERVALS_API_KEY", "")
INTERVALS_ATHLETE_ID = st.secrets.get("INTERVALS_ATHLETE_ID", "")
GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY", "")

# Validation de la présence des clés
if not all([INTERVALS_API_KEY, INTERVALS_ATHLETE_ID, GEMINI_API_KEY]):
    st.error("⚠️ Il manque une ou plusieurs clés API dans les secrets Streamlit (`INTERVALS_API_KEY`, `INTERVALS_ATHLETE_ID`, `GEMINI_API_KEY`).")
    st.stop()

# Configuration du SDK Gemini
genai.configure(api_key=GEMINI_API_KEY)


# ---------------------------------------------------------
# FONCTIONS APIS INTERVALS.ICU
# ---------------------------------------------------------
def get_recent_activities(oldest_date_iso):
    """Récupère la liste des activités depuis une date ISO (ex: YYYY-MM-DD)."""
    url = f"https://intervals.icu/api/v1/athlete/{INTERVALS_ATHLETE_ID}/activities?oldest={oldest_date_iso}"
    try:
        res = requests.get(url, auth=('API_KEY', INTERVALS_API_KEY))
        if res.status_code == 200:
            return res.json()
        else:
            st.error(f"Erreur d'accès à l'API Intervals.icu ({res.status_code})")
            return None
    except Exception as e:
        st.error(f"Exception lors de la connexion à Intervals.icu : {e}")
        return None


def get_activity_streams(activity_id):
    """
    Récupère les streams d'une activité.
    Transforme la liste d'objets [{'type': 'heartrate', 'data': [...]}, ...] 
    en dictionnaire {'heartrate': [...], 'watts': [...]}.
    """
    keys = "time,heartrate,watts,cadence,altitude,velocity_smooth"
    url = f"https://intervals.icu/api/v1/activity/{activity_id}/streams?keys={keys}"
    try:
        res = requests.get(url, auth=('API_KEY', INTERVALS_API_KEY))
        if res.status_code == 200:
            raw_streams = res.json()
            # Si l'API renvoie une liste d'objets par type de stream
            if isinstance(raw_streams, list):
                return {s.get('type'): s.get('data', []) for s in raw_streams if isinstance(s, dict) and 'type' in s}
            # Si l'API renvoie déjà un dictionnaire
            elif isinstance(raw_streams, dict):
                return raw_streams
        return None
    except Exception as e:
        st.warning(f"Impossible de récupérer les streams pour l'activité {activity_id} : {e}")
        return None


# ---------------------------------------------------------
# INTERFACE UTILISATEUR STREAMLIT
# ---------------------------------------------------------
st.title("🏃‍♂️ Coach IA Running & Trail")
st.write("Analyse automatique de tes données d'entraînement via **Intervals.icu** et **Google Gemini**.")

# Barre latérale de configuration des paramètres
with st.sidebar:
    st.header("Paramètres")
    start_date = st.date_input("Date de début des données", value=None, help="Sélectionne la période d'analyse")
    
    analysis_type = st.radio(
        "Mode d'analyse",
        options=["Vue d'ensemble de la période", "Focus sur une séance spécifique"]
    )

if not start_date:
    st.info("💡 Choisis une date de début dans la barre latérale pour lancer la récupération des données.")
    st.stop()

# Conversion de la date au format ISO
start_date_iso = start_date.strftime("%Y-%m-%d")

with st.spinner("Récupération des données depuis Intervals.icu..."):
    activities = get_recent_activities(start_date_iso)

if activities is None:
    st.stop()

if not activities:
    st.warning("Aucune activité trouvée sur la période sélectionnée.")
    st.stop()

st.success(f"{len(activities)} activité(s) chargée(s) avec succès !")

# ---------------------------------------------------------
# CONSTRUCTION DU PROMPT GEMINI
# ---------------------------------------------------------
system_prompt = (
    "Tu es un entraîneur expert en course à pied, semi-marathon, marathon et trail de montagne. "
    "Tu analyses les données brutes fournies et rédiges une synthèse claire, structurée et bienveillante "
    "avec des conseils concréts, des alertes de surentraînement ou des encouragements."
)

prompt_context = ""

if analysis_type == "Vue d'ensemble de la période":
    summary_list = []
    for act in activities:
        name = act.get('name', 'Sans titre')
        type_act = act.get('type', 'Inconnu')
        start = act.get('start_date_local', '')[:10]
        dist_km = act.get('distance', 0) / 1000.0
        dur_min = act.get('moving_time', 0) / 60.0
        hr_avg = act.get('average_heartrate', 'N/A')
        d_plus = act.get('total_elevation_gain', 0)
        ic_load = act.get('icu_training_load', 'N/A')
        
        summary_list.append(
            f"- {start} | {name} ({type_act}) : {dist_km:.2f} km, {dur_min:.0f} min, "
            f"D+ {d_plus}m, FC moy {hr_avg} bpm, Load {ic_load}"
        )
    
    activities_str = "\n".join(summary_list)
    prompt_context = (
        f"Voici le récapitulatif des séances de l'athlète depuis le {start_date_iso} :\n\n"
        f"{activities_str}\n\n"
        "Fais un bilan global du volume, de la charge d'entraînement et de la répartition du dénivelé."
    )

else:
    # Mode séance spécifique
    act_titles = [f"{a.get('start_date_local', '')[:10]} - {a.get('name', 'Sans titre')}" for a in activities]
    selected_act_idx = st.selectbox("Sélectionne la séance à analyser en détail :", range(len(activities)), format_func=lambda i: act_titles[i])
    
    act = activities[selected_act_idx]
    act_id = act.get('id')
    
    name = act.get('name', 'Sans titre')
    type_act = act.get('type', 'Inconnu')
    start = act.get('start_date_local', '')[:10]
    dist_km = act.get('distance', 0) / 1000.0
    dur_min = act.get('moving_time', 0) / 60.0
    hr_avg = act.get('average_heartrate', 'N/A')
    d_plus = act.get('total_elevation_gain', 0)
    ic_load = act.get('icu_training_load', 'N/A')
    
    # Récupération des streams
    streams = get_activity_streams(act_id)
    streams_summary = ""
    
    if streams:
        # Filtrage des valeurs None dans les listes de streams
        hr_data = [x for x in streams.get('heartrate', []) if x is not None]
        watts_data = [x for x in streams.get('watts', []) if x is not None]
        cad_data = [x for x in streams.get('cadence', []) if x is not None]
        alt_data = [x for x in streams.get('altitude', []) if x is not None]
        
        extra_metrics = []
        if hr_data:
            max_hr = max(hr_data)
            min_hr = min(hr_data)
            half = len(hr_data) // 2
            avg_hr_h1 = sum(hr_data[:half]) / half if half > 0 else 0
            avg_hr_h2 = sum(hr_data[half:]) / (len(hr_data) - half) if half > 0 else 0
            drift = avg_hr_h2 - avg_hr_h1
            extra_metrics.append(f"- FC min/max : {min_hr} / {max_hr} bpm")
            extra_metrics.append(f"- Dérive cardiaque estimée (2e moitié - 1ère moitié) : {drift:+.1f} bpm")
        
        if watts_data:
            max_w = max(watts_data)
            avg_w = sum(watts_data) / len(watts_data)
            extra_metrics.append(f"- Puissance moy/max : {avg_w:.0f} W / {max_w} W")
            
        if cad_data:
            avg_cad = sum(cad_data) / len(cad_data)
            extra_metrics.append(f"- Cadence moyenne : {avg_cad:.0f} spm")
        
        if alt_data and len(alt_data) > 1:
            d_plus_stream = sum(max(0, alt_data[i] - alt_data[i-1]) for i in range(1, len(alt_data)))
            extra_metrics.append(f"- Dénivelé positif calculé sur les streams : {d_plus_stream:.0f} m")
        
        streams_summary = "\n".join(extra_metrics)

    prompt_context = (
        f"Voici le détail d'une séance spécifique :\n"
        f"Nom: {name}\nType: {type_act}\nDate: {start}\n"
        f"Distance: {dist_km:.2f} km\nDurée: {dur_min:.0f} min\n"
        f"D+: {d_plus}m\nFC moyenne: {hr_avg} bpm\nCharge (Load): {ic_load}\n\n"
        f"Métriques détaillées extraites des streams :\n{streams_summary if streams_summary else 'Pas de données de streams disponibles.'}\n\n"
        "Analyse cette séance en détails (gestion d'allure, dérive cardiaque, adaptations recommandées)."
    )

# ---------------------------------------------------------
# APPEL À L'API GEMINI & AFFICHAGE
# ---------------------------------------------------------
if st.button("🚀 Lancer l'analyse du Coach IA", type="primary"):
    with st.spinner("Le coach analyse tes données..."):
        try:
            model = genai.GenerativeModel("gemini-1.5-pro")
            full_prompt = f"{system_prompt}\n\n{prompt_context}"
            
            response = model.generate_content(full_prompt)
            
            st.markdown("### 📋 Analyse du Coach")
            st.markdown(response.text)
            
        except Exception as e:
            st.error(f"Erreur lors de la génération de l'analyse avec Gemini : {e}")
