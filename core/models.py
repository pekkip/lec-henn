from django.db import models
from django.contrib.auth.models import User
from decimal import Decimal, ROUND_HALF_UP


# ══════════════════════════════════════════
#  STRUCTURE ORGANISATIONNELLE
# ══════════════════════════════════════════

class Territoire(models.Model):
    nom = models.CharField(max_length=200)
    code = models.CharField(max_length=20, blank=True, help_text="Ex: 35, 29, COB")
    ordre = models.IntegerField(default=0)

    class Meta:
        ordering = ['ordre', 'nom']
        verbose_name = 'Territoire'

    def __str__(self):
        return self.nom


class Service(models.Model):
    territoire = models.ForeignKey(
        Territoire, on_delete=models.PROTECT, related_name='services'
    )
    nom = models.CharField(max_length=200)
    module_planning = models.BooleanField(
        default=False,
        help_text="Ce service utilise le module Planning & Émargement (salariés en insertion)"
    )
    conditions_devis = models.TextField(
        blank=True,
        help_text="Conditions de vente affichées sur les devis de ce service"
    )
    conditions_facture = models.TextField(
        blank=True,
        help_text="Conditions de vente affichées sur les factures de ce service"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['territoire', 'nom']
        verbose_name = 'Service'

    def __str__(self):
        return f"{self.territoire} — {self.nom}"


class Equipe(models.Model):
    ACTIVITE_CHOICES = [
        ('gros_oeuvre',   'Gros œuvre'),
        ('second_oeuvre', 'Second œuvre'),
    ]
    service = models.ForeignKey(
        Service, on_delete=models.PROTECT, related_name='equipes'
    )
    nom = models.CharField(max_length=200)
    ordre = models.IntegerField(default=0)
    # ── Module Planning (insertion) ──
    encadrant = models.ForeignKey(
        User, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='equipes_encadrees',
        help_text="Chef d'équipe fixe (= ETI sur la fiche d'émargement)"
    )
    activite = models.CharField(
        max_length=20, choices=ACTIVITE_CHOICES, blank=True,
        help_text="Filtre du suivi de production (gros / second œuvre)"
    )
    nb_equipiers = models.PositiveSmallIntegerField(
        default=4,
        help_text="Effectif théorique (base de calcul de la durée en planning)"
    )
    financeurs = models.ManyToManyField(
        'Financeur', blank=True, related_name='equipes',
        help_text="Financeurs affichés au pied de la fiche d'émargement"
    )
    nom_programme = models.CharField(
        max_length=200, blank=True,
        help_text="Nom complet réglementaire du chantier d'insertion (ex. 'Atelier de Quartier Saint-Malo')"
    )
    heures_matin_defaut = models.DecimalField(
        max_digits=4, decimal_places=2, default=Decimal('4.00'),
        help_text="Heures par défaut pour la demi-journée matin (émargement)"
    )
    heures_aprem_defaut = models.DecimalField(
        max_digits=4, decimal_places=2, default=Decimal('3.00'),
        help_text="Heures par défaut pour la demi-journée après-midi (émargement)"
    )
    afficher_plie = models.BooleanField(
        default=False,
        help_text="Afficher le tampon PLIE en en-tête de la fiche d'émargement mensuelle"
    )
    actif = models.BooleanField(default=True)

    class Meta:
        ordering = ['service', 'ordre', 'nom']
        verbose_name = 'Équipe'

    def __str__(self):
        return f"{self.service} — {self.nom}"


# ══════════════════════════════════════════
#  PROFIL UTILISATEUR
# ══════════════════════════════════════════

class ProfilUtilisateur(models.Model):
    ROLE_CHOICES = [
        ('admin',        'Administrateur'),
        ('responsable',  'Responsable de service'),
        ('technicien',   'Technicien / Chargé de projet'),
        ('comptable',    'Comptable'),
        ('rh',           'Ressources humaines'),
        ('encadrant',    'Encadrant / ETI'),
    ]
    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name='profil'
    )
    role = models.CharField(
        max_length=20, choices=ROLE_CHOICES, default='technicien'
    )
    service = models.ForeignKey(
        Service, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='membres',
        help_text="Service d'appartenance principal"
    )
    equipes = models.ManyToManyField(
        Equipe, blank=True, related_name='membres',
        help_text="Équipes habituelles (filtre par défaut dans les listes)"
    )
    responsable = models.ForeignKey(
    'self', on_delete=models.SET_NULL,
    null=True, blank=True, related_name='techniciens',
    help_text="Responsable hiérarchique direct (Responsable secteur)"
    )
    # Préférences personnelles
    taux_mo_defaut = models.DecimalField(
        max_digits=6, decimal_places=2, default=46.00
    )
    saisie_ht = models.BooleanField(
        default=False,
        help_text="Prix matériaux saisis HT, convertis en TTC (+20%)"
    )
    categories_biblio = models.JSONField(
        default=list, blank=True,
        help_text="Ordre et visibilité des catégories dans la bibliothèque"
    )
    dashboard_config = models.JSONField(
        default=dict, blank=True,
        help_text="Disposition du tableau de bord (widgets, ordre, portée)"
    )
    production_config = models.JSONField(
        default=dict, blank=True,
        help_text="Disposition du suivi de production (widgets, ordre, portée)"
    )
    telephone = models.CharField(
        max_length=50, blank=True,
        help_text="Tél. de l'encadrant (affiché comme ETI sur la fiche d'émargement)"
    )
    invitation_envoyee = models.BooleanField(
        default=False,
        help_text="Email d'invitation envoyé avec succès"
    )
    conditions_devis = models.TextField(blank=True)
    conditions_facture = models.TextField(blank=True)
    coordonnees_cb = models.TextField(
        blank=True,
        help_text="Coordonnées CB affichées sur les devis/factures (nom, fonction, tél.)"
    )

    class Meta:
        verbose_name = 'Profil utilisateur'

    def __str__(self):
        return f"{self.user} ({self.get_role_display()})"

    def get_territoire(self):
        return self.service.territoire if self.service else None

    def is_admin(self):
        return self.role == 'admin'

    def is_responsable(self):
        return self.role in ('admin', 'responsable')

    def is_comptable(self):
        return self.role == 'comptable'

    def peut_voir_compta(self):
        # Accès OUTILS COMPTA — extensible 'responsable' plus tard.
        return self.role in ('admin', 'comptable')

    # Règles d'accès devis/facture : voir core.permissions (source unique).


class Bibliotheque(models.Model):
    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name='bibliotheque'
    )
    lignes = models.JSONField(
        default=list, blank=True,
        help_text="Arbre JSON identique aux lignes de devis"
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Bibliothèque'

    def __str__(self):
        return f"Bibliothèque de {self.user}"


# ══════════════════════════════════════════
#  BIBLIOTHÈQUE AIDES (partagée)
# ══════════════════════════════════════════

class BibliothequeAides(models.Model):
    TYPE_CHOICES = [
        ('FMO',  "Forfait main d'œuvre"),
        ('FMAT', 'Forfait matériaux'),
        ('FIN',  'Aide travaux CBB'),
        ('FINX', 'Financement organisme'),
    ]
    description = models.CharField(max_length=300)
    type_ligne = models.CharField(max_length=5, choices=TYPE_CHOICES, default='FIN')
    montant_defaut = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    unite = models.CharField(max_length=50, default='forfait', blank=True)
    organisme = models.CharField(max_length=200, blank=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, related_name='aides_creees'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['description']
        verbose_name = 'Aide / financement'
        verbose_name_plural = 'Aides / financements'

    def __str__(self):
        return self.description

# ══════════════════════════════════════════
#  PARAMÈTRES ASSOCIATION
# ══════════════════════════════════════════

class ParametresAssociation(models.Model):
    nom = models.CharField(max_length=200, default='Compagnons Bâtisseurs Bretagne')
    siret = models.CharField(max_length=50, blank=True)
    ape = models.CharField(max_length=20, blank=True)
    forme_juridique = models.CharField(
        max_length=100, blank=True, default='Association loi 1901'
    )
    adresse = models.TextField(blank=True)
    email = models.EmailField(blank=True)
    telephone = models.CharField(max_length=50, blank=True)
    site_web = models.URLField(blank=True)
    logo = models.ImageField(
        upload_to='logo/', null=True, blank=True
    )
    signature = models.ImageField(
        upload_to='signature/', null=True, blank=True,
        help_text="Signature + cachet de la directrice (PNG transparent recommandé)"
    )
    couleur_principale = models.CharField(
        max_length=7, default='#6B1F3A',
        help_text="Code hexadécimal ex: #6B1F3A"
    )
    couleur_secondaire = models.CharField(
        max_length=7, default='#2BBFA4',
        help_text="Code hexadécimal ex: #2BBFA4"
    )
    couleur_accent = models.CharField(
        max_length=7, default='#E8A020',
        help_text="Code hexadécimal ex: #E8A020"
    )
    slogan = models.CharField(
        max_length=200, blank=True,
        default='La solidarité, un chantier à partager'
    )
    # ── Module Planning (insertion) ──
    taux_jour_facturable = models.DecimalField(
        max_digits=8, decimal_places=2, default=Decimal('472.00'),
        help_text="Convertit le coût MO d'un devis en jours facturables (coût MO / taux)"
    )
    cout_jour_salarie = models.DecimalField(
        max_digits=8, decimal_places=2, default=Decimal('82.50'),
        help_text="Coût d'un salarié·jour (pour la colonne coût réel du suivi de production)"
    )

    class Meta:
        verbose_name = 'Paramètres association'

    def __str__(self):
        return self.nom

    def save(self, *args, **kwargs):
        # Garantit une seule instance
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


# ══════════════════════════════════════════
#  CLIENTS
# ══════════════════════════════════════════

class Client(models.Model):
    TYPE_CLIENT_CHOICES = [
        ('particulier',  'Particulier'),
        ('association',  'Association'),
        ('bailleur',     'Bailleur'),
        ('collectivite', 'Collectivité'),
        ('autre',        'Autre'),
    ]
    nom = models.CharField(max_length=200)
    type_client = models.CharField(
        max_length=20, choices=TYPE_CLIENT_CHOICES, default='particulier'
    )
    contact = models.CharField(max_length=200, blank=True)
    email = models.EmailField(blank=True)
    telephone = models.CharField(max_length=50, blank=True)
    adresse = models.TextField(blank=True, help_text="Rue / voie")
    code_postal = models.CharField(max_length=10, blank=True)
    ville = models.CharField(max_length=100, blank=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='clients_crees'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['nom']
        verbose_name = 'Client'

    def __str__(self):
        return self.nom


class ContactClient(models.Model):
    """
    Carnet de contacts optionnel d'un client (1..n).
    Permet de distinguer plusieurs services / interlocuteurs au sein d'une même
    structure (ex. collectivité : "Direction du patrimoine", "Service Jardins").
    Créé à la demande — un particulier ou une association n'en a généralement aucun.
    """
    client = models.ForeignKey(
        Client, on_delete=models.CASCADE, related_name='contacts'
    )
    service = models.CharField(
        max_length=200, blank=True,
        help_text="Service destinataire (ex. Direction du patrimoine)"
    )
    nom = models.CharField(max_length=200, blank=True, help_text="Interlocuteur / technicien")
    fonction = models.CharField(max_length=200, blank=True)
    email = models.EmailField(blank=True)
    telephone = models.CharField(max_length=50, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['service', 'nom']
        verbose_name = 'Contact client'

    def __str__(self):
        parts = [p for p in (self.service, self.nom) if p]
        return ' — '.join(parts) if parts else f"Contact #{self.pk}"


# ══════════════════════════════════════════
#  BIBLIOTHÈQUE D'ARTICLES
# ══════════════════════════════════════════

class Categorie(models.Model):
    nom = models.CharField(max_length=100)
    ordre = models.IntegerField(default=0)

    class Meta:
        ordering = ['ordre', 'nom']
        verbose_name = 'Catégorie'

    def __str__(self):
        return self.nom


class Article(models.Model):
    TYPE_CHOICES = [
        ('F', 'Forfait'),
        ('S', 'Ouvrage simple'),
        ('C', 'Ouvrage composite'),
    ]
    categorie = models.ForeignKey(
        Categorie, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='articles'
    )
    # Si proprietaire est null → article partagé (visible par tous)
    # Si proprietaire est renseigné → article personnel
    proprietaire = models.ForeignKey(
        User, on_delete=models.CASCADE,
        null=True, blank=True, related_name='articles_perso',
        help_text="Null = article partagé, renseigné = bibliothèque personnelle"
    )
    type = models.CharField(max_length=1, choices=TYPE_CHOICES)
    nom = models.CharField(max_length=200)
    description = models.CharField(max_length=300, blank=True)
    cout_unitaire = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    unite = models.CharField(max_length=50, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['categorie', 'nom']
        verbose_name = 'Article'

    def __str__(self):
        return self.nom


# ══════════════════════════════════════════
#  DEVIS
# ══════════════════════════════════════════

class Devis(models.Model):
    STATUS_CHOICES = [
        ('draft',    'Brouillon'),
        ('sent',     'Envoyé'),
        ('accepted', 'Accepté'),
        ('refused',  'Refusé'),
        ('expired',  'Expiré'),
    ]
    reference = models.CharField(max_length=50, unique=True)
    client = models.ForeignKey(
        Client, on_delete=models.PROTECT, related_name='devis'
    )
    equipe = models.ForeignKey(
        Equipe, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='devis'
    )

    chantier = models.CharField(max_length=300)
    # Adresse du chantier
    chantier_adresse1 = models.CharField(max_length=200, blank=True)
    chantier_adresse2 = models.CharField(max_length=200, blank=True)
    chantier_cp = models.CharField(max_length=10, blank=True)
    chantier_ville = models.CharField(max_length=100, blank=True)

    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='draft'
    )
    date_creation = models.DateField(auto_now_add=True)
    date_validite = models.DateField(null=True, blank=True)
    taux_mo = models.DecimalField(
        max_digits=6, decimal_places=2, default=46.00
    )
    notes = models.TextField(blank=True)
    conditions_devis = models.TextField(
        blank=True,
        help_text="Conditions de vente pour ce devis (copié depuis les préférences à la création)"
    )
    coordonnees_cb = models.TextField(
        blank=True,
        help_text="Coordonnées CB du contact pour ce devis (copié depuis le profil à la création)"
    )

    fin_group_title = models.CharField(
        max_length=100, default='Financements',
        help_text="Titre du groupe de financements"
    )
    zone_financement = models.BooleanField(default=False)
    zone_financement_ext = models.BooleanField(default=False)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL,
        null=True, related_name='devis_crees'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Devis'
        verbose_name_plural = 'Devis'

    def __str__(self):
        return f"{self.reference} — {self.client}"

    def total_brut(self):
        return sum(
            l.total() for l in self.lignes.filter(parent=None)
            if l.type_ligne not in ('FIN', 'FINX')
        )

    def total_financement(self):
        return sum(
            l.total() for l in self.lignes.filter(parent=None, type_ligne__in=['FIN', 'FINX'])
        )

    def net_client(self):
        return self.total_brut() - self.total_financement()

    def total_facture(self):
        # Somme directe : un avoir porte un montant négatif (quantités inversées),
        # il se déduit donc naturellement du total.
        return sum(
            f.montant for f in self.factures.exclude(status='cancelled')
            if f.type_doc in ('facture', 'acompte', 'avoir')
        )

    def reste_a_facturer(self):
        # Arrondi au centime des deux côtés AVANT la soustraction : total_brut() est
        # en pleine précision, alors que total_facture() somme des montants de factures
        # déjà arrondis au centime. Sans cet arrondi, un devis entièrement facturé
        # affichait un reste fantôme de ±0,01 € (ex. 8222,525 − 8222,53 = −0,005).
        cents = Decimal('0.01')
        brut = Decimal(self.total_brut()).quantize(cents, rounding=ROUND_HALF_UP)
        facture = Decimal(self.total_facture()).quantize(cents, rounding=ROUND_HALF_UP)
        return brut - facture


# ══════════════════════════════════════════
#  LIGNES DE DEVIS
# ══════════════════════════════════════════

class LigneDevis(models.Model):
    TYPE_CHOICES = [
        ('F',     'Forfait'), # supprimer?
        ('FMO',   'Forfait main d\'œuvre'),
        ('FMAT',  'Forfait matériaux'),
        ('S',     'Ouvrage simple'),
        ('C',     'Ouvrage composite'),
        ('MO',    'Main d\'œuvre'),
        ('MAT',   'Matériau'),
        ('OUV',   'Sous-ouvrage'),
        ('FIN',   'Aide travaux CBB'),
        ('FINX',  'Financement organisme'),
        ('TITRE', 'Titre'),
    ]
    devis = models.ForeignKey(
        Devis, on_delete=models.CASCADE, related_name='lignes'
    )
    parent = models.ForeignKey(
        'self', on_delete=models.CASCADE,
        null=True, blank=True, related_name='enfants'
    )
    type_ligne = models.CharField(max_length=5, choices=TYPE_CHOICES)
    description = models.TextField(blank=True)
    quantite = models.DecimalField(
        max_digits=10, decimal_places=3, default=1
    )
    unite = models.CharField(max_length=50, blank=True)
    cout_unitaire = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    ordre = models.IntegerField(default=0)
    ouvert = models.BooleanField(default=True)
    aide = models.ForeignKey(
        'BibliothequeAides', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='utilisations'
    )

    class Meta:
        ordering = ['ordre']
        verbose_name = 'Ligne de devis'

    def __str__(self):
        return f"{self.description} ({self.devis.reference})"

    def prix_unitaire(self):
        if self.cout_unitaire is not None:
            return self.cout_unitaire
        if self.quantite and self.quantite != 0:
            return self.total() / self.quantite
        return Decimal('0')

    def total(self):
        enfants = self.enfants.all()
        if self.type_ligne == 'TITRE':
            return sum(e.total() for e in enfants)
        if enfants.exists():
            return self.quantite * sum(e.total() for e in enfants)
        if self.cout_unitaire is not None:
            return self.quantite * self.cout_unitaire
        return Decimal('0')

    def total_mo(self):
        enfants = self.enfants.all()
        if not enfants.exists():
            # FMO (Forfait MO) doit être inclus — bug corrigé
            return self.quantite * (self.cout_unitaire or 0) if self.type_ligne in ('MO', 'FMO') else Decimal('0')
        mult = Decimal('1') if self.type_ligne == 'TITRE' else self.quantite
        return mult * sum(e.total_mo() for e in enfants)

    def total_mat(self):
        enfants = self.enfants.all()
        if not enfants.exists():
            return self.quantite * (self.cout_unitaire or 0) if self.type_ligne == 'MAT' else Decimal('0')
        mult = Decimal('1') if self.type_ligne == 'TITRE' else self.quantite
        return mult * sum(e.total_mat() for e in enfants)


# ══════════════════════════════════════════
#  FACTURES & AVOIRS
# ══════════════════════════════════════════

class Facture(models.Model):
    TYPE_DOC_CHOICES = [
        ('facture', 'Facture'),
        ('acompte', "Facture d'acompte"),
        ('appel', "Facture d'appel convention"),
        ('structure', 'Facture structure'),
        ('avoir',   'Avoir'),
    ]
    STATUS_CHOICES = [
        ('draft',     'Brouillon'),
        ('validated', 'Validée'),
        ('sent',      'Envoyée'),
        ('paid',      'Payée'),
        ('cancelled', 'Annulée'),
    ]
    # Le numéro n'est assigné qu'à la validation
    numero = models.CharField(
        max_length=50, unique=True, null=True, blank=True,
        help_text="Assigné automatiquement à la validation"
    )
    type_doc = models.CharField(
        max_length=10, choices=TYPE_DOC_CHOICES, default='facture'
    )
    devis = models.ForeignKey(
        Devis, on_delete=models.PROTECT, related_name='factures',
        null=True, blank=True,
        help_text="Optionnel : factures compta (structure/appel) créées sans devis"
    )
    # Lien client direct (factures compta sans devis ; pour les factures de devis,
    # le client reste accessible via devis.client — voir get_client())
    client = models.ForeignKey(
        Client, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='factures_directes'
    )
    contact_client = models.ForeignKey(
        'ContactClient', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='factures'
    )
    # Avoir → facture créditée (lignes copiées avec quantités inversées)
    facture_origine = models.ForeignKey(
        'self', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='avoirs'
    )
    destinataire = models.CharField(max_length=200)
    montant = models.DecimalField(
        max_digits=10, decimal_places=2, default=0
    )
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='draft'
    )
    date_creation = models.DateField(auto_now_add=True)
    date_echeance = models.DateField(null=True, blank=True)
    date_versement = models.DateField(
    null=True, blank=True,
    help_text="Date de versement de l'acompte (renseignée sur la facture normale)"
    )
    notes = models.TextField(blank=True)

    libelle = models.CharField(
        max_length=200, blank=True,
        help_text="Court libellé affiché dans le récapitulatif des factures précédentes"
    # PROTO : éditable inline dans l'éditeur de facture.
    )

    conditions_facture = models.TextField(
        blank=True,
        help_text="Conditions de vente pour cette facture"
    )
    coordonnees_cb = models.TextField(
        blank=True,
        help_text="Coordonnées CB (snapshot à la création depuis le profil) — "
                  "utilisé pour les factures compta sans devis"
    )
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL,
        null=True, related_name='factures_creees'
    )
    validated_by = models.ForeignKey(
        User, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='factures_validees'
    )
    validated_at = models.DateTimeField(null=True, blank=True)
    bypass_validation = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Facture'

    def __str__(self):
        ref = self.numero or f"BROUILLON-{self.pk}"
        return f"{ref} — {self.destinataire}"

    def get_reference(self):
        """Référence interne (outil) — proforma affiché « BROUILLON »."""
        return self.numero or f"BROUILLON-{self.pk}"

    def get_reference_client(self):
        """Référence affichée sur les éditions client — proforma préfixé « PF- »."""
        return self.numero or f"PF-{self.pk}"

    @property
    def is_compta(self):
        """Facture des outils compta (création directe sans devis)."""
        return self.type_doc in ('structure', 'appel')

    def get_client(self):
        """Client effectif : lien direct (compta) ou via le devis."""
        return self.client or (self.devis.client if self.devis else None)


# ══════════════════════════════════════════
#  LIGNES DE FACTURE
# ══════════════════════════════════════════

class LigneFacture(models.Model):
    """Copie des lignes du devis au moment de la création de la facture."""
    TYPE_CHOICES = LigneDevis.TYPE_CHOICES

    facture = models.ForeignKey(
        Facture, on_delete=models.CASCADE, related_name='lignes'
    )
    parent = models.ForeignKey(
        'self', on_delete=models.CASCADE,
        null=True, blank=True, related_name='enfants'
    )
    type_ligne = models.CharField(max_length=5, choices=TYPE_CHOICES)
    description = models.TextField(blank=True)
    quantite = models.DecimalField(
        max_digits=10, decimal_places=3, default=1
    )
    quantite_originale = models.DecimalField(
        max_digits=10, decimal_places=3, default=1,
        help_text="Quantité du devis original, pour référence"
    )
    unite = models.CharField(max_length=50, blank=True)
    cout_unitaire = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    ordre = models.IntegerField(default=0)
    ouvert = models.BooleanField(default=True)
    
    ligne_devis_source = models.ForeignKey(
        'LigneDevis',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='lignes_factures',
        help_text="Ligne du devis à l'origine de cette ligne de facture"
        # PROTO : permet le calcul du 'déjà facturé' par ligne.
    )

    class Meta:
        ordering = ['ordre']
        verbose_name = 'Ligne de facture'

    def total(self):
        enfants = self.enfants.all()
        if self.type_ligne == 'TITRE':
            if self.quantite == 0:
                return Decimal('0')
            return self.quantite * sum(e.total() for e in enfants)
        if enfants.exists():
            return self.quantite * sum(e.total() for e in enfants)
        if self.cout_unitaire is not None:
            return self.quantite * self.cout_unitaire
        return Decimal('0')

    def prix_unitaire(self):
        if self.type_ligne == 'TITRE':
            return None
        if self.cout_unitaire is not None:
            return self.cout_unitaire
        t = self.total()
        if self.quantite and self.quantite != 0:
            return t / self.quantite
        return None


# ══════════════════════════════════════════
#  JOURNAL D'AUDIT
# ══════════════════════════════════════════

class AuditLog(models.Model):
    user = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True
    )
    action = models.TextField()
    devis = models.ForeignKey(
        Devis, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='audit_logs'
    )
    facture = models.ForeignKey(
        Facture, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='audit_logs'
    )
    bypass = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Journal d\'audit'

    def __str__(self):
        return f"{self.created_at:%d/%m/%Y %H:%M} — {self.action[:60]}"


# ══════════════════════════════════════════
#  PLANNING & ÉMARGEMENT (insertion)
# ══════════════════════════════════════════
#
#  Principe directeur : la PRÉSENCE est la SOURCE UNIQUE. L'encadrant pointe une
#  seule fois (équipier × demi-journée), rattaché à une affectation (donc à un
#  chantier). On en dérive sans re-saisie : la fiche d'émargement mensuelle
#  (paie) ET le suivi de production (jours facturables / réalisés / écart).
#
#  Le chantier n'est PAS choisi cellule par cellule : il vient de l'affectation
#  de l'équipe. Un équipier n'est sur un autre chantier que s'il est prêté à une
#  autre équipe (sa présence pointe alors vers l'affectation de cette équipe).
#
#  Semaine travaillée = lundi→jeudi. Le vendredi se décide par équipe
#  (Affectation.vendredi_actif) ; samedi/dimanche jamais travaillés. Le calcul
#  des jours ouvrés exclut le vendredi sauf activation explicite.


class Financeur(models.Model):
    """Référentiel des financeurs (pied de page réglementaire de la fiche)."""
    nom = models.CharField(max_length=200)
    logo_cle = models.CharField(
        max_length=100, blank=True,
        help_text="Clé d'un logo statique embarqué (base64), comme le logo CB"
    )
    ordre = models.IntegerField(default=0)

    class Meta:
        ordering = ['ordre', 'nom']
        verbose_name = 'Financeur'

    def __str__(self):
        return self.nom


class Equipier(models.Model):
    """
    Personne à pointer (salarié en insertion). Modèle léger sans compte.
    Rattachée à une équipe « maison » mais empruntable par toute autre équipe.
    Porte les infos contrat nécessaires à la fiche d'émargement réglementaire.
    """
    nom = models.CharField(max_length=100)
    prenom = models.CharField(max_length=100)
    equipe = models.ForeignKey(
        Equipe, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='equipiers',
        help_text="Équipe « maison » (rattachement par défaut)"
    )
    matricule = models.CharField(
        max_length=50, blank=True,
        help_text="Identifiant RH stable (clé pour l'import futur)"
    )
    type_contrat = models.CharField(
        max_length=100, blank=True, default='CDDI - 26 heures'
    )
    heures_contrat_hebdo = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal('26.00'),
        help_text="Base contractuelle hebdomadaire (pour le calcul de récup)"
    )
    date_debut_contrat = models.DateField(null=True, blank=True)
    date_fin_contrat = models.DateField(null=True, blank=True)
    date_visite_medicale = models.DateField(null=True, blank=True)
    recup_base_heures = models.DecimalField(
        max_digits=6, decimal_places=2, default=0,
        help_text="Solde de récup de départ (saisi une fois)"
    )
    recup_base_date = models.DateField(
        null=True, blank=True,
        help_text="Date du solde de récup de départ"
    )
    droit_conges_jours = models.DecimalField(
        max_digits=6, decimal_places=2, default=0,
        help_text="Droit à congés (géré par la RH, non dérivé)"
    )
    actif = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['nom', 'prenom']
        verbose_name = 'Équipier'

    def __str__(self):
        return f"{self.prenom} {self.nom}"


class TrancheDevis(models.Model):
    """
    Découpage d'un chantier (devis) en blocs planifiables — PAS de Gantt/dépendances.
    Tranche par défaut = « Chantier complet » (titres vides = tout le devis).
    Le découpage en plusieurs tranches (par grand titre) est un commit ultérieur,
    UI seule (le schéma est déjà en place).
    """
    devis = models.ForeignKey(
        Devis, on_delete=models.CASCADE, related_name='tranches'
    )
    STATUT_CHOICES = [
        ('en_cours', 'En cours'),
        ('termine',  'Terminé (à facturer)'),
        ('facture',  'Facturé'),
    ]
    nom = models.CharField(max_length=200, default='Chantier complet')
    ordre = models.IntegerField(default=0)
    titres = models.ManyToManyField(
        LigneDevis, blank=True, related_name='tranches',
        help_text="TITRE racines couverts (vide = tout le devis)"
    )
    # ── Clôture de chantier (signal « à facturer » du dashboard insertion) ──
    statut = models.CharField(
        max_length=10, choices=STATUT_CHOICES, default='en_cours',
        help_text="termine = clôturé sur la timeline (à facturer) ; facture = signal levé"
    )
    termine_le = models.DateField(null=True, blank=True)
    termine_par = models.ForeignKey(
        User, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='chantiers_clotures'
    )

    class Meta:
        ordering = ['devis', 'ordre']
        verbose_name = 'Tranche de devis'
        verbose_name_plural = 'Tranches de devis'

    def __str__(self):
        return f"{self.devis.reference} — {self.nom}"


class Affectation(models.Model):
    """
    Dépose une tranche de chantier sur une équipe pour une période.
    Pas d'unique_together : une même tranche peut être posée plusieurs fois
    → multi-équipe natif (parallèle, renfort temporaire, passation).
    Le budget jours est porté par la tranche (un seul pool) ; les jours réalisés
    agrègent les présences de TOUTES les affectations de la tranche (pas de
    double comptage).
    """
    equipe = models.ForeignKey(
        Equipe, on_delete=models.CASCADE, related_name='affectations'
    )
    tranche = models.ForeignKey(
        TrancheDevis, on_delete=models.CASCADE, related_name='affectations'
    )
    date_debut = models.DateField(null=True, blank=True)
    date_fin = models.DateField(null=True, blank=True)
    duree_jours = models.DecimalField(
        max_digits=6, decimal_places=2, null=True, blank=True,
        help_text="Longueur planifiée en jours ouvrés (défaut = jours facturables, "
                  "ajustable aux poignées) — référence du décalage en cascade et du prévu"
    )
    epingle = models.BooleanField(
        default=False,
        help_text="Date fixe : exclue du décalage automatique (chantier à échéance)"
    )
    vendredi_actif = models.BooleanField(
        default=False,
        help_text="Déprécié — remplacé par les événements Evenement(travaille=True)"
    )
    debut_creneau = models.CharField(
        max_length=5,
        choices=[('matin', 'Matin'), ('aprem', 'Après-midi')],
        default='matin',
    )
    fin_creneau = models.CharField(
        max_length=5,
        choices=[('matin', 'Matin'), ('aprem', 'Après-midi')],
        default='aprem',
    )
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='affectations_creees'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['date_debut']
        verbose_name = 'Affectation'

    def __str__(self):
        return f"{self.equipe.nom} → {self.tranche}"


class Evenement(models.Model):
    """
    Exception calendrier sur le planning.
    - travaille=False (défaut) : journée non travaillée (formation, férié…) — si decale_chantier=True,
      repousse automatiquement les date_fin des affectations chevauchantes.
    - travaille=True : journée normalement non-ouvrée devenue ouvrée (vendredi de rattrapage, etc.)
      → avance les date_fin des affectations concernées.
    equipes vide = événement global (toutes équipes).
    """
    TYPE_CHOICES = [
        ('formation',     'Formation'),
        ('visite',        'Visite'),
        ('reunion',       'Réunion'),
        ('journee_ferie', 'Pont → Récup'),
        ('jour_sup',      'Jour supplémentaire'),
        ('autre',         'Autre'),
    ]
    CRENEAU_CHOICES = [
        ('matin',   'Matin'),
        ('aprem',   'Après-midi'),
        ('journee', 'Journée'),
    ]
    # Legacy FK — conservé pour la compatibilité schéma ; utiliser equipes (M2M) désormais
    equipe = models.ForeignKey(
        Equipe, on_delete=models.SET_NULL, related_name='evenements_legacy',
        null=True, blank=True,
    )
    equipes = models.ManyToManyField(
        Equipe, blank=True, related_name='evenements',
        verbose_name='Équipes concernées (vide = toutes)',
    )
    type = models.CharField(max_length=20, choices=TYPE_CHOICES, default='autre')
    libelle = models.CharField(max_length=200, blank=True)
    date_debut = models.DateField()
    date_fin = models.DateField(null=True, blank=True)
    creneau = models.CharField(
        max_length=10, choices=CRENEAU_CHOICES, default='journee', blank=True,
    )
    decale_chantier = models.BooleanField(
        default=False,
        help_text="Recalcule automatiquement les date_fin des chantiers couverts"
    )
    travaille = models.BooleanField(
        default=False,
        help_text="True = jour normalement non-ouvré devient ouvré (vendredi de rattrapage…)",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['date_debut']
        verbose_name = 'Événement'

    def __str__(self):
        return f"{self.get_type_display()} — {self.libelle or '(sans libellé)'}"


class Presence(models.Model):
    """
    Émargement réel — la donnée cœur. Une ligne = un équipier sur une demi-journée.
    Présent = cellule avec des heures (pas de code « P »). Les codes ne servent
    qu'aux absences ; un code renseigné ⇒ heures = 0.
    L'affectation porte l'équipe + la tranche (donc le chantier via tranche.devis).
    unique_together garantit qu'un équipier n'est qu'à un seul endroit par
    demi-journée (gère le prêt entre équipes).
    """
    CRENEAU_CHOICES = [
        ('matin', 'Matin'),
        ('aprem', 'Après-midi'),
    ]
    CODE_CHOICES = [
        ('C',     'Congé'),
        ('R',     'Récupération'),
        ('M',     'Maladie'),
        ('AT',    'Accident du travail'),
        ('A',     'Absence'),
        ('AJ',    'Absence justifiée non rémunérée'),
        ('S',     'Suspension'),
        ('PMSMP', 'PMSMP'),
        ('DE',    'Démarches externes'),
        ('DI',    'Démarches internes'),
        ('F',     'Férié'),
    ]
    equipier = models.ForeignKey(
        Equipier, on_delete=models.CASCADE, related_name='presences'
    )
    affectation = models.ForeignKey(
        Affectation, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='presences'
    )
    date = models.DateField()
    creneau = models.CharField(max_length=10, choices=CRENEAU_CHOICES)
    heures = models.DecimalField(
        max_digits=4, decimal_places=2, default=0,
        help_text="Heures travaillées sur ce demi-journée (au quart d'heure)"
    )
    code = models.CharField(
        max_length=10, choices=CODE_CHOICES, blank=True,
        help_text="Code d'absence (vide = présent)"
    )
    observation = models.CharField(max_length=300, blank=True)
    # Traçabilité paie : qui a pointé, quand.
    saisi_par = models.ForeignKey(
        User, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='presences_saisies'
    )
    saisi_le = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('equipier', 'date', 'creneau')
        ordering = ['date', 'creneau']
        verbose_name = 'Présence'

    def __str__(self):
        return f"{self.equipier} — {self.date:%d/%m/%Y} {self.get_creneau_display()}"


class ClotureMois(models.Model):
    """
    Verrou mensuel par équipe : une fois la fiche remise à la RH (le 27),
    on clôture le mois pour empêcher toute modification rétroactive des présences.
    """
    equipe = models.ForeignKey(
        Equipe, on_delete=models.CASCADE, related_name='clotures'
    )
    annee = models.IntegerField()
    mois = models.IntegerField()
    cloture_par = models.ForeignKey(
        User, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='clotures_faites'
    )
    cloture_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('equipe', 'annee', 'mois')
        ordering = ['-annee', '-mois']
        verbose_name = 'Clôture mensuelle'

    def __str__(self):
        return f"{self.equipe.nom} — {self.mois:02d}/{self.annee}"


class FicheNote(models.Model):
    """
    Override chantier et observation par équipier + semaine ISO.
    Écrit depuis l'émargement hebdo ou la fiche mensuelle.
    Partagé par les deux vues (même donnée, deux points d'entrée).
    """
    equipier    = models.ForeignKey(
        Equipier, on_delete=models.CASCADE, related_name='fiche_notes'
    )
    annee       = models.PositiveSmallIntegerField()
    mois        = models.PositiveSmallIntegerField()
    num_semaine = models.PositiveSmallIntegerField()
    chantier_texte    = models.CharField(max_length=200, blank=True)
    observation_texte = models.TextField(blank=True)

    class Meta:
        unique_together = ('equipier', 'annee', 'mois', 'num_semaine')
        verbose_name = 'Note de fiche'
        verbose_name_plural = 'Notes de fiche'

    def __str__(self):
        return f"{self.equipier} — S{self.num_semaine}/{self.annee}"


class Pret(models.Model):
    """Prêt temporaire d'un équipier à une équipe hôte."""
    equipier = models.ForeignKey(
        Equipier, on_delete=models.CASCADE, related_name='prets'
    )
    equipe_hote = models.ForeignKey(
        Equipe, on_delete=models.CASCADE, related_name='prets_recus'
    )
    CRENEAU_CHOICES = [('matin', 'Matin'), ('aprem', 'Après-midi')]
    date_debut    = models.DateField()
    creneau_debut = models.CharField(max_length=10, choices=CRENEAU_CHOICES, default='matin')
    date_fin      = models.DateField()
    creneau_fin   = models.CharField(max_length=10, choices=CRENEAU_CHOICES, default='aprem')
    cree_par = models.ForeignKey(
        User, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='prets_crees'
    )
    cree_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['date_debut']
        unique_together = ('equipier', 'equipe_hote')
        verbose_name = "Prêt d'équipier"
        verbose_name_plural = "Prêts d'équipiers"

    def __str__(self):
        return f"{self.equipier} → {self.equipe_hote} ({self.date_debut}–{self.date_fin})"