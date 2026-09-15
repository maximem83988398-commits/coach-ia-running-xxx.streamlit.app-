import streamlit as st
import requests
from google import genai
from datetime import datetime, timedelta

# 1. Configuration de la page
st.set_page_config(
    page_title="Coach IA - Running & Cyclisme",
    page_icon="🏃‍♂️",
    layout="centered"
)

st.title("🏃‍♂️ Mon Coach IA sur Mesure")

# 2. Clés d'accès
try:
    INTERVALS_API_KEY = st.secrets["INTERVALS_API_KEY"]
    ATHLETE_ID = st.secrets["ATHLETE_ID"]
    GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
except Exception:
    st.error("Clés d'API manquantes dans les Secrets Streamlit.")
    st.stop()

client = genai.Client(api_key=GEMINI_API_KEY)
MODEL_NAME = "gemini-3.6-flash"

# Fonction pour récupérer la liste des activités
def get_activities(oldest_str, newest_str=None):
    url = f"https://intervals.icu/api/v1/athlete/{ATHLETE_ID}/activities?oldest={oldest_str}"
    if newest_str:
        url += f"&newest={newest_str}"
    res = requests.get(url, auth=('API_KEY', INTERVALS_API_KEY))
    if res.status_code == 200:
        return res.json()
    return None

# Fonction pour récupérer les streams seconde par seconde d'une séance
def get_activity_streams(activity_id):
    keys = "time,heartrate,watts,cadence,altitude,velocity_smooth"
    url = f"https://intervals.icu/api/v1/activity/{activity_id}/streams?keys={keys}"
    res = requests.get(url, auth=('API_KEY', INTERVALS_API_KEY))
    if res.status_code == 200:
        return res.json()
    return None

# Fonction pour récupérer le fichier brut (.fit / .gpx)
def get_activity_file(activity_id):
    url = f"https://intervals.icu/api/v1/activity/{activity_id}/file"
    res = requests.get(url, auth=('API_KEY', INTERVALS_API_KEY))
    if res.status_code == 200:
        return res.content
    return None

# 3. Choix du mode d'analyse
mode = st.radio(
    "Période à analyser :",
    ["Une séance spécifique", "Une semaine complète", "30 derniers jours"],
    horizontal=True
)

st.divider()

# --- MODE 1 : SÉANCE SPÉCIFIQUE ---
if mode == "Une séance spécifique":
    st.subheader("📅 Sélectionner et analyser une séance")
    
    selected_date = st.date_input("Date de la séance", datetime.now())
    date_str = selected_date.strftime("%Y-%m-%d")
    
    activities = get_activities(date_str, date_str)
    
    if activities is not None:
        if len(activities) == 0:
            st.warning("Aucune activité enregistrée à cette date.")
        else:
            act_options = {f"{a.get('name')} ({a.get('type')}) - {a.get('distance', 0)/1000:.1f} km": a for a in activities}
            chosen_label = st.selectbox("Sélectionne l'activité :", list(act_options.keys()))
            act = act_options[chosen_label]
            act_id = act.get('id')
            
            dist_km = act.get('distance', 0) / 1000
            duration_min = act.get('moving_time', 0) // 60
            
            st.info(f"**{act.get('name')}** | {act.get('type')} | {dist_km:.2f} km en {duration_min} min | Charge: {act.get('icu_training_load', 'N/A')}")
            
            # Bouton de téléchargement du fichier brut (.fit)
            raw_file = get_activity_file(act_id)
            if raw_file:
                st.download_button(
                    label="📥 Télécharger le fichier brut d'origine (.fit)",
                    data=raw_file,
                    file_name=f"seance_{act_id}.fit",
                    mime="application/octet-stream"
                )
            
            # Extraction des streams (données seconde par seconde)
            streams_summary = ""
            streams = get_activity_streams(act_id)
            
            if streams:
                hr_data = streams.get('heartrate', [])
                watts_data = streams.get('watts', [])
                cad_data = streams.get('cadence', [])
                alt_data = streams.get('altitude', [])
                
                # Exemples de métriques calculées sur les données brutes :
                extra_metrics = []
                if hr_data:
                    max_hr = max(hr_data)
                    min_hr = min(hr_data)
                    # Calcul de dérive cardiaque (comparaison 1ère moitié vs 2ème moitié)
                    half = len(hr_data) // 2
                    avg_hr_h1 = sum(hr_data[:half]) / half if half > 0 else 0
                    avg_hr_h2 = sum(hr_data[half:]) / (len(hr_data) - half) if half > 0 else 0
                    drift = avg_hr_h2 - avg_hr_h1
                    extra_metrics.append(f"- FC min/max : {min_hr} / {max_hr} bpm")
                    extra_metrics.append(f"- Dérive cardiaque (2e moitié - 1ere moitié) : {drift:+.1f} bpm")
                
                if watts_data:
                    max_w = max(watts_data)
                    extra_metrics.append(f"- Puissance max enregistrée : {max_w} W")
                
                if alt_data:
                    d_plus = sum(max(0, alt_data[i] - alt_data[i-1]) for i in range(1, len(alt_data)))
                    extra_metrics.append(f"- Dénivelé positif calculé sur le stream : {d_plus:.0f} m")
                
                streams_summary = "\n".join(extra_metrics)
            
            default_prompt = f"""Tu es mon entraîneur expert en course à pied et cyclisme. 
Analyse cette séance en détail à partir des données résumées et des métriques fines issues du stream :

--- DONNÉES GÉNÉRALES ---
- Type : {act.get('type')}
- Distance : {dist_km:.2f} km
- Durée : {duration_min} min
- Charge (TSS) : {act.get('icu_training_load')}
- FC moyenne : {act.get('average_heartrate')} bpm
- Puissance moyenne : {act.get('average_watts')} W
- Description : {act.get('description', 'Aucune')}

--- MÉTRIQUES DÉTAILLÉES (STREAMS SECONDE PAR SECONDE) ---
{streams_summary if streams_summary else "Aucun stream disponible."}

Fais un bilan structuré :
1. Analyse de la gestion de l'effort et de la stabilité cardiaque/puissance.
2. Impact de la séance sur la fatigue métabolique.
3. Recommandations pour la suite de l'entraînement.
"""
            custom_prompt = st.text_area("✍️ Consigne / Question pour le Coach :", value=default_prompt, height=280)
            
            if st.button("🚀 Lancer l'analyse IA", type="primary"):
                with st.spinner("Analyse par Gemini en cours..."):
                    try:
                        res = client.models.generate_content(model=MODEL_NAME, contents=custom_prompt)
                        st.markdown(res.text)
                    except Exception as e:
                        st.error(f"Erreur Gemini : {e}")

# --- MODE 2 : UNE SEMAINE COMPLÈTE ---
elif mode == "Une semaine complète":
    st.subheader("📆 Bilan d'une semaine d'entraînement")
    
    col1, col2 = st.columns(2)
    with col1:
        start_date = st.date_input("Début de semaine (Lundi)", datetime.now() - timedelta(days=datetime.now().weekday()))
    with col2:
        end_date = start_date + timedelta(days=6)
        st.write(f"**Fin de semaine :** {end_date.strftime('%Y-%m-%d')}")
        
    activities = get_activities(start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d"))
    
    if activities:
        st.success(f"{len(activities)} activité(s) trouvée(s) pour cette semaine.")
        
        summary = ""
        total_dist = 0
        total_tss = 0
        for a in activities:
            d = a.get('distance', 0) / 1000
            total_dist += d
            total_tss += a.get('icu_training_load', 0) or 0
            summary += f"- {a.get('start_date_local')[:10]} | {a.get('name')} ({a.get('type')}) : {d:.1f} km, TSS: {a.get('icu_training_load')}, FC moy: {a.get('average_heartrate')} bpm\n"
        
        default_prompt = f"""Tu es mon entraîneur expert en endurance. 
Voici le bilan de ma semaine du {start_date.strftime('%d/%m')} au {end_date.strftime('%d/%m')} :
- Nombre de séances : {len(activities)}
- Volume total : {total_dist:.1f} km
- Charge totale (TSS) : {total_tss}

Détail des séances :
{summary}

Analyse ma semaine :
1. Évalue la répartition du volume et de l'intensité.
2. Identifie les points forts et les risques de surmenage.
3. Propose des recommandations claires pour la semaine suivante.
"""
        custom_prompt = st.text_area("✍️ Consigne / Question pour le Coach :", value=default_prompt, height=250)
        
        if st.button("🚀 Lancer l'analyse de la semaine", type="primary"):
            with st.spinner("Analyse par Gemini en cours..."):
                try:
                    res = client.models.generate_content(model=MODEL_NAME, contents=custom_prompt)
                    st.markdown(res.text)
                except Exception as e:
                    st.error(f"Erreur Gemini : {e}")

# --- MODE 3 : 30 DERNIERS JOURS ---
elif mode == "30 derniers jours":
    st.subheader("📈 Bilan du mois écoulé")
    
    oldest_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    activities = get_activities(oldest_date)
    
    if activities:
        summary = ""
        for a in activities[-15:]:
            d = a.get('distance', 0) / 1000
            summary += f"- {a.get('start_date_local')[:10]} | {a.get('name')} ({a.get('type')}) : {d:.1f} km, TSS: {a.get('icu_training_load')}\n"
            
        default_prompt = f"""Voici mes séances des 30 derniers jours (aperçu des 15 plus récentes) :
{summary}

Analyse la tendance globale de mon bloc d'entraînement :
1. Progression du volume et de la charge.
2. Risque de fatigue accumulée.
3. Conseil stratégique pour mon prochain cycle.
"""
        custom_prompt = st.text_area("✍️ Consigne / Question pour le Coach :", value=default_prompt, height=250)
        
        if st.button("🚀 Lancer l'analyse globale", type="primary"):
            with st.spinner("Analyse par Gemini en cours..."):
                try:
                    res = client.models.generate_content(model=MODEL_NAME, contents=custom_prompt)
                    st.markdown(res.text)
                except Exception as e:
                    st.error(f"Erreur Gemini : {e}")
