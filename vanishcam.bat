@echo off
rem Arranca VanishCam mandando el video a la camara virtual de OBS.
rem Acepta las mismas opciones que vanish_cam.py, por ejemplo --mode naruto.
setlocal
set "APP=%~dp0"
if not exist "%APP%.venv\Scripts\python.exe" (
  echo [VanishCam] Falta instalar: corre install.ps1 ^(ver README^).
  pause
  exit /b 1
)
"%APP%.venv\Scripts\python.exe" "%APP%vanish_cam.py" --virtual-camera %*
if errorlevel 1 pause
exit /b %errorlevel%
