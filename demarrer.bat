@echo off
title Lancement de GEST-STOCK POS
echo ========================================================
echo             LANCEMENT DE GEST-STOCK POS
echo ========================================================
echo.

python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERREUR] Python n'est pas installe ou pas accessible dans le PATH.
    echo Rendez-vous sur python.org pour installer Python en cochant "Add Python to PATH".
    pause
    exit /b 1
)

echo Verification des modules necessaires...
python -m pip install -r requirements.txt >nul 2>&1

echo Demarrage de l'application de bureau...
python app.py

