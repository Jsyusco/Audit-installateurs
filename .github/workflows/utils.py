# utils.py (Version Finale sans affichage Debug ni Conditions)
import streamlit as st
import pandas as pd
import uuid
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime
import numpy as np
import zipfile
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
    rows = []
    start_time_str = start_time.strftime('%Y-%m-%d %H:%M:%S') if isinstance(start_time, datetime) else 'N/A'
    end_time_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    for item in collected_data:
        phase_name = item['phase_name']
        for q_id, val in item['answers'].items():
            if int(q_id) == COMMENT_ID:
                q_text = "Commentaire Écart Photo"
            else:
                q_row = df_struct[df_struct['id'] == int(q_id)]
                q_text = q_row.iloc[0]['question'] if not q_row.empty else f"Question ID {q_id}"
            
            if isinstance(val, list) and val and hasattr(val[0], 'name'):
                final_val = f"[Pièces jointes] {len(val)} fichiers"
            elif hasattr(val, 'name'):
                final_val = f"[Pièce jointe] {val.name}"
            else:
                final_val = str(val)
            
            rows.append({
                "ID Formulaire": submission_id, "Date Début": start_time_str, "Date Fin": end_time_str,
                "Projet": project_name, "Phase": phase_name, "ID": q_id, "Question": q_text, "Réponse": final_val
            })
    return pd.DataFrame(rows).to_csv(index=False, sep=';', encoding='utf-8-sig')

def create_zip_export(collected_data):
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        files_added = 0
        for phase in collected_data:
            phase_name_clean = str(phase['phase_name']).replace("/", "_").replace(" ", "_")
            for q_id, answer in phase['answers'].items():
                if isinstance(answer, list) and answer and hasattr(answer[0], 'read'):
                    for idx, file_obj in enumerate(answer):
                        try:
                            file_obj.seek(0)
                            file_content = file_obj.read()
                            if file_content:
                                original_name = file_obj.name.split('/')[-1].split('\\')[-1]
                                filename = f"{phase_name_clean}_Q{q_id}_{idx+1}_{original_name}"
                                zip_file.writestr(filename, file_content)
                                files_added += 1
                            file_obj.seek(0)
                        except: pass
        zip_file.writestr("info.txt", f"Export généré le {datetime.now()}\nFichiers : {files_added}")
    zip_buffer.seek(0)
    return zip_buffer

def define_custom_styles(doc):
    try: title_style = doc.styles.add_style('Report Title', WD_STYLE_TYPE.PARAGRAPH)
    except: title_style = doc.styles['Report Title']
    title_style.base_style = doc.styles['Heading 1']
    title_font = title_style.font
    title_font.name = 'Arial'
    title_font.size = Pt(20)
    title_font.bold = True
    title_font.color.rgb = RGBColor(0x01, 0x38, 0x2D)
    title_style.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER

    try: subtitle_style = doc.styles.add_style('Report Subtitle', WD_STYLE_TYPE.PARAGRAPH)
    except: subtitle_style = doc.styles['Report Subtitle']
    subtitle_font = subtitle_style.font
    subtitle_font.name = 'Arial'
    subtitle_font.size = Pt(14)
    subtitle_font.bold = True
    subtitle_font.color.rgb = RGBColor(0x00, 0x56, 0x47)

def create_word_report(collected_data, df_struct, project_data):
    """
    Crée un rapport Word robuste avec gestion sécurisée des images et tri des questions.
    """
    doc = Document()
    
    # --- STYLES ---
    style = doc.styles['Normal']
    font = style.font
    font.name = 'Calibri'
    font.size = Pt(11)
    
    # --- EN-TÊTE DU DOCUMENT ---
    header = doc.add_heading("Rapport d'Audit Chantier", 0)
    header.alignment = WD_ALIGN_PARAGRAPH.CENTER
    
    # --- TABLEAU D'INFORMATIONS PROJET ---
    doc.add_heading('Informations du Projet', level=1)
    
    # Création du tableau de synthèse
    table = doc.add_table(rows=1, cols=2)
    table.style = 'Table Grid'
    
    # Remplissage des infos générales
    hdr_cells = table.rows[0].cells
    hdr_cells[0].text = 'Intitulé du Projet'
    hdr_cells[1].text = str(project_data.get('Intitulé', 'N/A'))
    
    row = table.add_row().cells
    row[0].text = 'Date de début'
    start_time = st.session_state.get('form_start_time', datetime.now())
    row[1].text = start_time.strftime('%d/%m/%Y %H:%M') if isinstance(start_time, datetime) else str(start_time)

    row = table.add_row().cells
    row[0].text = 'Date de fin'
    row[1].text = datetime.now().strftime('%d/%m/%Y %H:%M')

    doc.add_paragraph() # Espace

    # --- DÉTAILS TECHNIQUES (Boucle sur les groupes configurés) ---
    doc.add_heading('Détails Techniques', level=2)
    for group in DISPLAY_GROUPS:
        p = doc.add_paragraph()
        for field_key in group:
            renamed_key = PROJECT_RENAME_MAP.get(field_key, field_key)
            value = project_data.get(field_key, 'N/A')
            # Si la valeur est vide ou NaN, on met un tiret
            if pd.isna(value) or value == "": 
                value = "-"
            
            runner = p.add_run(f'{renamed_key} : ')
            runner.bold = True
            p.add_run(f'{value}\n')
            
    doc.add_page_break()
    
    # --- BOUCLE SUR LES PHASES (SECTION) ---
    for phase_idx, phase in enumerate(collected_data):
        phase_name = phase['phase_name']
        
        # Titre de la phase
        doc.add_heading(f'Phase : {phase_name}', level=1)
        
        # On récupère les réponses et on les TRIE par ID (pour avoir Q1, Q2, Q3 dans l'ordre)
        # On convertit les clés en int pour le tri, sauf si c'est impossible
        sorted_answers = sorted(phase['answers'].items(), key=lambda x: int(x[0]) if str(x[0]).isdigit() else 9999)

        for q_id, answer in sorted_answers:
            q_id_int = int(q_id)
            
            # Récupération du libellé de la question
            if q_id_int == COMMENT_ID:
                q_text = "Commentaire sur l'écart photo"
            else:
                q_row = df_struct[df_struct['id'] == q_id_int]
                if not q_row.empty:
                    q_text = q_row.iloc[0]['question']
                else:
                    q_text = f"Question ID {q_id}"

            # Affichage de la question (Gras + Fond gris clair si possible, ici simple gras)
            p_quest = doc.add_paragraph()
            p_quest.paragraph_format.space_before = Pt(12)
            run_q = p_quest.add_run(f"Q{q_id} : {q_text}")
            run_q.bold = True
            run_q.font.color.rgb = RGBColor(0, 51, 102) # Bleu foncé professionnel

            # --- GESTION DES TYPES DE RÉPONSES ---
            
            # CAS 1 : Liste de fichiers (Photos multiples)
            if isinstance(answer, list) and answer and hasattr(answer[0], 'read'):
                doc.add_paragraph(f'📎 {len(answer)} photo(s) jointe(s) :', style='Caption')
                
                for idx, file_obj in enumerate(answer):
                    try:
                        # 1. Rembobiner le fichier original
                        file_obj.seek(0)
                        
                        # 2. Lire les bytes en mémoire
                        image_data = file_obj.read()
                        
                        # 3. Créer un nouveau flux IO propre pour Word (Évite les erreurs de stream closed)
                        image_stream = io.BytesIO(image_data)
                        
                        # 4. Insérer l'image
                        doc.add_picture(image_stream, width=Inches(4.5))
                        
                        # 5. Légende
                        legend = doc.add_paragraph(f"Fig {q_id}.{idx+1} - {file_obj.name}")
                        legend.alignment = WD_ALIGN_PARAGRAPH.CENTER
                        legend.runs[0].font.size = Pt(8)
                        legend.runs[0].font.italic = True
                        
                        # Rembobiner pour d'autres usages futurs (zip, etc.)
                        file_obj.seek(0)
                        
                    except Exception as e:
                        err_p = doc.add_paragraph(f"[Erreur image : {e}]")
                        err_p.runs[0].font.color.rgb = RGBColor(255, 0, 0)

            # CAS 2 : Fichier unique
            elif hasattr(answer, 'read'):
                try:
                    answer.seek(0)
                    image_data = answer.read()
                    image_stream = io.BytesIO(image_data)
                    
                    doc.add_picture(image_stream, width=Inches(4.5))
                    
                    legend = doc.add_paragraph(f"Fig {q_id} - {answer.name}")
                    legend.alignment = WD_ALIGN_PARAGRAPH.CENTER
                    
                    answer.seek(0)
                except Exception as e:
                    doc.add_paragraph(f"[Erreur image unique : {e}]")

            # CAS 3 : Texte / Nombre / Autre
            else:
                text_val = str(answer) if answer is not None else "Non répondu"
                p_rep = doc.add_paragraph(text_val)
                p_rep.paragraph_format.left_indent = Inches(0.5) # Indentation pour la réponse

        # Saut de page entre les phases (sauf la dernière)
        if phase_idx < len(collected_data) - 1:
            doc.add_page_break()

    # --- FINALISATION ---
    word_buffer = io.BytesIO()
    doc.save(word_buffer)
    word_buffer.seek(0)
    
    return word_buffer

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
