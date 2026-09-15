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

# Fonction pour récupérer les activités sur une plage de dates
def get_activities(oldest_str, newest_str=None):
    url = f"https://intervals.icu/api/v1/athlete/{ATHLETE_ID}/activities?oldest={oldest_str}"
    if newest_str:
        url += f"&newest={newest_str}"
    res = requests.get(url, auth=('API_KEY', INTERVALS_API_KEY))
    if res.status_code == 200:
        return res.json()
    else:
        st.error(f"Erreur API Intervals.icu ({res.status_code}) : {res.text}")
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
    
    # Choix de la date
    selected_date = st.date_input("Date de la séance", datetime.now())
    date_str = selected_date.strftime("%Y-%m-%d")
    
    # Bouton pour charger les séances du jour
    activities = get_activities(date_str, date_str)
    
    if activities is not None:
        if len(activities) == 0:
            st.warning("Aucune activité enregistrée à cette date.")
        else:
            # S'il y a plusieurs activités le même jour (ex: Biquotidien run + vélo)
            act_options = {f"{a.get('name')} ({a.get('type')}) - {a.get('distance', 0)/1000:.1f} km": a for a in activities}
            chosen_label = st.selectbox("Sélectionne l'activité :", list(act_options.keys()))
            act = act_options[chosen_label]
            
            # Données clés
            dist_km = act.get('distance', 0) / 1000
            duration_min = act.get('moving_time', 0) // 60
            
            st.info(f"**{act.get('name')}** | {act.get('type')} | {dist_km:.2f} km en {duration_min} min | Charge: {act.get('icu_training_load', 'N/A')}")
            
            # Prompt personnalisable
            default_prompt = f"""Tu es mon entraîneur expert en course à pied et cyclisme. 
Analyse cette séance en détail :
- Type : {act.get('type')}
- Distance : {dist_km:.2f} km
- Durée : {duration_min} min
- Charge (TSS / Load) : {act.get('icu_training_load')}
- FC moyenne : {act.get('average_heartrate')} bpm
- Puissance moyenne : {act.get('average_watts')} W
- Remarques/Description : {act.get('description', 'Aucune')}

Fais un bilan clair :
1. Objectif physique et métabolique travaillé.
2. Impact sur ma fatigue/charge globale.
3. Conseils pour mes prochaines séances ou ma récupération.
"""
            custom_prompt = st.text_area("✍️ Consigne / Question pour le Coach :", value=default_prompt, height=250)
            
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
        for a in activities[-15:]: # Limite aux 15 plus récentes pour ne pas surcharger le prompt
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
