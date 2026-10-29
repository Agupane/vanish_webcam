@echo off
rem Compatibilidad con los lanzadores originales: usa vanishcam.bat.
call "%~dp0vanishcam.bat" %*
exit /b %errorlevel%
