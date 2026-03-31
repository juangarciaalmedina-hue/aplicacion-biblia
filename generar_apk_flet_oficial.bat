@echo off
setlocal

set "PROJECT_DIR=%~dp0"
set "JAVA_HOME=C:\Program Files\Microsoft\jdk-17.0.10.7-hotspot"
set "FLET_EXE=C:\Users\ester\AppData\Local\Programs\Python\Python311\Scripts\flet.exe"

echo.
echo === Generar APK con Flet oficial ===
echo.

if not exist "%JAVA_HOME%\bin\java.exe" (
    echo No se encontro Java en:
    echo %JAVA_HOME%
    pause
    exit /b 1
)

if not exist "%FLET_EXE%" (
    echo No se encontro la CLI de Flet en:
    echo %FLET_EXE%
    pause
    exit /b 1
)

cd /d "%PROJECT_DIR%"

python -m pip install -U flet
if errorlevel 1 (
    echo.
    echo Fallo al actualizar Flet.
    pause
    exit /b 1
)

"%FLET_EXE%" build apk . --clear-cache --product "Biblia IA" --org com.jmgalmedina --bundle-id com.jmgalmedina.biblia_app
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
