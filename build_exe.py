import os
import sys
import subprocess
import shutil

def build():
    print("==================================================")
    print("   GEST-STOCK POS - COMPILATION DU FICHIER .EXE   ")
    print("==================================================")

    base_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(base_dir)

    # 1. Vérifier les dépendances
    print("[1/3] Vérification des modules Python...")
    try:
        import flask, webview, PIL, PyInstaller
        print("  -> Tous les modules nécessaires sont installés.")
    except ImportError as e:
        print(f"  [ERREUR] Module manquant : {e}")
        print("  Veuillez exécuter : pip install -r requirements.txt")
        sys.exit(1)

    # 2. Nettoyer les anciens builds
    print("[2/3] Nettoyage des répertoires de compilation...")
    for folder in ['build', 'dist']:
        if os.path.exists(folder):
            shutil.rmtree(folder)
            print(f"  -> Dossier '{folder}' nettoyé.")

    # 3. Lancer PyInstaller
    print("[3/3] Génération de l'exécutable avec PyInstaller...")
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--clean",
        "--noconfirm",
        "StockPOS.spec"
    ]
    
    res = subprocess.run(cmd)
    if res.returncode == 0:
        print("\n" + "=" * 50)
        print("   SUCCÈS ! EXÉCUTABLE CRÉÉ AVEC SUCCÈS")
        print("=" * 50)
        dist_path = os.path.join(base_dir, 'dist')
        print(f"L'application se trouve dans le dossier : {dist_path}")
        for f in os.listdir(dist_path):
            print(f" -> {f}")
        print("\nPour l'utiliser, il suffit de double-cliquer dessus !")
    else:
        print("\n[ERREUR] La compilation a échoué.")
        sys.exit(res.returncode)

if __name__ == '__main__':
    build()
