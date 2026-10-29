# Instalador de VanishCam para Windows 10/11.
#   powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/Agupane/vanish_webcam/main/install.ps1 | iex"
# o, desde una copia del repo: clic derecho en install.ps1 -> "Ejecutar con PowerShell".
# Solo ASCII a proposito: Windows PowerShell 5.1 lee los .ps1 sin BOM como ANSI.
$ErrorActionPreference = "Stop"
$Repo = "Agupane/vanish_webcam"

function Say($Message) { Write-Host "`n[VanishCam] $Message" -ForegroundColor Cyan }
function Check($What) { if ($LASTEXITCODE -ne 0) { throw "Fallo: $What" } }

# Ejecutado con irm | iex: bajar el repo y seguir desde ahi.
$AppDir = $null
if ($PSScriptRoot -and (Test-Path (Join-Path $PSScriptRoot "vanish_cam.py"))) {
    $AppDir = $PSScriptRoot
} else {
    $AppDir = Join-Path $HOME "VanishCam"
    Say "Descargando VanishCam en $AppDir..."
    $zip = Join-Path $env:TEMP "vanishcam.zip"
    $unpacked = Join-Path $env:TEMP "vanishcam-src"
    Invoke-WebRequest "https://github.com/$Repo/archive/refs/heads/main.zip" -OutFile $zip -UseBasicParsing
    if (Test-Path $unpacked) { Remove-Item $unpacked -Recurse -Force }
    Expand-Archive $zip $unpacked
    New-Item -ItemType Directory -Force $AppDir | Out-Null
    # Copia encima de una instalacion anterior sin borrar .venv ni models\.
    Copy-Item (Join-Path $unpacked "vanish_webcam-main\*") $AppDir -Recurse -Force
    Remove-Item $zip, $unpacked -Recurse -Force
}
Set-Location $AppDir

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Say "Instalando uv (instala Python sin pedir permisos de administrador)..."
    powershell -ExecutionPolicy Bypass -NoProfile -Command "irm https://astral.sh/uv/install.ps1 | iex"
    Check "instalar uv"
    $env:Path = "$HOME\.local\bin;$env:Path"
}

Say "Preparando Python y las dependencias..."
$Python = Join-Path $AppDir ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { uv venv --python 3.12 .venv; Check "crear el entorno de Python" }
uv pip install --python $Python -r requirements.txt
Check "instalar las dependencias"

Say "Descargando modelos de MediaPipe..."
& $Python -c "import sys; sys.path.insert(0, sys.argv[1]); import vanish_cam; vanish_cam.download_models('normal')" $AppDir
Check "descargar los modelos"

$Obs = Join-Path $env:ProgramFiles "obs-studio\bin\64bit\obs64.exe"
if (-not (Test-Path $Obs)) {
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Say "Instalando OBS Studio (trae la camara virtual)..."
        winget install --id OBSProject.OBSStudio -e --accept-source-agreements --accept-package-agreements
        Check "instalar OBS Studio"
    } else {
        Write-Warning "Falta OBS Studio, que trae la camara virtual. Bajalo de https://obsproject.com/download e instalalo."
    }
}

Say "Creando el acceso VanishCam en el Escritorio..."
$Shell = New-Object -ComObject WScript.Shell
$Link = $Shell.CreateShortcut((Join-Path ([Environment]::GetFolderPath("Desktop")) "VanishCam.lnk"))
$Link.TargetPath = Join-Path $AppDir "vanishcam.bat"
$Link.WorkingDirectory = $AppDir
$Link.IconLocation = Join-Path $AppDir "assets\vanish_icon.ico"
$Link.Save()

Say "Listo. Abri VanishCam desde el Escritorio. En Zoom o Meet elegi la camara 'OBS Virtual Camera'."
Say "Si OBS esta abierto, no actives su camara virtual: la usa VanishCam."
