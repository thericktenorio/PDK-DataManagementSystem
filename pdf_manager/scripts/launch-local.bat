@echo off
set local enabledelayedexpansion

REM Go to repo root
cd /d %~dp0\..

REM Start/refresh containers
docker compose up -d --build

REM Wait for web to answer HTTP (up to ~60s)
set URL=http://localhost:8000/
for /l %%i in (1,1,60) do (
    powershell -Command ^
        "$r = try { (Invoke-WebRequest -Uri '%URL%' -UseBasicParsing -TimeoutSec 2).StatusCode } catch { 0 }; ^
         if ($r -eq 200 -or $r -eq 302) { exit 0 } else { Start-Sleep -Seconds 1; exit 1 }"
    if !errorlevel! == 0 goto :ready
)
echo Timed out waiting for %URL%. Check logs with: docker compose logs -f web
:ready

start "" %URL%
echo App starting at %URL%
endlocal
