@echo off
setlocal

set "PROJECT_DIR=%~dp0"
set "FLET_EXE=C:\Users\ester\AppData\Local\Programs\Python\Python311\Scripts\flet.exe"

echo.
echo === Generar APK ligera ARM64 ===
echo.

if not exist "%FLET_EXE%" (
    echo No se encontro la CLI de Flet en:
    echo %FLET_EXE%
    pause
    exit /b 1
)

cd /d "%PROJECT_DIR%"

"%FLET_EXE%" build apk . ^
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
