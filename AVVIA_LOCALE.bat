@echo off
rem Compatibility with the original launchers: uses vanishcam.bat.
call "%~dp0vanishcam.bat" %*
exit /b %errorlevel%
