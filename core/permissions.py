# core/permissions.py

from .models import ProfilUtilisateur


def get_profil_or_none(user):
    """
    Retourne le profil ou None si inexistant.
    Ne crée jamais de profil — contrairement à views.get_profil qui fait un
    get_or_create. À utiliser dans tout contexte en lecture seule (permissions)
    où un effet de bord en écriture serait incorrect.
    """
    try:
        return user.profil
    except ProfilUtilisateur.DoesNotExist:
        return None


def is_admin(user):
    profil = get_profil_or_none(user)
    return profil and profil.role == 'admin'


def is_responsable(user):
    profil = get_profil_or_none(user)
    return profil and profil.role in ('admin', 'responsable')


def is_comptable(user):
    profil = get_profil_or_none(user)
    return profil and profil.role == 'comptable'


def get_techniciens(user):
    """Retourne les profils des techniciens sous ce responsable."""
    profil = get_profil_or_none(user)
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
        createur_profil = get_profil_or_none(devis.created_by)
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
    profil = get_profil_or_none(user)
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


def peut_voir_devis(user, devis):
    """
    Peut consulter un devis (lecture seule) ?

    Règle métier : tout utilisateur connecté peut consulter n'importe quel devis
    et ses factures (outil interne, visibilité partagée entre équipes). La
    restriction par équipe s'applique uniquement à la *modification*
    (peut_modifier_devis / peut_modifier_facture).

    Le paramètre `devis` est conservé pour permettre une restriction future
    sans changer les appels.
    """
    return user.is_authenticated


def peut_envoyer_facture(user, facture):
    """
    Peut envoyer une facture en validation ?

    Même règle que peut_modifier_devis, appliquée au devis parent de la facture.
    """
    if not user.is_authenticated:
        return False
    profil = get_profil_or_none(user)
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


def peut_voir_facture(user, facture):
    """Peut consulter une facture (lecture seule) ? Via le devis parent."""
    return peut_voir_devis(user, facture.devis)


def peut_modifier_facture(user, facture):
    """
    Peut modifier une facture (statut, lignes, date de versement, libellé) ?

    Comme peut_envoyer_facture mais autorise aussi le comptable, qui gère le
    cycle de vie de la facture. La validation reste régie par peut_valider_facture.
    """
    if not user.is_authenticated:
        return False
    profil = get_profil_or_none(user)
    if not profil:
        return False

    # Admin et comptable → accès total
    if profil.role in ('admin', 'comptable'):
        return True

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
    profil = get_profil_or_none(user)
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
    profil = get_profil_or_none(user)
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


# ══════════════════════════════════════════
#  GESTION UTILISATEURS
# ══════════════════════════════════════════

def peut_gerer_utilisateurs(user):
    """
    Peut accéder à la gestion des utilisateurs ?

    - Admin : gère tous les utilisateurs du système
    - Responsable : gère uniquement les membres de ses équipes
    """
    if not user.is_authenticated:
        return False
    profil = get_profil_or_none(user)
    return profil and profil.role in ('admin', 'responsable')


def peut_gerer_cet_utilisateur(user, cible_profil):
    """
    Peut modifier/désactiver un utilisateur précis ?

    - Admin : oui, toujours (sauf lui-même — géré dans la vue)
    - Responsable : uniquement si la cible partage une de ses équipes
      et n'est pas admin
    """
    if not user.is_authenticated:
        return False
    profil = get_profil_or_none(user)
    if not profil:
        return False

    # Admin → accès total
    if profil.role == 'admin':
        return True

    # Responsable → uniquement les membres de ses équipes, pas les admins
    if profil.role == 'responsable':
        if cible_profil.role == 'admin':
            return False
        equipes_responsable = profil.equipes.values_list('pk', flat=True)
        return cible_profil.equipes.filter(pk__in=equipes_responsable).exists()

    return False
