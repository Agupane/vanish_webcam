# VanishCam installer for Windows 10/11.
#   powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/Agupane/vanish_webcam/main/install.ps1 | iex"
# or, from a copy of the repo: right-click install.ps1 -> "Run with PowerShell".
# ASCII only on purpose: Windows PowerShell 5.1 reads BOM-less .ps1 files as ANSI.
$ErrorActionPreference = "Stop"
$Repo = "Agupane/vanish_webcam"

function Say($Message) { Write-Host "`n[VanishCam] $Message" -ForegroundColor Cyan }
function Check($What) { if ($LASTEXITCODE -ne 0) { throw "Failed: $What" } }

# Run via irm | iex: download the repo and continue from there.
$AppDir = $null
if ($PSScriptRoot -and (Test-Path (Join-Path $PSScriptRoot "vanish_cam.py"))) {
    $AppDir = $PSScriptRoot
} else {
    $AppDir = Join-Path $HOME "VanishCam"
    Say "Downloading VanishCam to $AppDir..."
    $zip = Join-Path $env:TEMP "vanishcam.zip"
    $unpacked = Join-Path $env:TEMP "vanishcam-src"
    Invoke-WebRequest "https://github.com/$Repo/archive/refs/heads/main.zip" -OutFile $zip -UseBasicParsing
    if (Test-Path $unpacked) { Remove-Item $unpacked -Recurse -Force }
    Expand-Archive $zip $unpacked
    New-Item -ItemType Directory -Force $AppDir | Out-Null
    # Copies over a previous install without deleting .venv or models\.
    Copy-Item (Join-Path $unpacked "vanish_webcam-main\*") $AppDir -Recurse -Force
    Remove-Item $zip, $unpacked -Recurse -Force
}
Set-Location $AppDir

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Say "Installing uv (installs Python without asking for administrator rights)..."
    powershell -ExecutionPolicy Bypass -NoProfile -Command "irm https://astral.sh/uv/install.ps1 | iex"
    Check "install uv"
    $env:Path = "$HOME\.local\bin;$env:Path"
}

Say "Setting up Python and the dependencies..."
$Python = Join-Path $AppDir ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { uv venv --python 3.12 .venv; Check "create the Python environment" }
uv pip install --python $Python -r requirements.txt
Check "install the dependencies"

Say "Downloading MediaPipe models..."
& $Python -c "import sys; sys.path.insert(0, sys.argv[1]); import vanish_cam; vanish_cam.download_models('normal')" $AppDir
Check "download the models"

$Obs = Join-Path $env:ProgramFiles "obs-studio\bin\64bit\obs64.exe"
if (-not (Test-Path $Obs)) {
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Say "Installing OBS Studio (it includes the virtual camera)..."
        winget install --id OBSProject.OBSStudio -e --accept-source-agreements --accept-package-agreements
        Check "install OBS Studio"
    } else {
        Write-Warning "OBS Studio, which includes the virtual camera, is missing. Download it from https://obsproject.com/download and install it."
    }
}

Say "Creating the VanishCam shortcut on the Desktop..."
$Shell = New-Object -ComObject WScript.Shell
$Link = $Shell.CreateShortcut((Join-Path ([Environment]::GetFolderPath("Desktop")) "VanishCam.lnk"))
$Link.TargetPath = Join-Path $AppDir "vanishcam.bat"
$Link.WorkingDirectory = $AppDir
$Link.IconLocation = Join-Path $AppDir "assets\vanish_icon.ico"
$Link.Save()

Say "Done. Open VanishCam from the Desktop. In Zoom or Meet pick the 'OBS Virtual Camera' camera."
Say "If OBS is open, don't start its virtual camera: VanishCam uses it."
