# Employee Attendance API

FastAPI and MongoDB implementation of the employee attendance API, including attendance operations, corrections, analytics, and query-plan inspection.

## Requirements

- Python 3.12+
- MongoDB 6.0+
- Git

## Setup (Windows PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Configure `MONGO_URI` and `MONGO_DB` in `.env` if needed. The defaults are `mongodb://localhost:27017` and `attendance_db`.

Ensure MongoDB is running, then start the API:

```powershell
python -m uvicorn app.main:app --port 8000
```

Open `http://127.0.0.1:8000/docs` to explore the API.

## Tests

```powershell
python -m pytest -q
```

## Repository notes

- `app/main.py` contains the API implementation.
- `openapi.yaml` describes the API contract.
- `DATA_MODEL.md` documents the MongoDB data model.
- `REVIEW.md` records reviewed starter-code defects.
- `DECISIONS.md` documents implementation decisions.

Do not commit `.env`, credentials, or the original problem statement.
