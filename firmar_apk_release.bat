@echo off
setlocal

set "PROJECT_DIR=%~dp0"
set "KEYSTORE=%PROJECT_DIR%biblia-app-release.jks"
set "ALIAS=bibliaapp"
set "UNSIGNED_APK=%PROJECT_DIR%build\biblia_app\android\gradle\app\build\outputs\apk\release\app-release-unsigned.apk"
set "ALIGNED_APK=%PROJECT_DIR%build\biblia_app\android\gradle\app\build\outputs\apk\release\app-release-aligned.apk"
set "BUILD_TOOLS=%LOCALAPPDATA%\Android\Sdk\build-tools\36.1.0"
set "ZIPALIGN=%BUILD_TOOLS%\zipalign.exe"
set "APKSIGNER=%BUILD_TOOLS%\apksigner.bat"
set "KEYTOOL=C:\Program Files\Microsoft\jdk-17.0.10.7-hotspot\bin\keytool.exe"

echo.
echo === Firmador APK Biblia App ===
echo.

if not exist "%UNSIGNED_APK%" (
    echo No se encontro el APK release sin firmar:
    echo %UNSIGNED_APK%
    echo.
    echo Primero genera el build Android release.
    pause
    exit /b 1
)

if not exist "%ZIPALIGN%" (
    echo No se encontro zipalign:
    echo %ZIPALIGN%
    echo.
    echo Revisa la instalacion del Android SDK Build-Tools.
    pause
    exit /b 1
)

if not exist "%APKSIGNER%" (
    echo No se encontro apksigner:
    echo %APKSIGNER%
    echo.
    echo Revisa la instalacion del Android SDK Build-Tools.
    pause
    exit /b 1
)

if not exist "%KEYTOOL%" (
    echo No se encontro keytool:
    echo %KEYTOOL%
    echo.
    echo Revisa la instalacion del JDK.
    pause
    exit /b 1
)

if not exist "%KEYSTORE%" (
    echo No existe el keystore. Vamos a crearlo ahora.
    echo.
    "%KEYTOOL%" -genkeypair -v -keystore "%KEYSTORE%" -alias %ALIAS% -keyalg RSA -keysize 2048 -validity 10000
    if errorlevel 1 (
        echo.
        echo No se pudo crear el keystore.
        pause
        exit /b 1
    )
)

echo.
echo Alineando APK...
"%ZIPALIGN%" -p -f 4 "%UNSIGNED_APK%" "%ALIGNED_APK%"
if errorlevel 1 (
    echo.
    echo Fallo al alinear el APK.
    pause
    exit /b 1
)

echo.
echo Firmando APK...
"%APKSIGNER%" sign --ks "%KEYSTORE%" --ks-key-alias %ALIAS% "%ALIGNED_APK%"
if errorlevel 1 (
    echo.
    echo Fallo al firmar el APK.
    pause
    exit /b 1
)

echo.
echo Verificando firma...
"%APKSIGNER%" verify --verbose "%ALIGNED_APK%"
if errorlevel 1 (
    echo.
    echo La verificacion de firma fallo.
    pause
    exit /b 1
)

echo.
echo APK firmado correctamente:
echo %ALIGNED_APK%
echo.
pause
