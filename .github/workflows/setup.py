from setuptools import setup

setup(
    name='my_shared_utils',
    version='0.1',
    py_modules=['utils'],  # Ceci dit à pip d'inclure le fichier utils.py
    install_requires=[
        'streamlit',
        'pandas',
        'firebase-admin',
        'numpy',
        'python-docx'
    ]
)
