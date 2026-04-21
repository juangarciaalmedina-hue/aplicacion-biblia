$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$flutterSdk = "C:\Users\danie\flutter\3.41.4\bin\flutter.bat"
$javaHome = "C:\Users\danie\java\17.0.13+11"
$buildFlutterDir = Join-Path $projectRoot "build\flutter"
$sitePackagesDir = Join-Path $projectRoot "build\site-packages"
$sourceApk = Join-Path $buildFlutterDir "build\app\outputs\flutter-apk\app-arm64-v8a-release.apk"
$targetApk = Join-Path $projectRoot "build\apk\biblia_app-arm64-v8a-lite.apk"
$symbolsDir = Join-Path $projectRoot "build\android-debug-symbols"

if (-not (Test-Path $flutterSdk)) {
    throw "No encuentro Flutter en: $flutterSdk"
}

if (-not (Test-Path $javaHome)) {
    throw "No encuentro Java en: $javaHome"
}

if (-not (Test-Path $buildFlutterDir)) {
    throw "Falta la carpeta build\flutter. Crea antes el scaffold Android del proyecto."
}

if (-not (Test-Path $sitePackagesDir)) {
    throw "Falta la carpeta build\site-packages. Hace falta para serious_python_android."
}

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $targetApk) | Out-Null
New-Item -ItemType Directory -Force -Path $symbolsDir | Out-Null

$env:SERIOUS_PYTHON_SITE_PACKAGES = $sitePackagesDir
$env:JAVA_HOME = $javaHome
$env:PATH = "C:\Users\danie\flutter\3.41.4\bin;$javaHome\bin;$env:PATH"

Push-Location $buildFlutterDir
try {
    & $flutterSdk build apk `
        --release `
        --target-platform android-arm64 `
        --split-per-abi `
        --tree-shake-icons `
        --split-debug-info=../android-debug-symbols
}
finally {
    Pop-Location
}

if (-not (Test-Path $sourceApk)) {
    throw "Flutter no genero el APK esperado en: $sourceApk"
}

Copy-Item -LiteralPath $sourceApk -Destination $targetApk -Force

$apk = Get-Item $targetApk
$sizeMb = [math]::Round($apk.Length / 1MB, 2)

Write-Host "APK ligera creada en: $targetApk"
Write-Host "Tamano: $sizeMb MB"
