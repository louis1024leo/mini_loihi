@echo off
if exist "C:\tool\oss-cad-suite\bin\yosys-smtbmc.exe.exe" (
  "C:\tool\oss-cad-suite\bin\yosys-smtbmc.exe.exe" %*
  exit /b %errorlevel%
)
python "C:\tool\oss-cad-suite\bin\yosys-smtbmc.exe-script.py" %*
