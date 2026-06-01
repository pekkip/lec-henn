from django.db import models
from django.contrib.auth.models import User
from decimal import Decimal


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
    service = models.ForeignKey(
        Service, on_delete=models.PROTECT, related_name='equipes'
    )
    nom = models.CharField(max_length=200)
    ordre = models.IntegerField(default=0)

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
    nom = models.CharField(max_length=200)
    contact = models.CharField(max_length=200, blank=True)
    email = models.EmailField(blank=True)
    telephone = models.CharField(max_length=50, blank=True)
    adresse = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['nom']
        verbose_name = 'Client'

    def __str__(self):
        return self.nom


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
            if l.type_ligne != 'FIN'
        )

    def total_financement(self):
        return sum(
            l.total() for l in self.lignes.filter(parent=None, type_ligne='FIN')
        )

    def net_client(self):
        return self.total_brut() - self.total_financement()

    def total_facture(self):
        return sum(
            f.montant for f in self.factures.exclude(status='cancelled')
            if f.type_doc in ('facture', 'acompte')
        ) - sum(
            f.montant for f in self.factures.exclude(status='cancelled')
            if f.type_doc == 'avoir'
        )

    def reste_a_facturer(self):
        return self.total_brut() - self.total_facture()


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
        ('FIN',   'Financement'),
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
            return self.quantite * (self.cout_unitaire or 0) if self.type_ligne == 'MO' else Decimal('0')
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
        Devis, on_delete=models.PROTECT, related_name='factures'
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
        return self.numero or f"BROUILLON-{self.pk}"


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
            return sum(e.total() for e in enfants)
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