# Déploiement OVH — CB Bretagne (outil devis/facturation)

> Runbook pas-à-pas pour héberger l'appli Django sur un **VPS OVH Ubuntu 24.04**.
> Cible : `https://gestioncbb.compagnonsbatisseurs.eu` derrière nginx + Let's Encrypt,
> PostgreSQL local sur le VPS, gunicorn en service systemd.
> Remplace l'hébergement Railway (cf. NOTES_DEV § Infra — migration Phase 4).

## État actuel (15/06/2026 — session 48)

✅ **§1 à §8a terminés** — VPS opérationnel en HTTPS :
- ufw actif (OpenSSH + Nginx Full)
- PostgreSQL local, base `cbbretagne`, user `cbb`
- Code cloné dans `/srv/cbbretagne/app/`, venv + dépendances installés
- `.env` en place (SECRET_KEY, DATABASE_URL, ALLOWED_HOSTS, CSRF, SITE_URL)
- `migrate` + `collectstatic` OK (132 fichiers statiques)
- gunicorn en service systemd (`cbbretagne.service`), enabled, running
- nginx configuré : redirection 80→443 + SSL Let's Encrypt
- Login fonctionnel sur `https://vps-28c76530.vps.ovh.net` (superuser créé)
- Renouvellement certbot auto OK (`--dry-run` passé)

**Stratégie domaine : 2 étapes**
- ✅ **§8a** : HTTPS sur `vps-28c76530.vps.ovh.net` (hostname OVH, DNS déjà résolu).
- **§8b — quand DNS prêt** : certbot ajoute `gestioncbb.compagnonsbatisseurs.eu`,
  `.env` mis à jour, Railway coupé.

**⏳ En attente :**
1. **Mail IT national** → demande DNS A/AAAA + Entra ID (brouillon complet dans NOTES_DEV
   § Infra). À envoyer dès que possible pour lancer le délai humain.
2. **§8b** : DNS résolu → certbot ajoute le domaine définitif, `.env` basculé.
3. **Bascule finale** (§10) : dump Railway → restore VPS, nouvelle URL aux testeurs,
   couper Railway.

## 0. Contexte / décisions actées
- **VPS** : 4 vCore / 8 Go / 75 Go NVMe, Gravelines (FR), Ubuntu 24.04, engagement 12 mois.
  - Hostname : `vps-28c76530.vps.ovh.net`
  - IPv4 : **51.178.24.126** · IPv6 : **2001:41d0:367:4d7::1**
- **Base** : PostgreSQL **installé sur le VPS** (accès local), import du dump Railway.
- **Backups** : option OVH **Automated Backup Premium** (disque entier) + **`pg_dump`
  mensuel** (dump logique, conservation FSE) — voir § 9.
- **Python** : 3.12 (natif Ubuntu 24.04 = cible `runtime.txt`).
- **Bascule invisible pour les testeurs** : Railway reste en ligne jusqu'à ce que le
  domaine OVH soit en HTTPS ; on bascule l'URL ensuite, puis on coupe Railway.

---

## 1. Création du VPS & accès initial
1. VPS livré : IPv4 **51.178.24.126**, IPv6 **2001:41d0:367:4d7::1**,
   hostname `vps-28c76530.vps.ovh.net`. C'est l'IPv4 qu'il faut pour la demande DNS.
2. Première connexion SSH (OVH envoie les identifiants par email) :
   ```bash
   ssh ubuntu@51.178.24.126      # utilisateur ubuntu (pas root ni deploy)
   ```
3. Mises à jour :
   ```bash
   sudo apt update && sudo apt -y upgrade
   ```
4. Pare-feu minimal :
   ```bash
   sudo apt -y install ufw
   sudo ufw allow OpenSSH
   sudo ufw allow 'Nginx Full'   # 80 + 443
   sudo ufw enable
   ```

---

## 2. Paquets système
```bash
sudo apt -y install python3 python3-venv python3-pip \
                    postgresql postgresql-contrib \
                    nginx git
# (libs WeasyPrint plus tard, quand on attaquera l'export PDF — pas nécessaire ici)
```

---

## 3. PostgreSQL (base de prod locale)
```bash
sudo -u postgres psql <<'SQL'
CREATE DATABASE cbbretagne;
CREATE USER cbb WITH PASSWORD 'CHANGER_CE_MOT_DE_PASSE';
ALTER ROLE cbb SET client_encoding TO 'utf8';
ALTER ROLE cbb SET default_transaction_isolation TO 'read committed';
ALTER ROLE cbb SET timezone TO 'Europe/Paris';
GRANT ALL PRIVILEGES ON DATABASE cbbretagne TO cbb;
\c cbbretagne
GRANT ALL ON SCHEMA public TO cbb;
SQL
```
→ `DATABASE_URL = postgres://cbb:CHANGER_CE_MOT_DE_PASSE@127.0.0.1:5432/cbbretagne`

### Import du dump Railway (au moment de la bascule)
Sur ta machine (ou via `railway`), récupérer un dump de la base Railway :
```bash
# Railway expose une DATABASE_URL externe (onglet Postgres → Connect)
pg_dump --no-owner --no-privileges -Fc "$RAILWAY_DATABASE_URL" -f cbb_railway.dump
```
Copier sur le VPS puis restaurer :
```bash
scp cbb_railway.dump ubuntu@51.178.24.126:/home/deploy/
# sur le VPS :
pg_restore --no-owner --no-privileges -d cbbretagne -U cbb -h 127.0.0.1 cbb_railway.dump
```
> ⚠️ Faire l'import **juste avant** la bascule finale (sinon les données saisies sur
> Railway entre-temps seraient perdues). Pendant le montage, on peut travailler sur une
> base vide + `migrate` (+ éventuellement `seed_demo` pour tester).

---

## 4. Code + virtualenv
```bash
sudo mkdir -p /srv/cbbretagne && sudo chown deploy:deploy /srv/cbbretagne
cd /srv/cbbretagne
git clone https://github.com/pekkip/lec-henn.git app
cd app
python3 -m venv venv
venv/bin/pip install --upgrade pip
venv/bin/pip install -r requirements.txt
mkdir -p media staticfiles      # media = volume persistant (logos, annexes, PDF)
```

---

## 5. Variables d'environnement (fichier `.env`)
Créer `/srv/cbbretagne/app/.env` (lu par python-dotenv ; **chmod 600**, **jamais commité**) :
```ini
SECRET_KEY=<générer une clé longue aléatoire>
DEBUG=False
ALLOWED_HOSTS=gestioncbb.compagnonsbatisseurs.eu vps-28c76530.vps.ovh.net 127.0.0.1
DATABASE_URL=postgres://cbb:CHANGER_CE_MOT_DE_PASSE@127.0.0.1:5432/cbbretagne
CSRF_TRUSTED_ORIGINS=https://vps-28c76530.vps.ovh.net   # remplacer par le domaine définitif en §8b
SITE_URL=https://vps-28c76530.vps.ovh.net               # idem
DEFAULT_FROM_EMAIL=noreply@compagnonsbatisseurs.eu
BREVO_API_KEY=<clé Brevo actuelle — remplacée par Graph Mail.Send plus tard>
```
Générer une SECRET_KEY :
```bash
venv/bin/python -c "from django.core.management.utils import get_random_secret_key as k; print(k())"
```
> Rappels config (cf. `cbretagne/settings.py`) :
> - `ALLOWED_HOSTS` est **séparé par des espaces** (pas des virgules).
> - Dès que `DATABASE_URL` est présent **et** `DEBUG=False`, le code active
>   `SECURE_SSL_REDIRECT` + cookies secure + le storage statique hashé
>   (`CompressedManifestStaticFilesStorage`). C'est voulu — **mais ça impose
>   d'être derrière nginx en HTTPS** (§ 7), sinon boucle de redirection.

---

## 6. Premier lancement & test AVANT le domaine
Tant que le DNS ne pointe pas encore, **ne pas exposer l'IP en HTTP** (la redirection
HTTPS boucle). Tester proprement via un **tunnel SSH** :
```bash
cd /srv/cbbretagne/app
set -a; . ./.env; set +a
venv/bin/python manage.py migrate
venv/bin/python manage.py collectstatic --noinput
venv/bin/python manage.py createsuperuser   # si base vierge
venv/bin/python manage.py check --deploy
# lancer gunicorn en local sur le VPS :
venv/bin/gunicorn cbretagne.wsgi --bind 127.0.0.1:8000 --workers 3 --timeout 60
```
Depuis ta machine :
```bash
ssh -L 8000:127.0.0.1:8000 ubuntu@51.178.24.126
# puis ouvrir http://127.0.0.1:8000  (passe par le tunnel, pas d'exposition publique)
```

---

## 7. nginx + gunicorn (service systemd)

### gunicorn via systemd — `/etc/systemd/system/cbbretagne.service`
```ini
[Unit]
Description=CB Bretagne (gunicorn)
After=network.target postgresql.service

[Service]
User=deploy
Group=deploy
WorkingDirectory=/srv/cbbretagne/app
EnvironmentFile=/srv/cbbretagne/app/.env
ExecStart=/srv/cbbretagne/app/venv/bin/gunicorn cbretagne.wsgi \
          --bind 127.0.0.1:8000 --workers 3 --timeout 60
Restart=always

[Install]
WantedBy=multi-user.target
```
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now cbbretagne
sudo systemctl status cbbretagne
```

### nginx — `/etc/nginx/sites-available/cbbretagne`
```nginx
server {
    listen 80;
    server_name gestioncbb.compagnonsbatisseurs.eu vps-28c76530.vps.ovh.net;

    client_max_body_size 25M;   # uploads (logo, annexes PDF)

    location /static/ { alias /srv/cbbretagne/app/staticfiles/; }
    location /media/  { alias /srv/cbbretagne/app/media/; }

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;   # requis : settings lit ce header
    }
}
```
```bash
sudo ln -s /etc/nginx/sites-available/cbbretagne /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
```

---

## 8a. HTTPS sur hostname OVH (temporaire — faisable maintenant)

Le hostname `vps-28c76530.vps.ovh.net` est déjà résolu dans le DNS OVH, pas d'attente.

1. Installer certbot et émettre le certificat :
   ```bash
   sudo apt -y install certbot python3-certbot-nginx
   sudo certbot --nginx -d vps-28c76530.vps.ovh.net
   ```
   Certbot configure nginx en HTTPS + redirection 80→443 automatiquement.

2. Mettre à jour le `.env` sur le VPS :
   ```bash
   # Supprimer HTTPS_ONLY=False (maintenant on est bien en HTTPS)
   sed -i '/^HTTPS_ONLY/d' /srv/cbbretagne/app/.env
   # Mettre à jour CSRF et SITE_URL
   sed -i 's|^CSRF_TRUSTED_ORIGINS=.*|CSRF_TRUSTED_ORIGINS=https://vps-28c76530.vps.ovh.net|' /srv/cbbretagne/app/.env
   sed -i 's|^SITE_URL=.*|SITE_URL=https://vps-28c76530.vps.ovh.net|' /srv/cbbretagne/app/.env
   sudo systemctl restart cbbretagne
   ```

3. Vérifier le renouvellement auto :
   ```bash
   sudo certbot renew --dry-run
   ```

4. Tester `https://vps-28c76530.vps.ovh.net` → login OK, cadenas vert.

---

## 8b. Bascule domaine définitif (quand DNS IT national prêt)

1. **Demande DNS** (IT nationale, cf. NOTES_DEV § Infra point 5) : enregistrement **A**
   `gestioncbb` → **51.178.24.126** + **AAAA** → **2001:41d0:367:4d7::1**.
2. Vérifier la résolution :
   ```bash
   dig +short gestioncbb.compagnonsbatisseurs.eu     # doit renvoyer 51.178.24.126
   ```
3. Étendre le certificat existant au domaine définitif :
   ```bash
   sudo certbot --nginx -d vps-28c76530.vps.ovh.net -d gestioncbb.compagnonsbatisseurs.eu
   ```
4. Mettre à jour le `.env` sur le VPS :
   ```bash
   sed -i 's/vps-28c76530\.vps\.ovh\.net/gestioncbb.compagnonsbatisseurs.eu/g' /srv/cbbretagne/app/.env
   sudo systemctl restart cbbretagne
   ```
5. Tester `https://gestioncbb.compagnonsbatisseurs.eu` → login OK, cadenas vert.

---

## 9. Backups
- **Automated Backup Premium (OVH)** : activé à la commande — sauvegarde le disque
  entier (donc Postgres + media). Vérifier la fréquence/rétention dans l'espace client.
- **Snapshot (OVH)** : à déclencher **manuellement avant chaque grosse manip** de la
  migration (rollback rapide).
- **`pg_dump` mensuel (dump logique, conservation FSE)** — cron du user `deploy` :
  ```bash
  mkdir -p /srv/cbbretagne/backups
  crontab -e
  # → dump le 1er de chaque mois à 2h, rétention 18 mois :
  0 2 1 * * pg_dump -Fc "postgres://cbb:MDP@127.0.0.1:5432/cbbretagne" \
            -f /srv/cbbretagne/backups/cbb_$(date +\%Y\%m).dump
  0 3 1 * * find /srv/cbbretagne/backups -name 'cbb_*.dump' -mtime +540 -delete
  ```

---

## 10. Bascule finale & post-migration
1. Annoncer une courte fenêtre (ou non — la beta tolère).
2. **Re-dump Railway → restore VPS** (§ 3) pour récupérer les dernières saisies.
3. Vérifier l'appli sur le domaine HTTPS (login, devis, planning, upload logo).
4. Communiquer la **nouvelle URL** aux testeurs.
5. **Couper Railway** (garder le projet quelques jours en secours avant suppression).
6. Mettre à jour NOTES_DEV § Infra (migration faite) + cocher les items dépendants
   (export PDF WeasyPrint, restriction email à décommenter, HSTS, demande IT Graph).

## 11. Copie de fichiers media (logos, uploads)

Le dossier `media/` n'est **pas dans git**. Pour copier un fichier depuis la machine locale :
```powershell
scp "chemin/local/fichier.png" ubuntu@51.178.24.126:/srv/cbbretagne/app/media/logo/
```
Créer le sous-dossier si besoin (depuis le VPS) :
```bash
mkdir -p /srv/cbbretagne/app/media/logo
```
Nginx sert `/media/` directement (alias `/srv/cbbretagne/app/media/`), pas de redémarrage nécessaire.

---

## 12. Déploiements suivants (mise à jour du code)
Script fourni à la racine du repo : **`deploy.sh`** (rejoue la séquence du `Procfile`
Railway, en une commande, avec arrêt au premier échec). Après le `git clone` initial,
le rendre exécutable une fois :
```bash
cd /srv/cbbretagne/app
chmod +x deploy.sh
```
Ensuite, à chaque mise à jour :
```bash
cd /srv/cbbretagne/app
./deploy.sh
```
Il fait : `git pull` → `pip install -r requirements.txt` → `migrate` →
`collectstatic --noinput` → `systemctl restart cbbretagne`.

> Note : `deploy.sh` appelle `sudo systemctl restart cbbretagne`. Pour éviter le mot de
> passe à chaque déploiement, autoriser ce seul redémarrage sans mot de passe —
> `sudo visudo -f /etc/sudoers.d/cbbretagne` :
> ```
> deploy ALL=(root) NOPASSWD: /usr/bin/systemctl restart cbbretagne
> ```
