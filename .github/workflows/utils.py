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

# --- CONSTANTES (inchangées) ---
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

# --- INITIALISATION FIREBASE (MODIFIÉE) ---
def initialize_firebase():
    """Initialise Firebase si ce n'est pas déjà fait et retourne le client Firestore.
    Lit les secrets Streamlit au niveau racine (firebase_...).
    """
    if not firebase_admin._apps:
        try:
            # --- MODIFICATION ICI ---
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
            # ------------------------
            
            project_id = cred_dict["project_id"]
            cred = credentials.Certificate(cred_dict)
            firebase_admin.initialize_app(cred, {'projectId': project_id})
        except Exception as e:
            st.error(f"Erreur de connexion Firebase : {e}")
            # Ligne originale commentée pour debug: st.stop()
            st.stop()
    return firestore.client()

# Initialisation unique du client DB pour ce module
db = initialize_firebase()

# --- CHARGEMENT DONNÉES (inchangé) ---
@st.cache_data(ttl=3600)
def load_form_structure_from_firestore():
    # ... reste du code inchangé ...
# ...
@st.cache_data(ttl=3600)
def load_site_data_from_firestore():
    # ... reste du code inchangé ...
# ...

# --- LOGIQUE MÉTIER (inchangée) ---
def get_expected_photo_count(section_name, project_data):
    # ... reste du code inchangé ...
# ...
def check_condition(row, current_answers, collected_data):
    # ... reste du code inchangé ...
# ...
def validate_section(df_questions, section_name, answers, collected_data, project_data):
    # ... reste du code inchangé ...
# ...

# --- SAUVEGARDE ET EXPORTS (inchangés) ---
def save_form_data(collected_data, project_data, submission_id, start_time):
    # ... reste du code inchangé ...
# ...
def create_csv_export(collected_data, df_struct, project_name, submission_id, start_time):
    # ... reste du code inchangé ...
# ...
def create_zip_export(collected_data):
    # ... reste du code inchangé ...
# ...
def define_custom_styles(doc):
    # ... reste du code inchangé ...
# ...
def create_word_report(collected_data, df_struct, project_data, start_time):
    # ... reste du code inchangé ...
# ...

# --- COMPOSANT UI (inchangé) ---
def render_question(row, answers, phase_name, key_suffix, loop_index, project_data):
    # ... reste du code inchangé ...
