import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import firestore, credentials
from datetime import datetime
from io import BytesIO
import zipfile
import base64
from docx import Document
from docx.shared import Inches, Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import RGBColor

# --- Constantes (À adapter si nécessaire) ---
# La section d'identification est censée être la première ligne du df_struct
COMMENT_ID = 99999 

# Mapping pour renommer les colonnes des données Projet dans l'affichage
PROJECT_RENAME_MAP = {
    'Localisation': 'Ville',
    'Date de mise en service': 'Date MS',
    'Nb PDL Standard': 'PDL Standard',
    'Puissance Standard (kW)': 'P. Std (kW)',
    'Nb PDL Pré-équipés': 'PDL Pré-équipés',
    'Puissance Pré-équipée (kW)': 'P. Pré-eq (kW)',
    'Type': 'Type de site'
}

# Groupes de champs du projet pour l'affichage dans l'expander
DISPLAY_GROUPS = [
    ['Localisation', 'Type', 'Date de mise en service'],
    ['Nb PDL Standard', 'Puissance Standard (kW)', 'Type PDL Standard'],
    ['Nb PDL Pré-équipés', 'Puissance Pré-équipée (kW)', 'Type PDL Pré-équipés']
]

# --- 1. INITIALISATION DE FIREBASE ---

def setup_firebase():
    """Initialise Firebase si ce n'est pas déjà fait."""
    if not firebase_admin._apps:
        try:
            # Récupération des secrets depuis Streamlit
            firebase_config = st.secrets["firebase"]
            cred_json = {
                "type": "service_account",
                "project_id": firebase_config["project_id"],
                "private_key_id": firebase_config["private_key_id"],
                "private_key": firebase_config["private_key"].replace('\\n', '\n'),
                "client_email": firebase_config["client_email"],
                "client_id": firebase_config["client_id"],
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                "client_x509_cert_url": firebase_config["client_x509_cert_url"]
            }
            
            cred = credentials.Certificate(cred_json)
            firebase_admin.initialize_app(cred)
            return firestore.client()
        except Exception as e:
            st.error(f"Erreur d'initialisation de Firebase : {e}")
            return None
    return firestore.client()

DB = setup_firebase()

# --- 2. FONCTIONS DE CHARGEMENT DE DONNÉES (mise en cache) ---

@st.cache_data(ttl=3600)
def load_form_structure_from_firestore():
    """Charge la structure du formulaire depuis Firestore."""
    if DB is None: return None
    try:
        docs = DB.collection('form_structure').stream()
        data = [doc.to_dict() for doc in docs]
        if not data:
            st.warning("Collection 'form_structure' vide.")
            return pd.DataFrame()
            
        df = pd.DataFrame(data)
        # Assurer que les colonnes clés existent pour éviter des erreurs
        required_cols = ['id', 'question', 'type', 'section', 'mandatory', 'condition']
        for col in required_cols:
            if col not in df.columns:
                df[col] = ''
        
        # S'assurer que 'id' est un entier pour le matching
        df['id'] = pd.to_numeric(df['id'], errors='coerce').fillna(0).astype(int)
        
        # Trier par ID pour s'assurer de l'ordre d'affichage
        df = df.sort_values(by='id').reset_index(drop=True)
        return df
    except Exception as e:
        st.error(f"Erreur lors du chargement de la structure : {e}")
        return None

@st.cache_data(ttl=3600)
def load_site_data_from_firestore():
    """Charge les données des sites depuis Firestore."""
    if DB is None: return None
    try:
        docs = DB.collection('sites').stream()
        data = [doc.to_dict() for doc in docs]
        df = pd.DataFrame(data)
        if 'Intitulé' not in df.columns:
            st.warning("Colonne 'Intitulé' manquante dans les données Sites.")
        return df
    except Exception as e:
        st.error(f"Erreur lors du chargement des données des sites : {e}")
        return None

# --- 3. LOGIQUE DE CONDITION (Le cœur de la correction) ---

def _evaluate_simple_term(term_string, combined_answers, project_data):
    """
    Évalue une sous-condition simple (ex: "10 = Oui", "Site = Mairie")
    et retourne True ou False.
    """
    term = term_string.strip()
    
    # 1. Déterminer l'opérateur de comparaison
    op_raw = None
    op_python = None
    
    if ' <> ' in term:
        op_raw = ' <> '
        op_python = ' != '
    elif ' = ' in term:
        op_raw = ' = '
        op_python = ' == '
    else:
        # st.warning(f"Condition mal formatée : '{term_string}'")
        return False
        
    try:
        # Séparer la clé et la valeur attendue
        parts = term.split(op_raw.strip(), 1)
        if len(parts) != 2: return False # Robuste
        
        key_raw = parts[0].strip()
        expected_value = parts[1].strip().strip('"').strip("'")
        
        # 2. Récupérer la réponse réelle
        user_answer = None
        
        if key_raw.isdigit():
            # C'est un ID de question (vient de combined_answers)
            q_num = int(key_raw)
            user_answer = combined_answers.get(q_num)
        else:
            # C'est une clé de Projet (vient de project_data)
            user_answer = project_data.get(key_raw)
            
        # Si la clé n'est pas trouvée ou n'a pas été répondue, la condition est Fausse
        if user_answer is None:
            return False

        # 3. Comparaison
        actual_answer_str = str(user_answer).strip().lower()
        expected_value_lower = expected_value.lower()
        
        if op_python == ' == ':
            return actual_answer_str == expected_value_lower
        elif op_python == ' != ':
            return actual_answer_str != expected_value_lower
        
        return False

    except Exception as e:
        # st.error(f"Erreur critique lors de l'évaluation du terme '{term_string}' : {e}")
        return False


def check_condition(row, current_phase_answers, collected_data):
    """
    Vérifie si la condition d'une question est remplie.
    Supporte les conditions complexes (ET/OU) et les comparaisons (= / <>).
    """
    condition_str = row.get('condition', '').strip()
    
    # Pas de condition, la question est toujours visible
    if not condition_str:
        return True

    # Fusionner les réponses actuelles et l'historique
    combined_answers = current_phase_answers.copy()
    for entry in collected_data:
        combined_answers.update(entry['answers'])
        
    # Le cas 'Identification' est toujours la première entrée (si complétée)
    project_data = st.session_state.get('project_data', {})

    # Remplacement des opérateurs logiques pour le split
    temp_condition = condition_str.upper().replace(' ET ', ' AND ').replace(' OU ', ' OR ')
    
    # Utiliser un séparateur unique pour ne pas confondre avec = ou <>
    # On isole les conditions simples et les opérateurs logiques
    temp_condition = temp_condition.replace(' AND ', '||AND||').replace(' OR ', '||OR||')
    
    parts = [p.strip() for p in temp_condition.split('||') if p.strip()]
    
    if not parts:
        return True
        
    # 5. Construction de l'expression booléenne finale
    final_expression_eval = ""
    
    for part in parts:
        part = part.strip()
        
        if part == 'AND':
            final_expression_eval += ' and '
        elif part == 'OR':
            final_expression_eval += ' or '
        elif part: 
            # Évaluation du terme simple (ex: "10 = Oui")
            term_result = _evaluate_simple_term(part, combined_answers, project_data)
            # Ajout du résultat booléen (True ou False) à l'expression à évaluer
            final_expression_eval += str(term_result)

    # 6. Évaluation finale
    try:
        return eval(final_expression_eval)
    except Exception as e:
        # st.error(f"Erreur d'évaluation finale de la condition '{condition_str}': {e}")
        return False

# --- 4. FONCTION DE RENDU DE QUESTION ---

def render_question(row, answers_dict, phase_name, iteration_id, index, project_data=None):
    """Rend un widget Streamlit basé sur le type de question."""
    q_id = int(row.get('id', 0))
    q_text = row.get('question', 'QUESTION SANS TEXTE').strip()
    q_type = str(row.get('type', 'text')).strip().lower()
    mandatory = str(row.get('mandatory', 'NON')).strip().upper() == 'OUI'
    options = str(row.get('options', '')).strip().split(';')
    
    # Clé unique pour Streamlit : évite les conflits entre phases et itérations
    key = f"{phase_name}_{q_id}_{iteration_id}_{index}"
    
    # Texte du label
    label_text = f"{q_text} ({q_id})"
    if mandatory and q_id != COMMENT_ID:
        label_text += '<span class="mandatory">*</span>'

    # Gestion de la description du projet pour l'étape Identification
    if q_id == 1 and phase_name == st.session_state['df_struct']['section'].iloc[0]:
        q_text = f"Projet : **{project_data.get('Intitulé', 'N/A')}** - {q_text}"
        label_text = f"{q_text} ({q_id})"
    
    if q_id == COMMENT_ID:
        q_text = "Justification (Obligatoire si photos manquantes)"
        label_text = f"{q_text} (ID {COMMENT_ID})"
        # Le champ commentaire est toujours multi-lignes et non obligatoire par défaut
        q_type = 'textarea'
        
    with st.container():
        st.markdown(f'<div class="question-card">', unsafe_allow_html=True)
        
        # Le conteneur du label
        st.markdown(f'<div class="description">{label_text}</div>', unsafe_allow_html=True)
        
        # Si la question existe déjà dans l'état de session, on pré-remplit
        default_value = answers_dict.get(q_id, '')

        # Rendu du widget
        if q_type == 'select' and options:
            options_list = [''] + [opt.strip() for opt in options]
            selection = st.selectbox(
                label="", 
                options=options_list, 
                key=key, 
                index=options_list.index(default_value) if default_value in options_list else 0
            )
            answers_dict[q_id] = selection

        elif q_type == 'radio' and options:
            options_list = [opt.strip() for opt in options]
            # Utilisation de la valeur par défaut ou None si non défini
            initial_index = options_list.index(default_value) if default_value in options_list else -1
            selection = st.radio(
                label="", 
                options=options_list, 
                key=key, 
                index=initial_index,
                horizontal=True
            )
            answers_dict[q_id] = selection

        elif q_type == 'number':
            try:
                # Si la valeur par défaut est une chaîne, on essaie de la convertir en float
                default_val_num = float(default_value) if default_value else None
            except ValueError:
                default_val_num = None
                
            number_input = st.number_input(
                label="", 
                value=default_val_num, 
                key=key,
                step=1 if default_val_num is None or default_val_num == int(default_val_num) else 0.1
            )
            # Sauvegarder la valeur comme chaîne ou None
            answers_dict[q_id] = str(number_input) if number_input is not None else None

        elif q_type == 'photo':
            # Widget de téléchargement de fichier
            uploaded_file = st.file_uploader(
                label="Prendre une photo ou télécharger un fichier image", 
                type=['png', 'jpg', 'jpeg'], 
                key=key
            )
            
            if uploaded_file:
                # Stocker l'image encodée en base64 dans les réponses
                answers_dict[q_id] = {
                    "filename": uploaded_file.name,
                    "b64_data": base64.b64encode(uploaded_file.getvalue()).decode('utf-8')
                }
            elif q_id in answers_dict and answers_dict[q_id]:
                 # Si une photo était déjà là, la garder si l'utilisateur ne la change pas
                 st.caption(f"Fichier déjà enregistré : **{answers_dict[q_id].get('filename', 'Inconnu')}**")
            else:
                 answers_dict[q_id] = None # Aucune photo

        elif q_type == 'date':
            default_date = None
            try:
                if default_value:
                    default_date = datetime.strptime(str(default_value), '%Y-%m-%d').date()
            except:
                pass # Laisser la date par défaut à None si le format est mauvais

            date_input = st.date_input(
                label="",
                value=default_date,
                key=key
            )
            answers_dict[q_id] = str(date_input) if date_input else None
            
        elif q_type == 'textarea':
            text_input = st.text_area(
                label="",
                value=str(default_value) if default_value else "",
                key=key
            )
            answers_dict[q_id] = text_input

        elif q_type == 'text' or q_id == COMMENT_ID:
            text_input = st.text_input(
                label="",
                value=str(default_value) if default_value else "",
                key=key
            )
            answers_dict[q_id] = text_input
            
        st.markdown('</div>', unsafe_allow_html=True)


# --- 5. FONCTION DE VALIDATION ---

def validate_section(df_struct, section_name, answers, collected_data, project_data):
    """Valide les champs obligatoires de la section et la justification de l'écart."""
    section_rows = df_struct[df_struct['section'] == section_name]
    missing = []
    
    # Fusionner les réponses (pour check_condition)
    combined_answers = {}
    for entry in collected_data:
        combined_answers.update(entry['answers'])
    combined_answers.update(answers)

    # 1. Vérification des champs obligatoires et visibles
    is_photo_count_incorrect = False
    photo_count_ok = 0
    
    for _, row in section_rows.iterrows():
        q_id = int(row.get('id', 0))
        q_text = row.get('question', 'Question sans texte')
        q_type = str(row.get('type', 'text')).strip().lower()
        mandatory = str(row.get('mandatory', 'NON')).strip().upper() == 'OUI'

        # Le commentaire (ID 99999) n'est jamais obligatoire dans la structure de base
        if q_id == COMMENT_ID:
            continue
            
        # Vérifie si la question doit être visible selon les conditions
        if check_condition(row, answers, collected_data):
            answer = answers.get(q_id)
            
            # Gestion des champs obligatoires (hors photos)
            if mandatory and (answer is None or str(answer).strip() == ''):
                missing.append(f"Le champ obligatoire '{q_text}' (ID {q_id}) est manquant.")
                
            # Gestion spéciale pour les photos obligatoires
            if q_type == 'photo' and mandatory:
                if answer and isinstance(answer, dict) and answer.get('b64_data'):
                    photo_count_ok += 1
                else:
                    missing.append(f"La photo obligatoire '{q_text}' (ID {q_id}) est manquante.")
                    is_photo_count_incorrect = True
            
            # Gestion spéciale pour les photos NON obligatoires (doivent être justifiées si manquent)
            if q_type == 'photo' and not mandatory:
                if answer is None or not answer.get('b64_data'):
                    is_photo_count_incorrect = True
            
    # 2. Logique de Justification de l'Écart (ID 99999)
    if is_photo_count_incorrect:
        comment = answers.get(COMMENT_ID)
        # Si une photo obligatoire manque OU si une photo non obligatoire manque
        if comment is None or str(comment).strip() == '':
            missing.append(f"Le Commentaire (ID {COMMENT_ID}) est obligatoire pour justifier l'absence d'une photo (obligatoire ou non obligatoire).")
        
    # 3. Nettoyage et retour
    # Si toutes les photos ont été soumises ou si aucune photo n'est manquante, 
    # on retire le commentaire au cas où il ait été rempli par erreur (ou n'était pas nécessaire)
    if not is_photo_count_incorrect and COMMENT_ID in answers:
        del answers[COMMENT_ID]

    return len(missing) == 0, missing

# --- 6. FONCTION DE SAUVEGARDE FIREBASE ---

def save_form_data(collected_data, project_data, submission_id, form_start_time):
    """Sauvegarde les données finales dans la collection 'submissions'."""
    if DB is None: return False, "DB non initialisée."
    
    # 1. Préparation de la structure de la soumission
    submission_doc = {
        "submission_id": submission_id,
        "project_intitule": project_data.get('Intitulé', 'Projet Inconnu'),
        "project_details": project_data,
        "form_start_time": form_start_time.isoformat(),
        "form_end_time": datetime.now().isoformat(),
        "phases_data": []
    }
    
    # 2. Traitement des données collectées pour la sauvegarde (séparation des photos)
    for phase_entry in collected_data:
        phase_name = phase_entry['phase_name']
        answers = phase_entry['answers']
        
        phase_answers_clean = {}
        photos_to_save = {}
        
        for q_id, answer in answers.items():
            if isinstance(answer, dict) and 'b64_data' in answer:
                # C'est une photo. On stocke l'URL de l'image (pourrait être une URL de Firebase Storage si implémenté)
                # Pour l'instant, on stocke juste le nom du fichier dans la réponse principale et la b64 dans une sous-collection
                phase_answers_clean[str(q_id)] = f"[Photo: {answer['filename']}]"
                photos_to_save[str(q_id)] = answer
            else:
                phase_answers_clean[str(q_id)] = answer
                
        submission_doc["phases_data"].append({
            "phase_name": phase_name,
            "answers": phase_answers_clean,
            # Le stockage des photos dans la même doc Firestore est acceptable pour des petites images.
            # Pour des images volumineuses, il faudrait utiliser Firebase Storage.
            "photos": photos_to_save
        })
        
    # 3. Sauvegarde de la soumission principale
    try:
        doc_ref = DB.collection('submissions').document(submission_id)
        doc_ref.set(submission_doc)
        return True, submission_id
    except Exception as e:
        return False, str(e)


# --- 7. FONCTIONS D'EXPORT ---

def create_csv_export(collected_data, df_struct, project_name, submission_id, form_start_time):
    """Crée un buffer CSV avec toutes les réponses."""
    
    # 1. Préparation de toutes les colonnes
    column_mapping = {row['id']: row['question'] for _, row in df_struct.iterrows() if row.get('id')}
    all_q_ids = sorted(column_mapping.keys())
    
    # Colonnes de métadonnées
    meta_cols = ['submission_id', 'project_name', 'form_start_time', 'phase_name']
    header = meta_cols + [column_mapping.get(qid, f"Q_ID_{qid}") for qid in all_q_ids]
    
    # 2. Construction des lignes de données
    data_rows = []
    for phase_entry in collected_data:
        phase_name = phase_entry['phase_name']
        answers = phase_entry['answers']
        
        row_data = {
            'submission_id': submission_id,
            'project_name': project_name,
            'form_start_time': form_start_time.strftime('%Y-%m-%d %H:%M:%S'),
            'phase_name': phase_name
        }
        
        # Remplissage des réponses
        for qid in all_q_ids:
            answer = answers.get(qid)
            
            if isinstance(answer, dict) and 'b64_data' in answer:
                # Réponse photo (on met le nom du fichier)
                value = f"[Photo: {answer.get('filename', 'N/A')}]"
            elif answer is not None:
                value = str(answer)
            else:
                value = ''
            
            row_data[column_mapping.get(qid, f"Q_ID_{qid}")] = value
        
        data_rows.append(row_data)

    # 3. Création du DataFrame et du CSV
    df_export = pd.DataFrame(data_rows)
    df_export = df_export.reindex(columns=header) # Assure l'ordre des colonnes
    
    csv_buffer = BytesIO()
    # Utilisation de l'encodage 'utf-8-sig' pour un support optimal des accents
    df_export.to_csv(csv_buffer, index=False, encoding='utf-8-sig')
    csv_buffer.seek(0)
    return csv_buffer.getvalue()


def create_zip_export(collected_data):
    """Crée un buffer ZIP contenant toutes les images soumises."""
    zip_buffer = BytesIO()
    
    # Compteur pour les noms de fichiers en double
    filename_counter = {}
    
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        for phase_entry in collected_data:
            phase_name = phase_entry['phase_name']
            answers = phase_entry['answers']
            
            for q_id, answer in answers.items():
                if isinstance(answer, dict) and 'b64_data' in answer:
                    filename = answer.get('filename', f"photo_{q_id}.jpg")
                    b64_data = answer['b64_data']
                    
                    try:
                        image_data = base64.b64decode(b64_data)
                        
                        # Gestion des noms de fichiers en double
                        original_name, ext = filename.rsplit('.', 1) if '.' in filename else (filename, 'dat')
                        
                        if original_name not in filename_counter:
                            filename_counter[original_name] = 0
                            final_filename = filename
                        else:
                            filename_counter[original_name] += 1
                            final_filename = f"{original_name}_{filename_counter[original_name]}.{ext}"
                        
                        # Chemin d'accès dans le ZIP (Phase/Nom du fichier)
                        zip_path = f"{phase_name}/{final_filename}"
                        
                        # Écriture dans le ZIP
                        zf.writestr(zip_path, image_data)
                        
                    except Exception as e:
                        st.warning(f"Impossible de décoder/zipper la photo pour QID {q_id} : {e}")

    zip_buffer.seek(0)
    return zip_buffer


def create_word_report(collected_data, df_struct, project_data, form_start_time):
    """Crée un buffer DOCX pour le rapport final."""
    document = Document()
    
    # Styles de base
    style = document.styles['Normal']
    font = style.font
    font.name = 'Calibri'
    font.size = Pt(11)

    # --- EN-TÊTE ---
    document.add_heading(f"Rapport d'Audit - {project_data.get('Intitulé', 'Projet Inconnu')}", level=1)
    p = document.add_paragraph()
    p.add_run(f"Date de l'audit : {datetime.now().strftime('%d/%m/%Y à %H:%M')}\n").bold = True
    p.add_run(f"Début du formulaire : {form_start_time.strftime('%d/%m/%Y %H:%M')}")
    document.add_page_break()

    # --- DÉTAILS DU PROJET ---
    document.add_heading("1. Détails du Projet", level=2)
    
    for group in DISPLAY_GROUPS:
        table = document.add_table(rows=1, cols=3)
        table.style = 'Table Grid'
        
        # Entête de la table (simple pour les groupes)
        hdr_cells = table.rows[0].cells
        hdr_cells[0].text = 'Champ'
        hdr_cells[1].text = 'Valeur'
        hdr_cells[2].text = ''

        for field_key in group:
            renamed_key = PROJECT_RENAME_MAP.get(field_key, field_key)
            value = project_data.get(field_key, 'N/A')
            
            row_cells = table.add_row().cells
            row_cells[0].text = renamed_key
            row_cells[1].text = str(value)

    # --- RÉSULTATS DES PHASES ---
    document.add_page_break()
    document.add_heading("2. Résultats de l'Audit", level=2)
    
    # Mapping des ID aux questions
    question_map = {row['id']: row for _, row in df_struct.iterrows()}
    
    for phase_entry in collected_data:
        phase_name = phase_entry['phase_name']
        answers = phase_entry['answers']
        
        # Titre de la Phase
        document.add_heading(f"Phase : {phase_name}", level=3)
        
        for q_id, answer in answers.items():
            try:
                q_id_int = int(q_id)
            except ValueError:
                continue

            # Ne pas afficher les IDs non trouvés ou le COMMENT_ID dans le listing principal
            if q_id_int not in question_map or q_id_int == COMMENT_ID: continue
            
            q_row = question_map[q_id_int]
            q_text = q_row.get('question', f"Question ID {q_id_int}")
            q_type = str(q_row.get('type', 'text')).strip().lower()
            
            # Affichage de la question
            p_q = document.add_paragraph()
            p_q.add_run(f"Q{q_id_int}: {q_text}").bold = True

            if q_type == 'photo' and isinstance(answer, dict) and 'b64_data' in answer:
                # --- Affichage des Photos ---
                filename = answer.get('filename', 'Image')
                document.add_paragraph(f"Réponse : {filename}").italic = True
                
                try:
                    # Décodage et insertion de l'image
                    image_data = base64.b64decode(answer['b64_data'])
                    image_stream = BytesIO(image_data)
                    
                    # Le bloc d'image doit être centré
                    p_img = document.add_paragraph()
                    p_img.alignment = WD_ALIGN_PARAGRAPH.CENTER
                    
                    # On réduit la taille pour le rapport A4
                    run_img = p_img.add_run()
                    run_img.add_picture(image_stream, width=Inches(3.5)) 
                    
                except Exception as e:
                    document.add_paragraph(f"[Erreur d'affichage de l'image: {e}]")
                    
                # Vérifie si la justification est présente pour cette photo (si elle est manquante)
                comment_text = answers.get(COMMENT_ID)
                if comment_text and q_row.get('mandatory', 'NON').upper() == 'NON' and not answer.get('b64_data'):
                     p_com = document.add_paragraph()
                     p_com.add_run("Justification de l'absence: ").bold = True
                     p_com.add_run(str(comment_text)).italic = True

            elif answer is not None and str(answer).strip():
                # --- Affichage des autres réponses ---
                document.add_paragraph(f"Réponse : {str(answer)}")
                
        # Affichage du commentaire général (s'il existe et n'a pas été traité)
        comment_final = answers.get(COMMENT_ID)
        if comment_final and str(comment_final).strip():
            document.add_paragraph("---")
            p_com = document.add_paragraph()
            p_com.add_run("Commentaire / Justification générale de l'écart: ").bold = True
            p_com.add_run(str(comment_final))

        document.add_page_break()

    # Sauvegarde du document dans un buffer
    word_buffer = BytesIO()
    document.save(word_buffer)
    word_buffer.seek(0)
    return word_buffer
