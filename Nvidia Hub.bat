@echo off
cd /d "%~dp0"
if not exist "node_modules\electron" (
  echo Installing dependencies...
  call npm install
)
start "" cmd /c "npx electron ."
