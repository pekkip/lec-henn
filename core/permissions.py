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


def _partage_equipe_devis(profil, devis):
    """
    Vérifie si l'utilisateur a accès au devis via l'équipe.

    Deux cas :
      - Le devis est rattaché à une équipe ET l'utilisateur en fait partie
      - L'utilisateur est le responsable hiérarchique du créateur du devis
        (couvre le cas responsable hors équipe mais chef de l'auteur)
    """
    # Cas 1 — même équipe que le devis
    if devis.equipe and profil.equipes.filter(pk=devis.equipe.pk).exists():
        return True

    # Cas 2 — responsable hiérarchique du créateur
    if devis.created_by:
        createur_profil = get_profil(devis.created_by)
        if createur_profil and createur_profil.responsable == profil:
            return True

    return False


def peut_modifier_devis(user, devis):
    """
    Peut modifier un devis ?

    Autorisé si :
      - admin
      - créateur du devis
      - membre de l'équipe du devis
      - responsable hiérarchique du créateur
    """
    if not user.is_authenticated:
        return False
    profil = get_profil(user)
    if not profil:
        return False

    # Admin → accès total
    if profil.role == 'admin':
        return True

    # Comptable → jamais sur les devis
    if profil.role == 'comptable':
        return False

    # Créateur du devis
    if devis.created_by == user:
        return True

    # Équipe ou responsable hiérarchique
    if _partage_equipe_devis(profil, devis):
        return True

    return False


def peut_supprimer_devis(user, devis):
    """Peut supprimer un devis ? Uniquement les brouillons."""
    if devis.status != 'draft':
        return False
    return peut_modifier_devis(user, devis)


def peut_envoyer_facture(user, facture):
    """
    Peut envoyer une facture en validation ?

    Même règle que peut_modifier_devis, appliquée au devis parent de la facture.
    """
    if not user.is_authenticated:
        return False
    profil = get_profil(user)
    if not profil:
        return False

    # Admin → accès total
    if profil.role == 'admin':
        return True

    # Comptable → non
    if profil.role == 'comptable':
        return False

    # Créateur de la facture
    if facture.created_by == user:
        return True

    # Accès via le devis parent (équipe ou responsable)
    if _partage_equipe_devis(profil, facture.devis):
        return True

    return False


def peut_valider_facture(user, facture):
    """
    Peut modifier/valider un brouillon de facture ?
    Réservé à l'admin et au comptable.
    """
    if not user.is_authenticated:
        return False
    profil = get_profil(user)
    if not profil:
        return False

    if profil.role == 'admin':
        return True

    # Comptable uniquement sur les brouillons
    if profil.role == 'comptable' and facture.status == 'draft':
        return True

    return False


def peut_supprimer_facture(user, facture):
    """
    Peut supprimer une facture ?
    Jamais si validée, envoyée ou payée.
    """
    if facture.status in ('validated', 'sent', 'paid'):
        return False
    if not user.is_authenticated:
        return False
    profil = get_profil(user)
    if not profil:
        return False

    # Admin → accès total
    if profil.role == 'admin':
        return True

    # Comptable → non
    if profil.role == 'comptable':
        return False

    # Créateur de la facture
    if facture.created_by == user:
        return True

    # Accès via le devis parent (équipe ou responsable)
    if _partage_equipe_devis(profil, facture.devis):
        return True

    return False


def peut_supprimer_client(user):
    """Suppression client réservée à l'admin."""
    return is_admin(user)