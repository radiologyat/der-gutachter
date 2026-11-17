@echo off
rem Gutachten Assistant - start (Windows). Serves UI + API on http://127.0.0.1:8077
cd /d "%~dp0\.."
start "" "http://127.0.0.1:8077"
uv run python -m gutachten.api.app
