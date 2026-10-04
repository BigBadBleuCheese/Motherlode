@echo off
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\motherlode.ps1" %*
set "CODE=%ERRORLEVEL%"
echo %cmdcmdline% | find /i "%~nx0" >nul && pause
exit /b %CODE%
