# utils.py (Version Finale sans affichage Debug ni Conditions)
import streamlit as st
import pandas as pd
import uuid
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime
import numpy as np
import zipfile
from io import BytesIO
import io
import urllib.parse
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.table import WD_ALIGN_VERTICAL

# --- CONSTANTES ---
PROJECT_RENAME_MAP = {
    'Intitulé': 'Intitulé',
    'Fournisseur Bornes AC [Bornes]': 'Fournisseur Bornes AC',
    'Fournisseur Bornes DC [Bornes]': 'Fournisseur Bornes DC',
    'L [Plan de Déploiement]': 'PDC Lent',
    'R [Plan de Déploiement]': 'PDC Rapide',
    'UR [Plan de Déploiement]': 'PDC Ultra-rapide',
    'Pré L [Plan de Déploiement]': 'PDC L pré-équipés',
    'Pré R [Plan de Déploiement]': 'PDC R pré-équipés',
    'Pré UR [Plan de Déploiement]': 'PDC UR pré-équipés',
}

DISPLAY_GROUPS = [
    ['Intitulé', 'Fournisseur Bornes AC [Bornes]', 'Fournisseur Bornes DC [Bornes]'],
    ['L [Plan de Déploiement]', 'R [Plan de Déploiement]', 'UR [Plan de Déploiement]'],
    ['Pré L [Plan de Déploiement]', 'Pré R [Plan de Déploiement]', 'Pré UR [Plan de Déploiement]'],
]

SECTION_PHOTO_RULES = {
    "Bornes DC": ['R [Plan de Déploiement]', 'UR [Plan de Déploiement]'],
    "Bornes AC": ['L [Plan de Déploiement]'],
}

COMMENT_ID = 100
COMMENT_QUESTION = "Veuillez préciser pourquoi le nombre de photo partagé ne correspond pas au minimum attendu"

# --- INITIALISATION FIREBASE ---
def initialize_firebase():
    if not firebase_admin._apps:
        try:
            cred_dict = {
                "type": st.secrets["firebase_type"],
                "project_id": st.secrets["firebase_project_id"],
                "private_key_id": st.secrets["firebase_private_key_id"],
                "private_key": st.secrets["firebase_private_key"].replace('\\n', '\n'),
                "client_email": st.secrets["firebase_client_email"],
                "client_id": st.secrets["firebase_client_id"],
                "auth_uri": st.secrets["firebase_auth_uri"],
                "token_uri": st.secrets["firebase_token_uri"],
                "auth_provider_x509_cert_url": st.secrets["firebase_auth_provider_x509_cert_url"],
                "client_x509_cert_url": st.secrets["firebase_client_x509_cert_url"],
                "universe_domain": st.secrets["firebase_universe_domain"],
            }
            project_id = cred_dict["project_id"]
            cred = credentials.Certificate(cred_dict)
            firebase_admin.initialize_app(cred, {'projectId': project_id})
        except Exception as e:
            st.error(f"Erreur de connexion Firebase : {e}")
            st.stop() 
    return firestore.client()

db = initialize_firebase()

# --- CHARGEMENT DONNÉES ---
@st.cache_data(ttl=3600)
def load_form_structure_from_firestore():
    try:
        docs = db.collection('formsquestions').order_by('id').get()
        data = [doc.to_dict() for doc in docs]
        if not data: return None
        df = pd.DataFrame(data)
        df.columns = df.columns.str.strip()
        
        rename_map = {'Conditon value': 'Condition value', 'condition value': 'Condition value', 'Condition Value': 'Condition value', 'Condition': 'Condition value', 'Conditon on': 'Condition on', 'condition on': 'Condition on'}
        actual_rename = {k: v for k, v in rename_map.items() if k in df.columns}
        df = df.rename(columns=actual_rename)
        
        expected_cols = ['options', 'Description', 'Condition value', 'Condition on', 'section', 'id', 'question', 'type', 'obligatoire']
        for col in expected_cols:
            if col not in df.columns: df[col] = np.nan 
        
        df['options'] = df['options'].fillna('')
        df['Description'] = df['Description'].fillna('')
        df['Condition value'] = df['Condition value'].fillna('')
        df['Condition on'] = pd.to_numeric(df['Condition on'], errors='coerce').fillna(0).astype(int)
        
        for col in df.select_dtypes(include=['object']).columns:
            df[col] = df[col].astype(str).str.strip()
        return df
    except Exception as e:
        st.error(f"Erreur lors du chargement de la structure du formulaire: {e}")
        return None

@st.cache_data(ttl=3600)
def load_site_data_from_firestore():
    try:
        docs = db.collection('Sites').get()
        data = [doc.to_dict() for doc in docs]
        if not data: return None
        df_site = pd.DataFrame(data)
        df_site.columns = df_site.columns.str.strip()
        return df_site
    except Exception as e:
        st.error(f"Erreur lors du chargement des données des sites: {e}")
        return None

# --- LOGIQUE MÉTIER ---

def get_expected_photo_count(section_name, project_data):
    if section_name.strip() not in SECTION_PHOTO_RULES:
        return None, None 

    columns = SECTION_PHOTO_RULES[section_name.strip()]
    total_expected = 0
    details = []

    for col in columns:
        val = project_data.get(col, 0)
        try:
            if pd.isna(val) or val == "":
                num = 0
            else:
                num = int(float(str(val).replace(',', '.'))) 
        except Exception:
            num = 0
        total_expected += num
        short_name = PROJECT_RENAME_MAP.get(col, col) 
        details.append(f"{num} {short_name}")

    detail_str = " + ".join(details)
    return total_expected, detail_str

def evaluate_single_condition(condition_str, all_answers):
    if "=" not in condition_str:
        return True
    try:
        target_id_str, expected_value_raw = condition_str.split('=', 1)
        target_id = int(target_id_str.strip())
        expected_value = expected_value_raw.strip().strip('"').strip("'")
        user_answer = all_answers.get(target_id)
        if user_answer is not None:
            return str(user_answer).strip().lower() == str(expected_value).strip().lower()
        else:
            return False
    except Exception:
        return True

def check_condition(row, current_answers, collected_data):
    try:
        if int(row.get('Condition on', 0)) != 1: return True
    except (ValueError, TypeError): return True

    all_past_answers = {}
    for phase_data in collected_data: 
        all_past_answers.update(phase_data['answers'])
    combined_answers = {**all_past_answers, **current_answers}
    
    condition_raw = str(row.get('Condition value', '')).strip().strip('"').strip("'")
    if not condition_raw: return True

    or_blocks = condition_raw.split(' OU ')
    for block in or_blocks:
        and_conditions = block.split(' ET ')
        block_is_valid = True
        for atom in and_conditions:
            if not evaluate_single_condition(atom, combined_answers):
                block_is_valid = False
                break
        if block_is_valid:
            return True
    return False

def validate_section(df_questions, section_name, answers, collected_data, project_data):
    missing = []
    section_rows = df_questions[df_questions['section'] == section_name]
    comment_val = answers.get(COMMENT_ID)
    has_justification = comment_val is not None and str(comment_val).strip() != ""
    
    expected_total_base, detail_str = get_expected_photo_count(section_name.strip(), project_data)
    expected_total = expected_total_base
    
    photo_question_count = sum(
        1 for _, row in section_rows.iterrows()
        if str(row.get('type', '')).strip().lower() == 'photo' and check_condition(row, answers, collected_data)
    )
    
    if expected_total is not None and expected_total > 0:
        expected_total = expected_total_base * photo_question_count
        detail_str = f"{detail_str} | Questions photo visibles: {photo_question_count} -> Total ajusté: {expected_total}"

    current_photo_count = 0
    photo_questions_found = False
    
    for _, row in section_rows.iterrows():
        q_type = str(row['type']).strip().lower()
        if q_type == 'photo' and check_condition(row, answers, collected_data):
            photo_questions_found = True
            q_id = int(row['id'])
            val = answers.get(q_id)
            if isinstance(val, list):
                current_photo_count += len(val)

    for _, row in section_rows.iterrows():
        q_id = int(row['id'])
        if q_id == COMMENT_ID: continue
        if not check_condition(row, answers, collected_data): continue
        is_mandatory = str(row['obligatoire']).strip().lower() == 'oui'
        q_type = str(row['type']).strip().lower()
        val = answers.get(q_id)
        if is_mandatory:
            if q_type == 'photo':
                if not isinstance(val, list) or len(val) == 0:
                    missing.append(f"Question {q_id} : {row['question']} (Au moins une photo est requise)")
            else:
                if isinstance(val, list):
                    if not val: missing.append(f"Question {q_id} : {row['question']} (fichier(s) manquant(s))")
                elif val is None or val == "" or (isinstance(val, (int, float)) and val == 0):
                    missing.append(f"Question {q_id} : {row['question']}")

    is_photo_count_incorrect = False
    if expected_total is not None and expected_total > 0:
        if photo_questions_found and current_photo_count != expected_total:
            is_photo_count_incorrect = True
            error_message = (
                f"⚠️ **Écart de Photos pour '{str(section_name)}'**.\n"
                f"Attendu : **{str(expected_total)}** (calculé : {str(detail_str)}).\n"
                f"Reçu : **{str(current_photo_count)}**.\n"
            )
            if not has_justification:
                missing.append(
                    f"**Commentaire (ID {COMMENT_ID}) :** {COMMENT_QUESTION} "
                    f"(requis en raison de l'écart de photo). \n\n {error_message}"
                )

    if not is_photo_count_incorrect and COMMENT_ID in answers:
        del answers[COMMENT_ID]

    return len(missing) == 0, missing

# --- SAUVEGARDE ET EXPORTS ---
def save_form_data(collected_data, project_data, submission_id, start_time):
    try:
        cleaned_data = []
        for phase in collected_data:
            clean_phase = {"phase_name": phase["phase_name"], "answers": {}}
            for k, v in phase["answers"].items():
                if isinstance(v, list) and v and hasattr(v[0], 'read'): 
                    file_names = ", ".join([f.name for f in v])
                    clean_phase["answers"][str(k)] = f"Fichiers: {file_names}"
                elif hasattr(v, 'read'): 
                     clean_phase["answers"][str(k)] = f"Fichier: {v.name}"
                else:
                    clean_phase["answers"][str(k)] = v
            cleaned_data.append(clean_phase)
        
        final_document = {
            "project_intitule": project_data.get('Intitulé', 'N/A'),
            "project_details": project_data,
            "submission_id": submission_id,
            "start_date": start_time,
            "submission_date": datetime.now(),
            "status": "Completed",
            "collected_phases": cleaned_data
        }
        doc_id_base = str(project_data.get('Intitulé', 'form')).replace(" ", "_").replace("/", "_")[:20]
        doc_id = f"{doc_id_base}_{datetime.now().strftime('%Y%m%d_%H%M')}_{submission_id[:6]}"
        db.collection('FormAnswers').document(doc_id).set(final_document)
        return True, doc_id 
    except Exception as e:
        return False, str(e)

def create_csv_export(collected_data, df_struct, project_name, submission_id, start_time):
    """Génère un export CSV des réponses."""
    data_for_df = []
    for phase in collected_data:
        for q_id, answer in phase['answers'].items():
            if not hasattr(answer, 'read'): # Exclure les fichiers binaires (photos)
                data_for_df.append({
                    'Projet': project_name,
                    'Phase': phase['phase_name'],
                    'Question_ID': q_id,
                    'Réponse': answer
                })
    return pd.DataFrame(data_for_df).to_csv(index=False).encode('utf-8')

def create_zip_export(collected_data):
    """Regroupe toutes les photos dans un fichier ZIP."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zip_file:
        for phase in collected_data:
            for q_id, file in phase['answers'].items():
                if hasattr(file, 'getvalue'):
                    zip_file.writestr(f"{phase['phase_name']}_{q_id}.jpg", file.getvalue())
    return buf

# --- LA FONCTION MODIFIÉE ---
def create_word_report(collected_data, df_struct, project_data, form_start_time):
    """
    Génère le rapport Word. 
    Prend désormais 4 arguments pour inclure la date de début.
    """
    doc = Document()
    
    # Titre du rapport
    doc.add_heading(f"Rapport d'Audit - {project_data.get('Intitulé', 'Projet')}", 0)
    
    # Section Informations Générales
    doc.add_heading("Informations Générales", level=1)
    if form_start_time:
        date_str = form_start_time.strftime("%d/%m/%Y à %H:%M")
        doc.add_paragraph(f"Date de l'audit : {date_str}")
    
    doc.add_paragraph(f"Ville : {project_data.get('Ville', 'N/A')}")
    
    # Détails des réponses par phase
    for entry in collected_data:
        doc.add_heading(f"Phase : {entry['phase_name']}", level=2)
        table = doc.add_table(rows=1, cols=2)
        table.style = 'Table Grid'
        hdr_cells = table.rows[0].cells
        hdr_cells[0].text = 'Question'
        hdr_cells[1].text = 'Réponse'
        
        for q_id, answer in entry['answers'].items():
            row_cells = table.add_row().cells
            # On cherche le texte de la question dans le DataFrame de structure
            q_text = df_struct[df_struct['id'].astype(str) == str(q_id)]['question'].values
            row_cells[0].text = str(q_text[0]) if len(q_text) > 0 else f"ID: {q_id}"
            
            if hasattr(answer, 'read'):
                row_cells[1].text = "[Image jointe dans le ZIP]"
            else:
                row_cells[1].text = str(answer)

    buffer = BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer

# --- COMPOSANT UI (Rendu de la question) ---
def render_question(row, answers, phase_name, key_suffix, loop_index, project_data):
    """
    Rendu d'une question sans affichage des conditions ni debug.
    """
    q_id = int(row.get('id', 0))
    is_dynamic_comment = (q_id == COMMENT_ID)
    
    if is_dynamic_comment:
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
    
    # Label HTML simplifié (sans condition_display)
    label_html = (
        f"<strong>{q_id}. {q_text}</strong>" 
        + (' <span class="mandatory">*</span>' if q_mandatory else "")
    )
    
    widget_key = f"q_{q_id}_{phase_name}_{key_suffix}_{loop_index}"
    current_val = answers.get(q_id)
    val = current_val

    st.markdown(f'<div class="question-card"><div>{label_html}</div>', unsafe_allow_html=True)
    if q_desc: st.markdown(f'<div class="description">⚠️ {q_desc}</div>', unsafe_allow_html=True)
    
    # Éléments de formulaire
    if q_type == 'text':
        default_val = current_val if current_val else ""
        if is_dynamic_comment:
             val = st.text_area("Justification", value=default_val, key=widget_key, label_visibility="collapsed")
        else:
             val = st.text_input("Réponse", value=default_val, key=widget_key, label_visibility="collapsed")

    elif q_type == 'select':
        clean_opts = [opt.strip() for opt in q_options]
        if "" not in clean_opts: clean_opts.insert(0, "")
        idx = clean_opts.index(current_val) if current_val in clean_opts else 0
        val = st.selectbox("Sélection", clean_opts, index=idx, key=widget_key, label_visibility="collapsed")
    
    elif q_type == 'number':
        try:
            default_val = int(float(current_val)) if current_val is not None and str(current_val).replace('.', '', 1).isdigit() else 0
        except:
            default_val = 0
        val = st.number_input("Nombre", value=default_val, step=1, format="%d", key=widget_key, label_visibility="collapsed")
    
    elif q_type == 'photo':
        expected, details = get_expected_photo_count(phase_name.strip(), project_data)
        if expected is not None and expected > 0:
            st.info(f"📸 **Photos attendues : {expected}** ({details})")
            st.divider()
        
        file_uploader_default = current_val if isinstance(current_val, list) else []
        val = st.file_uploader("Images", type=['png', 'jpg', 'jpeg'], accept_multiple_files=True, key=widget_key, label_visibility="collapsed")
        
        if val:
            st.success(f"Photos chargées : {len(val)}")
        elif file_uploader_default and isinstance(file_uploader_default, list):
            val = file_uploader_default
            st.info(f"Photos conservées : {len(val)}")
        
    st.markdown('</div>', unsafe_allow_html=True)
    
    # Mise à jour des réponses
    if val is not None and (not is_dynamic_comment or str(val).strip() != ""): 
        answers[q_id] = int(val) if q_type == 'number' else val 
    elif current_val is not None and not is_dynamic_comment: 
        answers[q_id] = current_val 
    elif is_dynamic_comment and (val is None or str(val).strip() == ""):
        if q_id in answers: del answers[q_id]
