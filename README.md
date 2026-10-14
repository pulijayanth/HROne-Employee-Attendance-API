# Employee Attendance API

A FastAPI and MongoDB implementation of an employee attendance API, including employee management, attendance operations, manual corrections, analytics, and MongoDB query-plan inspection.

## Requirements

- Python 3.12+
- MongoDB 6.0+
- Git

## Setup (Windows PowerShell)

Run these commands from the repository root.

**1. Create and activate the virtual environment**

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

**2. Install dependencies**

```powershell
python -m pip install -r requirements.txt
```

**3. Configure environment variables**

```powershell
Copy-Item .env.example .env
```

Update `.env` if your MongoDB connection settings differ from the defaults:

```text
MONGO_URI=mongodb://localhost:27017
MONGO_DB=attendance_db
```

**4. Start MongoDB**

Ensure your local MongoDB service is running.

**5. Start the API**

```powershell
python -m uvicorn app.main:app --port 8000
```

Open the interactive API documentation at:

http://127.0.0.1:8000/docs

## Tests

Run the test suite from the repository root:

```powershell
python -m pytest -q
```

The current helper-test suite contains 14 passing tests. These cover attendance calculations, including late minutes, work hours, and overtime. They do not constitute full integration coverage of every API endpoint.

## Repository Structure

- `app/main.py` — API implementation.
- `openapi.yaml` — API contract.
- `DATA_MODEL.md` — MongoDB data model.
- `REVIEW.md` — Review of starter-code defects.
- `DECISIONS.md` — Implementation decisions.

## Security and Submission Notes

- Do not commit `.env`, credentials, or other secrets.
- Do not commit the original problem statement.
- Use `.env.example` as the template for local configuration.
