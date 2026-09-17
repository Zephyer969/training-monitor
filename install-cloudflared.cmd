@echo off
setlocal

where cloudflared >nul 2>&1
if not errorlevel 1 (
  echo cloudflared is already available in PATH.
  cloudflared --version
  pause
  exit /b 0
)

where winget >nul 2>&1
if errorlevel 1 (
  echo winget was not found.
  echo Install cloudflared from the official Cloudflare Windows instructions:
  echo https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/
  pause
  exit /b 1
)

echo Installing the official Cloudflare cloudflared package...
winget install --id Cloudflare.cloudflared --exact --source winget ^
  --accept-source-agreements --accept-package-agreements
if errorlevel 1 (
  echo Installation failed.  You can install cloudflared manually from the official page above.
  pause
  exit /b 1
)

echo Installation finished.  Close and reopen the monitor launcher once so PATH refreshes.
pause
