@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ============================================
echo   FishingBot - build do executavel (.exe)
echo ============================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo [ERRO] Python nao foi encontrado no PATH.
    echo.
    echo Instale o Python 3.11 ou mais novo em https://www.python.org/downloads/
    echo IMPORTANTE: marque a opcao "Add python.exe to PATH" durante a instalacao.
    echo Depois rode este build.bat de novo.
    pause
    exit /b 1
)

echo [1/5] Python encontrado:
python --version
echo.

if not exist venv (
    echo [2/5] Criando ambiente virtual em venv...
    python -m venv venv
) else (
    echo [2/5] Ambiente virtual ja existe, reaproveitando.
)
echo.

echo [3/5] Instalando dependencias (isso pode demorar alguns minutos na primeira vez)...
call venv\Scripts\python.exe -m pip install --upgrade pip >nul
call venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 (
    echo [ERRO] Falha instalando dependencias. Veja o log acima.
    pause
    exit /b 1
)
echo.

echo [4/5] Gerando o executavel com PyInstaller...
call venv\Scripts\python.exe -m PyInstaller --onefile --windowed --name FishingBot ^
    --hidden-import win32timezone ^
    --noconfirm ^
    main.py
if errorlevel 1 (
    echo [ERRO] Falha ao gerar o executavel. Veja o log acima.
    pause
    exit /b 1
)
echo.

echo [5/5] Copiando FishingBot.exe para a pasta do projeto...
copy /y dist\FishingBot.exe FishingBot.exe >nul

echo.
echo ============================================
echo   BUILD CONCLUIDO COM SUCESSO
echo   Executavel: %cd%\FishingBot.exe
echo ============================================
pause
