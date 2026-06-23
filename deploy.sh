#!/usr/bin/env bash
#
# Déploiement OVH — mise à jour de l'appli après l'installation initiale.
# Séquence pip → migrate → collectstatic → restart, en une commande.
# Usage (sur le VPS, depuis /srv/cbbretagne/app) :  ./deploy.sh
#
# set -e  : stoppe au premier échec (pas de redémarrage sur du code cassé)
# set -u  : erreur si une variable non définie est utilisée
# set -o pipefail : un échec au milieu d'un pipe fait échouer la ligne
set -euo pipefail

cd "$(dirname "$0")"          # se placer dans le dossier du script (= racine de l'app)

echo "→ git pull"
git pull

echo "→ dépendances"
venv/bin/pip install --quiet -r requirements.txt

echo "→ migrations"
venv/bin/python manage.py migrate --noinput

echo "→ fichiers statiques"
venv/bin/python manage.py collectstatic --noinput

echo "→ redémarrage gunicorn"
sudo systemctl restart cbbretagne

echo "✅ Déploiement terminé"
