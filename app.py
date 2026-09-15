import streamlit as st
import requests
from google import genai
from datetime import datetime, timedelta

# 1. Configuration de la page Streamlit
st.set_page_config(
    page_title="Coach IA - Running & Vélo",
    page_icon="🏃‍♂️",
    layout="centered"
)

st.title("🏃‍♂️ Mon Assistant Entraînement")

# 2. Récupération sécurisée des secrets
try:
    INTERVALS_API_KEY = st.secrets["INTERVALS_API_KEY"]
    ATHLETE_ID = st.secrets["ATHLETE_ID"]
    GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
except Exception:
    st.error("Les clés d'API ne sont pas configurées correctement dans les Secrets de Streamlit.")
    st.stop()

# 3. Initialisation du client Gemini
client = genai.Client(api_key=GEMINI_API_KEY)

# Modèle mis à jour selon les recommandations Google
MODEL_NAME = "gemini-3.6-flash"

# Date limite pour les requêtes (30 jours en arrière)
oldest_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

# 4. Menu de navigation
module = st.radio(
    "Que souhaites-tu analyser ?",
    ["Dernière séance", "Bilan des 5 dernières séances"],
    horizontal=True
)

st.divider()

# MODULE 1 : DERNIÈRE SÉANCE
if module == "Dernière séance":
    st.subheader("📊 Analyse de la dernière activité")
    
    if st.button("Charger et analyser la séance", type="primary"):
        with st.spinner("Récupération depuis Intervals.icu..."):
            url = f"https://intervals.icu/api/v1/athlete/{ATHLETE_ID}/activities?oldest={oldest_date}"
            response = requests.get(url, auth=('API_KEY', INTERVALS_API_KEY))
            
            if response.status_code == 200 and response.json():
                activities = response.json()
                act = activities[-1] if len(activities) > 0 else activities[0]
                
                dist_km = act.get('distance', 0) / 1000
                duration_min = act.get('moving_time', 0) // 60
                
                st.info(f"**{act.get('name')}** | {act.get('type')} - {dist_km:.2f} km en {duration_min} min")
                
                prompt = f"""
                Tu es un entraîneur expert en course à pied et cyclisme. 
                Analyse cette séance et donne un retour clair et motivant :
                - Type : {act.get('type')}
                - Distance : {dist_km:.2f} km
                - Durée : {duration_min} min
                - Charge (TSS / Load) : {act.get('icu_training_load')}
                - Fréquence cardiaque moyenne : {act.get('average_heartrate')} bpm
                - Puissance moyenne : {act.get('average_watts')} W
                - Notes / Sensations : {act.get('description', 'Aucune')}
                
                Donne un bilan concis en 3 points :
                1. Objectif physique atteint par la séance
                2. Impact sur la fatigue / charge
                3. Conseil de récupération ou d'ajustement pour la suite.
                """
                
                with st.spinner("Analyse par Gemini en cours..."):
                    try:
                        res = client.models.generate_content(
                            model=MODEL_NAME,
                            contents=prompt
                        )
                        st.markdown(res.text)
                    except Exception as e:
                        st.error(f"Erreur d'appel à Gemini : {e}")
            else:
                st.error(f"Erreur Intervals.icu {response.status_code} : {response.text}")

# MODULE 2 : BILAN DES 5 DERNIÈRES SÉANCES
elif module == "Bilan des 5 dernières séances":
    st.subheader("📈 Bilan du bloc d'entraînement récent")
    
    if st.button("Analyser le bloc de 5 séances", type="primary"):
        with st.spinner("Récupération des activités..."):
            url = f"https://intervals.icu/api/v1/athlete/{ATHLETE_ID}/activities?oldest={oldest_date}"
            response = requests.get(url, auth=('API_KEY', INTERVALS_API_KEY))
            
            if response.status_code == 200 and response.json():
                activities = response.json()[-5:]
                
                summary = ""
                for act in activities:
                    dist = act.get('distance', 0) / 1000
                    summary += f"- {act.get('start_date_local')[:10]} | {act.get('name')} ({act.get('type')}) : {dist:.1f} km, TSS: {act.get('icu_training_load')}, FC moy: {act.get('average_heartrate')} bpm\n"
                
                prompt = f"""
                Voici les 5 dernières activités enregistrées :
                {summary}
                
                Analyse la tendance récente de l'entraînement :
                1. Évalue la répartition de la charge (volume vs intensité).
                2. Détecte les risques potentiels de surmenage ou de sous-entraînement.
                3. Propose une recommandation pour les 3 à 4 prochains jours.
                """
                
                with st.spinner("Analyse globale par Gemini en cours..."):
                    try:
                        res = client.models.generate_content(
                            model=MODEL_NAME,
                            contents=prompt
                        )
                        st.markdown(res.text)
                    except Exception as e:
                        st.error(f"Erreur d'appel à Gemini : {e}")
            else:
                st.error(f"Erreur Intervals.icu {response.status_code} : {response.text}")
