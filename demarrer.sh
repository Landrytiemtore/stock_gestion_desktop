#!/usr/bin/env bash
echo "========================================================"
echo "             LANCEMENT DE GEST-STOCK POS"
echo "========================================================"
echo ""

cd "$(dirname "$0")"

# Vérification dépendances
python3 -m pip install -r requirements.txt > /dev/null 2>&1

echo "Démarrage de l'application..."
python3 app.py

