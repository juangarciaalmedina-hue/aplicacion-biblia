@echo off
setlocal

chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

set "PROJECT_DIR=%~dp0"
set "JAVA_HOME=C:\Program Files\Microsoft\jdk-17.0.10.7-hotspot"

echo.
echo === Generar APK con Flet oficial ===
echo.

if not exist "%JAVA_HOME%\bin\java.exe" (
    echo No se encontro Java en:
    echo %JAVA_HOME%
    pause
    exit /b 1
)

cd /d "%PROJECT_DIR%"

python validar_openrouter.py
if errorlevel 1 (
    echo.
    echo La configuracion de IA no es valida. Corrige OPENROUTER_PROXY_URL o OPENROUTER_API_KEY antes de generar el APK.
    pause
    exit /b 1
)

python -m pip install -U flet
if errorlevel 1 (
    echo.
    echo Fallo al actualizar Flet.
    pause
    exit /b 1
)

flet build apk . --clear-cache --product "Biblia IA" --org com.jmgalmedina --bundle-id com.jmgalmedina.biblia_app
if errorlevel 1 (
    echo.
    echo Fallo la generacion del APK con Flet.
    pause
    exit /b 1
)

echo.
echo APK generado. Revisa la carpeta build o dist creada por Flet.
echo.
pause
