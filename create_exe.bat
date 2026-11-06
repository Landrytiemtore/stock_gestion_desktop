@echo off
title Compilation GestStock POS
echo ========================================================
echo       COMPILATION AUTOMATIQUE GEST-STOCK POS (.EXE)
echo ========================================================
echo.

echo Verification de Python...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERREUR] Python n'est pas installe ou pas dans le PATH de Windows.
    echo Installez Python 3.10+ depuis python.org en cochant "Add Python to PATH".
    pause
    exit /b 1
)

echo Installation / Mise a jour des dependances...
python -m pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo [ERREUR] Impossible d'installer les dependances.
    pause
    exit /b 1
)

echo.
echo Lancement de la compilation...
python build_exe.py

echo.
echo ========================================================
echo Votre fichier GestStockPOS.exe est pret dans le dossier 'dist' !
echo ========================================================
pause
