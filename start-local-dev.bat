@echo off
setlocal

set "ROOT=%~dp0"
cd /d "%ROOT%"

echo Starting Conduut n8n container...
docker compose up -d n8n
if errorlevel 1 (
  echo Failed to start n8n with Docker Compose.
  exit /b 1
)

echo Waiting for n8n healthcheck...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$deadline=(Get-Date).AddMinutes(2); do { $status=(docker inspect -f '{{.State.Health.Status}}' conduut-n8n 2>$null); if ($status -eq 'healthy') { exit 0 }; Start-Sleep -Seconds 2 } while ((Get-Date) -lt $deadline); Write-Host 'n8n did not become healthy within 2 minutes.'; exit 1"
if errorlevel 1 (
  echo n8n is not healthy. Check logs with: docker logs --tail 100 conduut-n8n
  exit /b 1
)

echo Starting agent dev server on http://localhost:8100 ...
if not exist "%ROOT%logs\agent" mkdir "%ROOT%logs\agent"
if "%CONDUUT_WEB_PORT%"=="" set "CONDUUT_WEB_PORT=3007"
set "CONDUUT_ENVIRONMENT=development"
set "CONDUUT_LOG_DIR=%ROOT%logs\agent"
set "CONDUUT_N8N_URL=http://localhost:5980"
set "CONDUUT_N8N_API_KEY=***REMOVED***"
set "CONDUUT_PUBLIC_WEB_URL=http://localhost:%CONDUUT_WEB_PORT%"
if exist "%ROOT%.env" (
  for /f "usebackq eol=# tokens=1,* delims==" %%A in ("%ROOT%.env") do (
    if /I "%%A"=="CONDUUT_GOOGLE_OAUTH_CLIENT_ID" set "CONDUUT_GOOGLE_OAUTH_CLIENT_ID=%%B"
    if /I "%%A"=="CONDUUT_GOOGLE_OAUTH_CLIENT_SECRET" set "CONDUUT_GOOGLE_OAUTH_CLIENT_SECRET=%%B"
    if /I "%%A"=="CONDUUT_CONNECTION_ENCRYPTION_KEY" set "CONDUUT_CONNECTION_ENCRYPTION_KEY=%%B"
    if /I "%%A"=="CONDUUT_OAUTH_STATE_TTL_SECONDS" set "CONDUUT_OAUTH_STATE_TTL_SECONDS=%%B"
  )
)
set "PYTHONPATH=%ROOT%packages\n8n-registry\src;%PYTHONPATH%"
start "Conduut Agent" /D "%ROOT%apps\agent" cmd /k python -m uvicorn src.main:app --reload --host 0.0.0.0 --port 8100

echo Starting web dev server on http://localhost:%CONDUUT_WEB_PORT% ...
set "AGENT_API_BASE_URL=http://localhost:8100"
start "Conduut Web" /D "%ROOT%apps\web" cmd /k npm run dev -- --hostname localhost --port %CONDUUT_WEB_PORT%

echo.
echo Started:
echo   n8n   http://localhost:5980
echo   agent http://localhost:8100
echo   web   http://localhost:%CONDUUT_WEB_PORT%
echo.
echo Close the Agent/Web terminal windows to stop local dev servers.
echo Stop n8n with: docker compose stop n8n

endlocal
