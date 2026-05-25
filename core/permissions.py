# core/permissions.py

def get_profil(user):
    """Retourne le profil ou None si inexistant."""
    try:
        return user.profil
    except Exception:
        return None


def is_admin(user):
    profil = get_profil(user)
    return profil and profil.role == 'admin'


def is_responsable(user):
    profil = get_profil(user)
    return profil and profil.role in ('admin', 'responsable')


def is_comptable(user):
    profil = get_profil(user)
    return profil and profil.role == 'comptable'


def get_techniciens(user):
    """Retourne les profils des techniciens sous ce responsable."""
    profil = get_profil(user)
    if not profil:
        return []
    return list(profil.techniciens.all())


def peut_modifier_devis(user, devis):
    """Peut modifier un devis ?"""
    if not user.is_authenticated:
        return False
    profil = get_profil(user)
    if not profil:
        return False
    if profil.role == 'admin':
        return True
    if profil.role == 'comptable':
        return False
    # Créateur du devis
    if devis.created_by == user:
        return True
    # Responsable d'un technicien qui a créé le devis
    if profil.role == 'responsable':
        createur_profil = get_profil(devis.created_by)
        if createur_profil and createur_profil.responsable == profil:
            return True
    return False


def peut_supprimer_devis(user, devis):
    """Peut supprimer un devis ? Uniquement les brouillons."""
    if devis.status != 'draft':
        return False
    return peut_modifier_devis(user, devis)


def peut_envoyer_facture(user, facture):
    """Peut envoyer une facture en validation ?"""
    if not user.is_authenticated:
        return False
    profil = get_profil(user)
    if not profil:
        return False
    if profil.role == 'admin':
        return True
    if profil.role == 'comptable':
        return False
    if facture.created_by == user:
        return True
    if profil.role == 'responsable':
        createur_profil = get_profil(facture.created_by)
        if createur_profil and createur_profil.responsable == profil:
            return True
    return False


def peut_valider_facture(user, facture):
    """Peut modifier/valider un brouillon de facture (rôle comptable) ?"""
    if not user.is_authenticated:
        return False
    profil = get_profil(user)
    if not profil:
        return False
    if profil.role == 'admin':
        return True
    if profil.role == 'comptable' and facture.status == 'draft':
        return True
    return False


def peut_supprimer_facture(user, facture):
    """Peut supprimer une facture ? Jamais si validée."""
    if facture.status in ('validated', 'sent', 'paid'):
        return False
    if not user.is_authenticated:
        return False
    profil = get_profil(user)
    if not profil:
        return False
    if profil.role == 'admin':
        return True
    if profil.role == 'comptable':
        return False
    if facture.created_by == user:
        return True
    if profil.role == 'responsable':
        createur_profil = get_profil(facture.created_by)
        if createur_profil and createur_profil.responsable == profil:
            return True
    return False


def peut_supprimer_client(user):
    """Suppression client réservée à l'admin."""
    return is_admin(user)