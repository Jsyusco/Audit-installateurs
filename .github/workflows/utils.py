# utils.py
# ... (autres fonctions) ...

def check_condition(row, current_answers, collected_data):
    """Vérifie si une question doit être affichée en fonction des réponses précédentes."""
    
    # 1. Vérification si la question est conditionnelle (Condition on == 1)
    try:
        # Utilisation de 'Condition on' (le nom normalisé)
        if int(row.get('Condition on', 0)) != 1: return True
    except (ValueError, TypeError): 
        # En cas d'erreur de conversion (si la valeur n'est pas un nombre), on assume non conditionnel
        return True

    # 2. Agrégation de toutes les réponses passées et courantes
    all_past_answers = {}
    for phase_data in collected_data: 
        # S'assurer que 'answers' est bien un dictionnaire
        if 'answers' in phase_data and isinstance(phase_data['answers'], dict):
             all_past_answers.update(phase_data['answers'])
             
    combined_answers = {**all_past_answers, **current_answers}
    
    # 3. Parsing de la condition ("9 = Oui")
    condition_str = str(row.get('Condition value', '')).strip()
    if not condition_str or "=" not in condition_str: 
        # Si la condition est vide ou mal formatée, on affiche la question
        return True

    try:
        target_id_str, expected_value_raw = condition_str.split('=', 1)
        target_id = int(target_id_str.strip())
        expected_value = expected_value_raw.strip().strip('"').strip("'").lower() # On nettoie et met en minuscule l'attendu
        
        user_answer = combined_answers.get(target_id)
        
        # 4. Comparaison des réponses
        if user_answer is not None:
            # On convertit TOUJOURS la réponse utilisateur en chaîne de caractères, 
            # puis en minuscule, pour une comparaison fiable.
            actual_answer_str = str(user_answer).lower()
            
            return actual_answer_str == expected_value
        else:
            # Si la question cible n'a pas encore été répondue, la condition n'est pas remplie
            return False
            
    except Exception: 
        # En cas d'erreur de parsing (ex: ID cible non numérique), on affiche la question
        return True
