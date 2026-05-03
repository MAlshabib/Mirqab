@echo off
cd /d "%~dp0"

start "Mirqab Backend" cmd /k "cd /d "%~dp0back-end" && .venv\Scripts\activate && pip install -r requirements.txt && python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000"

start "Mirqab Frontend" cmd /k "cd /d "%~dp0front-end" && npm run dev"
