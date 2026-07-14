# CX Harness

Scaffold for the CX Harness application.

## Backend development

From the repository root:

```bash
python3 -m venv backend/.venv
source backend/.venv/bin/activate
python -m pip install -r backend/requirements.txt
cp .env.example .env
cd backend
uvicorn app.main:app --reload
```

The local `.env` file and virtual environment are intentionally ignored by Git.
