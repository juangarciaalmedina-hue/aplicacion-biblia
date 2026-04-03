@echo off
setlocal

chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

set "PROJECT_DIR=%~dp0"

echo.
echo === Generar APK ligera ARM64 ===
echo.

cd /d "%PROJECT_DIR%"

python validar_openrouter.py
if errorlevel 1 (
    echo.
    echo La configuracion de IA no es valida. Corrige OPENROUTER_PROXY_URL o OPENROUTER_API_KEY antes de generar el APK.
    pause
    exit /b 1
)

flet build apk . ^
  --no-rich-output ^
  --clear-cache ^
  --product "Biblia IA" ^
  --org com.jmgalmedina ^
  --bundle-id com.jmgalmedina.biblia_app ^
  --arch arm64 ^
  --split-per-abi ^
  --compile-app ^
  --compile-packages ^
  --cleanup-app ^
  --cleanup-packages ^
  --exclude dist build .gradle .gradle-user-home .gradle-user-home-apk "*.jks" "*.bat" "roots.sst"
if errorlevel 1 (
    echo.
    echo Fallo la generacion de la APK ligera.
    pause
    exit /b 1
)

echo.
echo APK ligera generada. Revisa la carpeta build\apk
echo.
pause
