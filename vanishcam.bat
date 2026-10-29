@echo off
rem Starts VanishCam sending the video to the OBS virtual camera.
rem Accepts the same options as vanish_cam.py, for example --mode naruto.
setlocal
set "APP=%~dp0"
if not exist "%APP%.venv\Scripts\python.exe" (
  echo [VanishCam] Not installed yet: run install.ps1 ^(see README^).
  pause
  exit /b 1
)
rem Without options it opens the home window (effect, camera, Super Saiyan hair).
set "HOME_WINDOW="
if "%~1"=="" set "HOME_WINDOW=--home"
"%APP%.venv\Scripts\python.exe" "%APP%vanish_cam.py" --virtual-camera %HOME_WINDOW% %*
if errorlevel 1 pause
exit /b %errorlevel%
