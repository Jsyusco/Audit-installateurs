# utils.py - Fonction render_question (complète)

# ... (Le reste du code de utils.py reste inchangé) ...

# --- COMPOSANT UI (rendu de la question) ---
def render_question(row, answers, phase_name, key_suffix, loop_index, project_data):
    """
    Rendu d'une question dans Streamlit. Modifie le dictionnaire 'answers' en place.
    """
    q_id = int(row.get('id', 0))
    is_dynamic_comment = q_id == COMMENT_ID
    
    if is_dynamic_comment:
        # ... (Logique commentaire inchangée) ...
        q_text = COMMENT_QUESTION
        q_type = 'text' 
        q_desc = "Ce champ est obligatoire si le nombre de photos n'est pas conforme."
        q_mandatory = True 
        q_options = []
    else:
        q_text = row['question']
        q_type = str(row['type']).strip().lower()
        q_desc = row['Description']
        q_mandatory = str(row['obligatoire']).lower() == 'oui'
        q_options = str(row['options']).split(',') if row['options'] else []
        
    q_text = str(q_text).strip()
    q_desc = str(q_desc).strip()
    label_html = f"<strong>{q_id}. {q_text}</strong>" + (' <span class="mandatory">*</span>' if q_mandatory else "")
    widget_key = f"q_{q_id}_{phase_name}_{key_suffix}_{loop_index}"
    current_val = answers.get(q_id)
    val = current_val

    st.markdown(f'<div class="question-card"><div>{label_html}</div>', unsafe_allow_html=True)
    if q_desc: st.markdown(f'<div class="description">⚠️ {q_desc}</div>', unsafe_allow_html=True)

    if q_type == 'text':
        default_val = current_val if current_val else ""
        if is_dynamic_comment:
             val = st.text_area("Justification de l'écart", value=default_val, key=widget_key, label_visibility="collapsed")
        else:
             val = st.text_input("Réponse", value=default_val, key=widget_key, label_visibility="collapsed")

    elif q_type == 'select':
        clean_opts = [opt.strip() for opt in q_options]
        if "" not in clean_opts: clean_opts.insert(0, "")
        idx = clean_opts.index(current_val) if current_val in clean_opts else 0
        val = st.selectbox("Sélection", clean_opts, index=idx, key=widget_key, label_visibility="collapsed")
    
    # --- LOGIQUE CLÉ POUR NUMBER (ENTIER vs DÉCIMAL) ---
    elif q_type == 'number':
        
        # 1. DÉFINITION DES IDs ENTIERS (À MODIFIER PAR VOS SOINS)
        # Vous devez lister ici TOUS les IDs des questions de type 'number' qui 
        # représentent un compte (nombre de bornes, nombre d'éléments, etc.)
        INTEGER_Q_IDS = [
            1, # ID d'exemple 
            5, # ID d'exemple
            # ... Insérez vos IDs d'entiers ici ...
        ]
        
        is_integer_count = q_id in INTEGER_Q_IDS
        
        # 2. Définition des paramètres
        if is_integer_count:
            # --- CAS ENTIER ---
            label = "Nombre (Entier)"
            try:
                # La conversion en int(float()) gère les cas où la valeur est stockée comme '5.0' ou '5'
                default_val = int(float(current_val)) if current_val is not None and str(current_val).replace('.', '', 1).isdigit() else 0
            except:
                default_val = 0
            step_val = 1
            format_val = "%d" # Force l'affichage en entier
            
        else: 
            # --- CAS DÉCIMAL (PAR DÉFAUT) ---
            label = "Nombre (Décimal possible)"
            try:
                default_val = float(current_val) if current_val is not None and str(current_val).replace('.', '', 1).isdigit() else 0.0
            except:
                default_val = 0.0
            step_val = 0.01 
            format_val = "%.2f" 
            
        val = st.number_input(
            label, 
            value=default_val, 
            step=step_val, 
            format=format_val, 
            key=widget_key, 
            label_visibility="collapsed"
        )
    # -----------------------------------------------
    
    elif q_type == 'photo':
        # ... (Logique photo inchangée) ...
        expected, details = get_expected_photo_count(phase_name.strip(), project_data)
        if expected is not None and expected > 0:
            st.info(f"📸 **Photos :** Il est attendu **{expected}** photos pour cette section (Base calculée : {details}).")
            st.divider()
        
        file_uploader_default = current_val if isinstance(current_val, list) else []

        val = st.file_uploader("Images", type=['png', 'jpg', 'jpeg'], accept_multiple_files=True, key=widget_key, label_visibility="collapsed")
        
        if val:
            file_names = ", ".join([f.name for f in val])
            st.success(f"Nombre d'images chargées : {len(val)} ({file_names})")
        elif file_uploader_default and isinstance(file_uploader_default, list):
            val = file_uploader_default
            names = ", ".join([getattr(f, 'name', 'Fichier') for f in val])
            st.info(f"Fichiers conservés : {len(val)} ({names})")
        
    st.markdown('</div>', unsafe_allow_html=True)
    
    # Mise à jour des réponses dans le dictionnaire 'answers'
    if val is not None and (not is_dynamic_comment or str(val).strip() != ""): 
        # Conversion du type stocké
        if q_type == 'number':
            # On utilise la même logique 'is_integer_count' que pour le widget
            if is_integer_count:
                 answers[q_id] = int(val)
            else:
                 answers[q_id] = float(val) 
        else:
            answers[q_id] = val 
    elif current_val is not None and not is_dynamic_comment: 
        answers[q_id] = current_val 
    elif is_dynamic_comment and (val is None or str(val).strip() == ""):
        if q_id in answers: del answers[q_id]
