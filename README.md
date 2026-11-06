# 🛍️ GEST-STOCK POS — Logiciel de Caisse & Gestion de Stock Desktop

Logiciel de bureau professionnel de gestion de stock et de point de vente (POS) inspiré de l'interface Odoo, spécialement conçu pour les commerçants et boutiques en Afrique de l'Ouest et zone Franc CFA.

---

## ✨ Fonctionnalités Incluses

1. **Catalogue Produits avec Calcul de Rentabilité Réelle & Détection Automatique de Rotation :**
   - Importation d'une photo pour chaque produit.
   - Saisie du prix d'achat, du prix de transport et du prix de vente.
   - Calcul en temps réel du **coût de revient réel** et de la **marge nette** (en FCFA et en %).
   - **Détection Automatique de la Rotation (Double Moteur basé sur les Ventes Réelles) :**
     * **Intensité / Débit rapide :** Dès qu'un article enregistre un pic de ventes ($\ge 5$ ventes/jour) ou $\ge 15$ unités sur les 7 derniers jours $\rightarrow$ classé automatiquement **🔥 Forte rotation (Best-seller)** sans attendre la fin du mois.
     * **Fréquence régulière :** Vendu $\ge 10$ jours distincts sur les 30 derniers jours $\rightarrow$ **🔥 Forte rotation**.
     * **Nouveaux articles :** Statut automatique **✨ Nouveau** en observation pendant ses 15 premiers jours.
     * **Articles dormants :** Détectés en **🐢 Faible rotation** si moins de 3 jours de vente et moins de 5 unités sur le mois.
     * **Ajustement automatique du seuil d'alerte :** 20% pour les fortes rotations pour prévenir la rupture, 10% pour les faibles rotations.
     * Possibilité de synchroniser tous les produits en 1 clic grâce au bouton *✨ Rotation Auto (Tous)*.

2. **Écran de Vente (POS / Caisse - Style Odoo) :**
   - Galerie visuelle avec photos des produits et badges d'état du stock (Vert / Orange / Rouge).
   - Clic sur l'article $\rightarrow$ ajout immédiat au panier avec contrôle des quantités disponibles.
   - Sélection ou création rapide du client (+ historique d'achats et statut fidélité).
   - Choix du mode de règlement : **Espèces (Liquide)** avec calcul de la monnaie à rendre ou **Mobile Money** (Wave, Orange Money, etc.).
   - Remise accordée et validation de la vente en un clic.

3. **Reçus et Factures Personnalisables :**
   - **Format 1 : Ticket de caisse thermique (80mm)** pour imprimante de caisse standard.
   - **Format 2 : Facture A4 avec papier à en-tête** (Logo d'entreprise, RCCM, NIF, Téléphone, Adresse, Conditions de vente, Cachet/Signature).
   - Impression directe via le bouton d'impression et **sauvegarde automatique** d'une copie dans le dossier `recus/`.

4. **Alertes de Stock Intelligentes :**
   - Alerte automatique à **20%** pour les produits à forte rotation.
   - Alerte automatique à **10%** pour les articles rares.
   - Bouton de **ravitaillement express (+ stock)** en 1 clic.

5. **Journal des Ventes & Annulation avec Motif Obligatoire :**
   - Historique complet de toutes les transactions.
   - Réimpression des reçus à tout moment.
   - Annulation sécurisée avec saisie obligatoire du motif (restitue immédiatement les articles dans le stock).

6. **Clôture de Caisse Journalière (Rapport Z) :**
   - Récapitulatif du total Espèces, total Mobile Money, Chiffre d'Affaires du jour et Bénéfice net réalisé.
   - Impression du ticket de clôture de caisse.

7. **Sauvegarde Locale Anti-Panne :**
   - Base de données SQLite locale autonome (fonctionne 100% hors-ligne, sans connexion internet).
   - Export d'une sauvegarde horodatée de la base de données en un clic.

---

## 🚀 Comment Lancer le Logiciel sur votre Machine

### Option A : Lancer directement en Python
```bash
# 1. Aller dans le dossier
cd stock_pos_desktop

# 2. Installer les dépendances
pip install -r requirements.txt

# 3. Lancer l'application de bureau
python app.py
```
*(Si vous voulez l'ouvrir directement dans un navigateur, utilisez : `python app.py --browser`)*

---

## 📦 Comment Générer le Fichier `.exe` (Pour Windows)

Pour créer le fichier exécutable autonome `GestStockPOS.exe` prêt à installer sur n'importe quel ordinateur Windows sans rien installer d'autre :

### Méthode 1 : Un seul double-clic (Recommandé)
Double-cliquez simplement sur le fichier **`create_exe.bat`**. Le script va :
1. Installer automatiquement les dépendances si nécessaire.
2. Compiler l'exécutable avec PyInstaller.
3. Déposer le fichier **`GestStockPOS.exe`** dans le dossier **`dist/`**.

### Méthode 2 : En ligne de commande
```bash
python build_exe.py
```
Le fichier autonome `.exe` sera généré dans le dossier `dist/` !
