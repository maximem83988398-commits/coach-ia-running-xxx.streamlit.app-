if module == "Dernière séance":
    st.subheader("📊 Analyse de la dernière activité")
    
    if st.button("Charger et analyser la séance", type="primary"):
        with st.spinner("Récupération depuis Intervals.icu..."):
            url = f"https://intervals.icu/api/v1/athlete/{ATHLETE_ID}/activities?limit=1"
            # Authentification HTTP Basic : l'utilisateur DOIT être la chaîne "API_KEY"
            response = requests.get(url, auth=('API_KEY', INTERVALS_API_KEY))
            
            if response.status_code == 200 and response.json():
                act = response.json()[0]
                
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
                    res = client.models.generate_content(
                        model="gemini-2.5-flash",
                        contents=prompt
                    )
                    st.markdown(res.text)
            else:
                # Affichage détaillé de l'erreur
                st.error(f"Erreur {response.status_code} : {response.text}")
