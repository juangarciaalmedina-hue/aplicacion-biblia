@echo off
setlocal

set "PROJECT_DIR=%~dp0"
set "GRADLE_DIR=%PROJECT_DIR%build\biblia_app\android\gradle"
set "GRADLEW=%GRADLE_DIR%\gradlew.bat"
set "APK_PATH=%GRADLE_DIR%\app\build\outputs\apk\debug\app-debug.apk"
set "SRC_PKG=%PROJECT_DIR%src\biblia_app"
set "ANDROID_PKG=%GRADLE_DIR%\app\src\main\python\biblia_app"
set "JAVA_HOME=C:\Program Files\Microsoft\jdk-17.0.10.7-hotspot"

echo.
echo === Generar APK Debug ===
echo.

if not exist "%GRADLEW%" (
    echo No se encontro gradlew.bat:
    echo %GRADLEW%
    echo.
    echo Primero genera o prepara el proyecto Android con Briefcase.
    pause
    exit /b 1
)

if not exist "%JAVA_HOME%\bin\java.exe" (
    echo No se encontro Java en:
    echo %JAVA_HOME%
    echo.
    echo Corrige la ruta de JAVA_HOME dentro del archivo BAT.
    pause
    exit /b 1
)

if not exist "%SRC_PKG%" (
    echo No se encontro el paquete fuente:
    echo %SRC_PKG%
    pause
    exit /b 1
)

if not exist "%ANDROID_PKG%" (
    echo No se encontro la carpeta Python de Android:
    echo %ANDROID_PKG%
    echo.
    echo Primero genera o prepara el proyecto Android con Briefcase.
    pause
    exit /b 1
)

echo Sincronizando codigo Python al proyecto Android...
del /f /q "%ANDROID_PKG%\*.py" >nul 2>&1
if exist "%ANDROID_PKG%\__pycache__" rmdir /s /q "%ANDROID_PKG%\__pycache__"
robocopy "%SRC_PKG%" "%ANDROID_PKG%" *.py /NJH /NJS /NDL /NFL >nul

cd /d "%GRADLE_DIR%"
if exist "%APK_PATH%" del /f /q "%APK_PATH%"

call "%GRADLEW%" clean assembleDebug
if errorlevel 1 (
    echo.
    echo Fallo la generacion del APK debug.
    pause
    exit /b 1
)

echo.
echo APK debug generado correctamente:
echo %APK_PATH%
echo.
pause
