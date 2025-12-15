# utils.py (À placer dans votre repository partagé 'shared-utils')
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
    # Ajoutez ici d'autres sections nécessitant des calculs de photos si nécessaire
}

COMMENT_ID = 100
COMMENT_QUESTION = "Veuillez préciser pourquoi le nombre de photo partagé ne correspond pas au minimum attendu"

# --- INITIALISATION FIREBASE ---
def initialize_firebase():
    """
    Initialise Firebase si ce n'est pas déjà fait. 
    Lit les secrets Streamlit au niveau racine (firebase_...).
    """
    if not firebase_admin._apps:
        try:
            # Lecture des secrets sans la section [firebase]
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

# Initialisation unique du client DB pour ce module
db = initialize_firebase()

# --- CHARGEMENT DONNÉES (mise en cache) ---
@st.cache_data(ttl=3600)
# utils.py
# ... (imports) ...

@st.cache_data(ttl=3600)
def load_form_structure_from_firestore():
    """Charge la structure du formulaire depuis la collection 'formsquestions'."""
    try:
        docs = db.collection('formsquestions').order_by('id').get()
        data = [doc.to_dict() for doc in docs]
        if not data: return None
        df = pd.DataFrame(data)
        df.columns = df.columns.str.strip()
        
        # NORMALISATION DES NOMS DE COLONNES (Gère 'Conditon' -> 'Condition')
        rename_map = {
            'Conditon value': 'Condition value', 'condition value': 'Condition value', 
            'Condition Value': 'Condition value', 'Condition': 'Condition value', 
            'Conditon on': 'Condition on', 'condition on': 'Condition on'
        }
        actual_rename = {k: v for k, v in rename_map.items() if k in df.columns}
        df = df.rename(columns=actual_rename)
        
        expected_cols = ['options', 'Description', 'Condition value', 'Condition on', 'section', 'id', 'question', 'type', 'obligatoire']
        for col in expected_cols:
            if col not in df.columns: df[col] = np.nan 
        
        # Nettoyage et typage de la colonne 'Condition on'
        df['options'] = df['options'].fillna('')
        df['Description'] = df['Description'].fillna('')
        df['Condition value'] = df['Condition value'].fillna('')
        # On s'assure que 'Condition on' est un entier (1 ou 0)
        df['Condition on'] = df['Condition on'].apply(lambda x: int(x) if pd.notna(x) and str(x).isdigit() and str(x).strip() in ('1', '0') else 0)
        
        # ... (reste du nettoyage) ...
        return df
    except Exception as e:
        st.error(f"Erreur lors du chargement de la structure du formulaire: {e}")
        return None

@st.cache_data(ttl=3600)
def load_site_data_from_firestore():
    """Charge les données des sites depuis la collection 'Sites'."""
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
    """Calcule le nombre de photos attendues pour une section donnée."""
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
                # Convertit la valeur en entier (gère les formats décimaux avec virgule/point)
                num = int(float(str(val).replace(',', '.'))) 
        except Exception:
            num = 0
        
        total_expected += num
        short_name = PROJECT_RENAME_MAP.get(col, col) 
        details.append(f"{num} {short_name}")

    detail_str = " + ".join(details)
    return total_expected, detail_str

# utils.py
# ... (autres fonctions) ...

# utils.py
# ... (autres fonctions) ...

# utils.py
# ... (autres fonctions) ...

def _evaluate_simple_term(term_string, combined_answers):
    """
    Évalue une sous-condition simple (ex: "10 = Oui" ou "9 <> Non")
    et retourne True ou False.
    """
    # Nettoyage de la chaîne de comparaison pour gérer les espaces et les guillemets
    term = term_string.strip().upper()
    
    # Déterminer l'opérateur de comparaison
    if ' <> ' in term:
        op_raw = ' <> '
        op_python = ' != '
    elif ' = ' in term:
        op_raw = ' = '
        op_python = ' == '
    else:
        # Cas non supporté ou mal formaté (on considère que la condition est fausse)
        return False
        
    try:
        question_num_str, expected_value_str = term_string.split(op_raw.strip(), 1)
        
        q_num = int(question_num_str.strip())
        expected_value = expected_value_str.strip().strip('"').strip("'")
        
        # Récupérer la réponse réelle (mise en string et minuscule pour comparaison)
        user_answer = combined_answers.get(q_num)
        
        # Si la question n'a pas été répondue, le terme est Faux
        if user_answer is None:
            return False

        # On convertit TOUJOURS la réponse utilisateur en chaîne de caractères pour la comparaison
        actual_answer_str = str(user_answer).strip().lower()
        
        # La valeur attendue doit aussi être en minuscule pour la comparaison (robustesse)
        expected_value_lower = expected_value.lower()
        
        # Note : On fait la comparaison manuellement au lieu d'utiliser eval pour cette sous-condition 
        # afin de mieux gérer les chaînes de caractères et la robustesse de la DB.
        
        if op_python == ' == ':
            return actual_answer_str == expected_value_lower
        elif op_python == ' != ':
            return actual_answer_str != expected_value_lower
        
        return False # Fallback de sécurité

    except Exception as e:
        # print(f"DEBUG Erreur d'évaluation du terme '{term_string}' : {e}")
        return False # En cas d'erreur de parsing, le terme est Faux
        
        
def check_condition(row, current_answers, collected_data):
    """
    Vérifie si une question doit être affichée en fonction des réponses précédentes.
    Supporte les conditions multiples avec ET et OU, ainsi que les opérateurs = et <>.
    """
    
    # 1. Vérification si la question est conditionnelle (Condition on == 1)
    try:
        if int(row.get('Condition on', 0)) != 1: return True
    except (ValueError, TypeError): 
        return True

    # 2. Agrégation de toutes les réponses passées et courantes
    all_past_answers = {}
    for phase_data in collected_data: 
        if 'answers' in phase_data and isinstance(phase_data['answers'], dict):
             all_past_answers.update(phase_data['answers'])
             
    combined_answers = {**all_past_answers, **current_answers}
    
    # 3. Parsing de la condition (ex: "10 = Oui ET 9 <> Non")
    condition_str = str(row.get('Condition value', '')).strip()
    
    # --- NETTOYAGE AGRESSIF DE LA CHAÎNE DE CONDITION ---
    # Enlève les guillemets/apostrophes qui pourraient entourer la chaîne entière
    while condition_str.startswith('"') and condition_str.endswith('"'):
        condition_str = condition_str[1:-1].strip()
    while condition_str.startswith("'") and condition_str.endswith("'"):
        condition_str = condition_str[1:-1].strip()
        
    if not condition_str or ("=" not in condition_str and "<>" not in condition_str): 
        return True

    # 4. Remplacement des opérateurs logiques pour le parsing
    
    # On met tout en majuscule pour la recherche
    temp_string = condition_str.upper() 
    
    # Remplacer les opérateurs logiques par des délimiteurs
    temp_string = temp_string.replace(' ET ', '|||AND|||')
    temp_string = temp_string.replace(' OU ', '|||OR|||')
    
    # Séparation par les délimiteurs pour obtenir les termes simples et les opérateurs
    parts = temp_string.split('|||')
    
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
            term_result = _evaluate_simple_term(part, combined_answers)
            # Ajout du résultat booléen (True ou False) à l'expression à évaluer
            final_expression_eval += str(term_result)

    # 6. Évaluation de l'expression complète
    if not final_expression_eval.strip():
        return False
        
    try:
        # L'expression est maintenant sécurisée, par exemple: "True and False or True"
        return eval(final_expression_eval)
    except Exception as e:
        # print(f"DEBUG Erreur d'évaluation finale : {e}")
        return False # En cas d'erreur, ne pas afficher la question

# --- SAUVEGARDE ET EXPORTS (inchangées) ---
def save_form_data(collected_data, project_data, submission_id, start_time):
    # ... code inchangé ...
    try:
        cleaned_data = []
        for phase in collected_data:
            clean_phase = {
                "phase_name": phase["phase_name"],
                "answers": {}
            }
            # Remplace les objets FileUpload par des noms de fichiers
            for k, v in phase["answers"].items():
                if isinstance(v, list) and v and hasattr(v[0], 'read'): 
                    file_names = ", ".join([f.name for f in v])
                    clean_phase["answers"][str(k)] = f"Fichiers (non stockés en DB): {file_names}"
                
                elif hasattr(v, 'read'): 
                     clean_phase["answers"][str(k)] = f"Fichier (non stocké en DB): {v.name}"
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
    # ... code inchangé ...
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
                final_val = f"[Pièces jointes] {len(val)} fichiers: " + ", ".join([f.name for f in val])
            elif hasattr(val, 'name'):
                final_val = f"[Pièce jointe] {val.name}"
            else:
                final_val = str(val)
            
            rows.append({
                "ID Formulaire": submission_id,
                "Date Début": start_time_str,
                "Date Fin": end_time_str,
                "Projet": project_name,
                "Phase": phase_name,
                "ID": q_id,
                "Question": q_text,
                "Réponse": final_val
            })
            
    df_export = pd.DataFrame(rows)
    return df_export.to_csv(index=False, sep=';', encoding='utf-8-sig')

def create_zip_export(collected_data):
    # ... code inchangé ...
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
                        except Exception as e:
                            pass 
                            
        info_txt = f"Export généré le {datetime.now()}\nNombre de fichiers : {files_added}"
        zip_file.writestr("info.txt", info_txt)
    
    zip_buffer.seek(0)
    return zip_buffer

def define_custom_styles(doc):
    # ... code inchangé ...
    # Style de titre principal
    try: title_style = doc.styles.add_style('Report Title', WD_STYLE_TYPE.PARAGRAPH)
    except: title_style = doc.styles['Report Title']
    title_style.base_style = doc.styles['Heading 1']
    title_font = title_style.font
    title_font.name = 'Arial'
    title_font.size = Pt(20)
    title_font.bold = True
    title_font.color.rgb = RGBColor(0x01, 0x38, 0x2D)
    title_style.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title_style.paragraph_format.space_after = Pt(20)

    # Style de sous-titre de section
    try: subtitle_style = doc.styles.add_style('Report Subtitle', WD_STYLE_TYPE.PARAGRAPH)
    except: subtitle_style = doc.styles['Report Subtitle']
    subtitle_style.base_style = doc.styles['Heading 2']
    subtitle_font = subtitle_style.font
    subtitle_font.name = 'Arial'
    subtitle_font.size = Pt(14)
    subtitle_font.bold = True
    subtitle_font.color.rgb = RGBColor(0x00, 0x56, 0x47)
    subtitle_style.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.LEFT
    subtitle_style.paragraph_format.space_after = Pt(10)

    # Style de texte normal
    try: text_style = doc.styles.add_style('Report Text', WD_STYLE_TYPE.PARAGRAPH)
    except: text_style = doc.styles['Report Text']
    text_style.base_style = doc.styles['Normal']
    text_font = text_style.font
    text_font.name = 'Calibri'
    text_font.size = Pt(11)
    text_font.color.rgb = RGBColor(0x00, 0x00, 0x00)
    text_style.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    text_style.paragraph_format.space_after = Pt(5)

    doc.styles['Normal'].font.name = 'Calibri'
    doc.styles['Normal'].font.size = Pt(11)

def create_word_report(collected_data, df_struct, project_data, start_time):
    # ... code inchangé ...
    doc = Document()
    define_custom_styles(doc)
    
    # --- Page de garde/Titre ---
    doc.add_paragraph('Rapport d\'Audit Chantier', style='Report Title')
    doc.add_paragraph('Informations du Projet', style='Report Subtitle')
    
    # Tableau d'informations de base
    project_table = doc.add_table(rows=3, cols=2)
    project_table.style = 'Light Grid Accent 1'
    project_table.rows[0].cells[0].text = 'Intitulé'
    project_table.rows[0].cells[1].text = str(project_data.get('Intitulé', 'N/A'))
    
    start_time_str = start_time.strftime('%d/%m/%Y %H:%M') if start_time else datetime.now().strftime('%d/%m/%Y %H:%M')
    project_table.rows[1].cells[0].text = 'Date de début'
    project_table.rows[1].cells[1].text = start_time_str
    project_table.rows[2].cells[0].text = 'Date de fin'
    project_table.rows[2].cells[1].text = datetime.now().strftime('%d/%m/%Y %H:%M')
    
    for row in project_table.rows:
        for cell in row.cells:
            for paragraph in cell.paragraphs:
                paragraph.style = 'Report Text'
    doc.add_paragraph()
    
    # Détails du projet (Bornes)
    doc.add_paragraph('Détails du Projet', style='Report Subtitle')
    for group in DISPLAY_GROUPS:
        for field_key in group:
            renamed_key = PROJECT_RENAME_MAP.get(field_key, field_key)
            value = project_data.get(field_key, 'N/A')
            p = doc.add_paragraph(style='Report Text')
            p.add_run(f'{renamed_key}: ').bold = True
            p.add_run(str(value))
    
    doc.add_page_break()
    
    # --- Contenu par Phase ---
    for phase_idx, phase in enumerate(collected_data):
        phase_name = phase['phase_name']
        doc.add_paragraph(f'Phase: {phase_name}', style='Report Subtitle')
        
        for q_id, answer in phase['answers'].items():
            # Récupération du texte de la question
            if int(q_id) == COMMENT_ID:
                q_text = "Commentaire explicatif de l'écart photo par rapport au nombre attendu"
            else:
                if not df_struct.empty:
                    q_row = df_struct[df_struct['id'] == int(q_id)]
                    q_text = q_row.iloc[0]['question'] if not q_row.empty else f"Question ID {q_id}"
                else:
                    q_text = f"Question ID {q_id}"
            
            # 1. Traitement des réponses de type PHOTO
            is_photo_answer = False
            if isinstance(answer, list) and answer and hasattr(answer[0], 'read'):
                is_photo_answer = True
            elif hasattr(answer, 'read'):
                is_photo_answer = True
                
            if is_photo_answer:
                doc.add_paragraph(f'Q{q_id}: {q_text}', style='Report Subtitle')
                if isinstance(answer, list):
                     doc.add_paragraph(f'Nombre de photos: {len(answer)}', style='Report Text')
                     for idx, file_obj in enumerate(answer):
                         try:
                             file_obj.seek(0)
                             image_data = file_obj.read()
                             if image_data:
                                 image_stream = io.BytesIO(image_data)
                                 doc.add_picture(image_stream, width=Inches(5)) 
                                 caption = doc.add_paragraph(f'Photo {idx+1}: {file_obj.name}', style='Report Text')
                                 caption.alignment = WD_ALIGN_PARAGRAPH.CENTER
                                 caption.runs[0].font.size = Pt(9)
                                 caption.runs[0].font.italic = True
                                 file_obj.seek(0)
                         except Exception as e:
                             doc.add_paragraph(f'[Erreur photo {idx+1}: {e}]', style='Report Text')
                doc.add_paragraph()

            # 2. Traitement des autres types de réponses (texte, nombre, select)
            else:
                table = doc.add_table(rows=1, cols=2)
                table.style = 'Light Grid Accent 1'
                q_cell = table.cell(0, 0)
                q_cell.text = f'Q{q_id}: {q_text}'
                q_cell.width = Inches(5.0)
                a_cell = table.cell(0, 1)
                a_cell.text = str(answer)
                a_cell.width = Inches(1.0)
                for cell in table.rows[0].cells:
                    cell.paragraphs[0].style = 'Report Text'
                    cell.paragraphs[0].paragraph_format.left_indent = None 
                    cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER 
                q_cell.paragraphs[0].runs[0].bold = True
                doc.add_paragraph()
        
        if phase_idx < len(collected_data) - 1:
            doc.add_page_break()
    
    word_buffer = io.BytesIO()
    doc.save(word_buffer)
    word_buffer.seek(0)
    return word_buffer

# --- COMPOSANT UI (rendu de la question) ---
# utils.py - Fonction render_question (complète)

# ... (Le reste du code de utils.py reste inchangé) ...

# --- COMPOSANT UI (rendu de la question) ---
# utils.py - Fonction render_question (complète et corrigée)
# ... (N'oubliez pas les imports et le reste de votre fichier utils.py) ...

# --- COMPOSANT UI (rendu de la question) ---
def render_question(row, answers, phase_name, key_suffix, loop_index, project_data):
    """
    Rendu d'une question dans Streamlit. Modifie le dictionnaire 'answers' en place.
    
    Toutes les questions de type 'number' sont désormais traitées comme des entiers.
    """
    q_id = int(row.get('id', 0))
    is_dynamic_comment = q_id == COMMENT_ID
    
    if is_dynamic_comment:
        q_text = COMMENT_QUESTION
        q_type = 'text' 
        q_desc = "Ce champ est obligatoire si le nombre de photos n'est pas conforme."
        q_mandatory = True 
        q_options = []
    else:
        q_text = row['question']
        # Ligne cruciale : on nettoie et met en minuscule pour une comparaison robuste
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
    
    # Étape de débogage temporaire : 
    # st.write(f"DEBUG: Q_ID={q_id}, Q_TYPE='{q_type}'") 

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
    
    # --- LOGIQUE AUTOMATIQUE POUR NUMBER (FORCÉ EN ENTIER) ---
    elif q_type == 'number': # Cette condition doit être TRUE
        
        label = "Nombre (Entier)"
        # On s'assure que la valeur par défaut est un entier (0 si invalide)
        try:
            default_val = int(float(current_val)) if current_val is not None and str(current_val).replace('.', '', 1).isdigit() else 0
        except:
            default_val = 0
            
        val = st.number_input(
            label, 
            value=default_val, 
            step=1,             # <-- LIGNE CRUCIALE : Force le pas de 1
            format="%d",         # <-- LIGNE CRUCIALE : Force l'affichage entier
            key=widget_key, 
            label_visibility="collapsed"
        )
    # --------------------------------------------------------
    
    elif q_type == 'photo':
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
        if q_type == 'number':
             answers[q_id] = int(val) # <-- LIGNE CRUCIALE : Force le stockage en entier
        else:
            answers[q_id] = val 
    elif current_val is not None and not is_dynamic_comment: 
        answers[q_id] = current_val 
    elif is_dynamic_comment and (val is None or str(val).strip() == ""):
        if q_id in answers: del answers[q_id]
