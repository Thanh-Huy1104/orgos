@echo off
echo ============================================
echo Orgos Monitor — Quick Start
echo ============================================
echo.
echo Starting API server on :8420 ...
start "orgos-api" /min py -3.12 -m uvicorn orgos.api:app --host 0.0.0.0 --port 8420
echo Starting Streamlit on :8501 ...
start "orgos-monitor" /min py -3.12 -m streamlit run monitor/app.py --server.port 8501
echo.
echo Waiting for API to be ready (this can take 60-90 seconds)...
echo.

set /a count=0
:loop_api
set /a count+=1
timeout /t 5 /nobreak >nul
py -3.12 -c "import urllib.request; urllib.request.urlopen('http://localhost:8420/health', timeout=2)" 2>nul && goto api_ok
if %count% lss 20 echo ... %count%0s still waiting ... && goto loop_api
echo WARNING: API not responding after 100s — it may still be starting.
goto check_ui

:api_ok
echo API is ready!

:check_ui
echo.
echo Waiting for Streamlit to be ready...
set /a count=0
:loop_ui
set /a count+=1
timeout /t 5 /nobreak >nul
py -3.12 -c "import urllib.request; urllib.request.urlopen('http://localhost:8501', timeout=2)" 2>nul && goto ui_ok
if %count% lss 12 echo ... %count%0s still waiting ... && goto loop_ui
echo WARNING: Streamlit not responding after 60s.
goto end

:ui_ok
echo Streamlit is ready!

:end
echo.
echo ============================================
echo Dashboard: http://localhost:8501
echo API docs:  http://localhost:8420/docs
echo ============================================
echo.
echo Close the two "py" windows to stop both services.
pause
