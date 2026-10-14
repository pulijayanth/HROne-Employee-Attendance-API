"""
Employee Attendance & Analytics API - STARTER

Run:  uvicorn app.main:app --port 8000
Env:  MONGO_URI, MONGO_DB (a local .env is loaded for convenience)

This file was written quickly by a colleague who has left the company. The happy path
works, but nobody has reviewed it. Read PROBLEM_STATEMENT.docx for what is expected of you,
openapi.yaml for the contract and DATA_MODEL.md for what is stored in MongoDB.
"""
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from dotenv import load_dotenv
from pymongo.errors import DuplicateKeyError, PyMongoError
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, field_validator
from pymongo import MongoClient

load_dotenv()

client = MongoClient(os.getenv("MONGO_URI", "mongodb://localhost:27017"))
db = client[os.getenv("MONGO_DB", "attendance_db")]

IST = timezone(timedelta(hours=5, minutes=30))


def _epoch_ms(value: Optional[datetime]) -> Optional[int]:
    if value is None:
        return None

    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)

    value = value.astimezone(timezone.utc).replace(microsecond=0)
    return int(value.timestamp() * 1000)


app = FastAPI(title="Employee Attendance & Analytics API", version="2.0.0")

@app.on_event("startup")
def create_indexes():
    db.employees.create_index(
        [("joined_on", 1)],
        name="ix_employees_joined_on",
    )

    db.employees.create_index(
        [("emp_code", 1)],
        unique=True,
        name="uq_employees_emp_code",
    )

    db.attendance_logs.create_index(
        [("emp_code", 1), ("date", 1)],
        unique=True,
        name="uq_attendance_emp_code_date",
    )

    db.attendance_logs.create_index(
        [("date", -1)],
        name="ix_attendance_date_desc",
    )

    db.attendance_logs.create_index(
        [("emp_code", 1), ("date", -1)],
        name="ix_attendance_emp_date_desc",
    )

    db.employees.create_index(
    [("department", 1), ("joined_on", 1)],
    name="ix_employees_department_joined",
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _as_ist(value: datetime) -> datetime:
    # MongoDB may return a naive datetime representing UTC.
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)

    return value.astimezone(IST)

def compute_late_minutes(
    punch_in: datetime,
    shift_start: str,
    shift_end: Optional[str] = None,
) -> int:
    punch_in = _as_ist(punch_in).replace(microsecond=0)

    start_hour, start_minute = map(int, shift_start.split(":"))

    shift_start_at = punch_in.replace(
        hour=start_hour,
        minute=start_minute,
        second=0,
        microsecond=0,
    )

    if (
        shift_end is not None
        and shift_end <= shift_start
    ):
        end_hour, end_minute = map(int, shift_end.split(":"))

        # A punch before the overnight shift's end belongs
        # to the shift that started on the previous day.
        if (
            punch_in.hour,
            punch_in.minute,
            punch_in.second,
        ) < (end_hour, end_minute, 0):
            shift_start_at -= timedelta(days=1)

    elapsed_seconds = (punch_in - shift_start_at).total_seconds()

    if elapsed_seconds <= 600:
        return 0

    return max(0, int(elapsed_seconds // 60))



def compute_work_hours(punch_in: datetime, punch_out: datetime) -> float:
        seconds = Decimal(
            str((punch_out - punch_in).total_seconds())
        )
        hours = seconds / Decimal("3600")

        rounded_hours = hours.quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )

        return float(rounded_hours)


def compute_overtime(
    punch_out: datetime,
    shift_end: str,
    date_str: str,
    shift_start: Optional[str] = None,
) -> int:
    punch_out = _as_ist(punch_out).replace(microsecond=0)
    end_hour, end_minute = map(int, shift_end.split(":"))

    end_date = datetime.fromisoformat(date_str).date()

    # date_str is the shift's start date. For overnight shifts,
    # the scheduled end falls on the following date.
    if shift_start is not None and shift_end <= shift_start:
        end_date += timedelta(days=1)

    shift_end_at = datetime(
        end_date.year,
        end_date.month,
        end_date.day,
        end_hour,
        end_minute,
        tzinfo=IST,
    )

    elapsed_seconds = (punch_out - shift_end_at).total_seconds()
    minutes = int(elapsed_seconds // 60)

    return minutes if minutes >= 30 else 0


# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #
class EmployeeIn(BaseModel):
    emp_code: str
    name: str
    email: str
    department: str
    shift_start: str = "09:30"
    shift_end: str = "18:30"
    joined_on: str


class PunchInIn(BaseModel):
    emp_code: str
    punched_at: Optional[int] = None
    status: str = "PRESENT"

    @field_validator("punched_at", mode="before")
    @classmethod
    def validate_punched_at(cls, value):
        if value is None:
            return value

        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(
                "punched_at must be an integer epoch timestamp in milliseconds"
            )

        if not 100_000_000_000 <= value <= 4_102_444_800_000:
            raise ValueError(
                "punched_at must be between 100000000000 and 4102444800000"
            )

        return value
class PunchOutIn(BaseModel):
    emp_code: str
    punched_at: Optional[int] = None

    @field_validator("punched_at", mode="before")
    @classmethod
    def validate_punched_at(cls, value):
        if value is None:
            return value

        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(
                "punched_at must be an integer epoch timestamp in milliseconds"
            )

        if not 100_000_000_000 <= value <= 4_102_444_800_000:
            raise ValueError(
                "punched_at must be between 100000000000 and 4102444800000"
            )

        return value

class AttendanceCorrectionIn(BaseModel):
    status: Optional[str] = None
    punch_in: Optional[int] = None
    punch_out: Optional[int] = None
    reason: str
    regularized_by: str


# --------------------------------------------------------------------------- #
# Endpoints provided
# --------------------------------------------------------------------------- #
@app.get("/health")
def health():
    try:
        client.admin.command("ping")
        return {"status": "ok"}
    except PyMongoError:
        raise HTTPException(
            status_code=503,
            detail="MongoDB is unavailable",
        )


@app.post("/employees", status_code=201)
def create_employee(body: EmployeeIn):
    if db.employees.find_one({"emp_code": body.emp_code}):
        raise HTTPException(409, "emp_code already exists")
    doc = body.model_dump()
    doc["created_at"] = datetime.now()
    db.employees.insert_one(doc)
    doc.pop("_id", None)
    return doc


@app.get("/employees")
def list_employees(department: Optional[str] = None, page: int = 1, page_size: int = 20):

    if page < 1:
        raise HTTPException(422, "page must be at least 1")

    if page_size < 1 or page_size > 100:
        raise HTTPException(422, "page_size must be between 1 and 100")

    q = {}
    if department:
        q["department"] = department
    skip = (page - 1) * page_size
    total = db.employees.count_documents(q)
    items = list(db.employees.find(q, {"_id": 0}).skip(skip).limit(page_size))
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@app.post("/attendance/punch-in", status_code=201)
def punch_in(body: PunchInIn):
    emp = db.employees.find_one({"emp_code": body.emp_code})

    if emp is None:
        raise HTTPException(
            status_code=404,
            detail="Employee not found",
        )

    if body.status not in {"PRESENT", "WFH", "ON_DUTY"}:
        raise HTTPException(
            status_code=422,
            detail="Invalid punch-in status",
        )

    if body.punched_at is None:
        ts = datetime.now(timezone.utc)
    else:
        ts = datetime.fromtimestamp(
            body.punched_at / 1000,
            tz=timezone.utc,
        )

    # Normalize to whole seconds and derive the date in IST.
    ts = ts.replace(microsecond=0)
    ts_ist = ts.astimezone(IST)
    date_str = ts_ist.date().isoformat()

    doc = {
        "emp_code": body.emp_code,
        "date": date_str,
        "status": body.status,
        "punch_in": ts,
        "punch_out": None,
        "work_hours": None,
        "late_minutes": compute_late_minutes(
            ts_ist,
            emp["shift_start"],
            emp["shift_end"],
        ),
        "overtime_minutes": 0,
        "half_day": False,
        "history": [],
    }

    try:
        result = db.attendance_logs.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(
            status_code=409,
            detail="Attendance already exists for this employee and date",
        )

    return {
    "emp_code": doc["emp_code"],
    "date": doc["date"],
    "status": doc["status"],
    "punch_in": _epoch_ms(doc["punch_in"]),
    "punch_out": _epoch_ms(doc["punch_out"]),
    "work_hours": doc["work_hours"],
    "late_minutes": doc["late_minutes"],
    "overtime_minutes": doc["overtime_minutes"],
    "half_day": doc["half_day"],
    "history": doc["history"],
}


@app.post("/attendance/punch-out")
def punch_out(body: PunchOutIn):
    emp = db.employees.find_one({"emp_code": body.emp_code})

    if emp is None:
        raise HTTPException(404, "Employee not found")

    if body.punched_at is None:
        ts = datetime.now(timezone.utc)
    else:
        ts = datetime.fromtimestamp(
            body.punched_at / 1000,
            tz=timezone.utc,
        )

    ts = ts.replace(microsecond=0)
    ts_ist = ts.astimezone(IST)
    date_str = ts_ist.date().isoformat()

    # Find today's record first; overnight shifts need the
    # attendance date on which the shift started.
    record = db.attendance_logs.find_one({
        "emp_code": body.emp_code,
        "punch_out": None,
        "punch_in": {"$ne": None},
    }, sort=[("punch_in", -1)])

    if record is None:
        raise HTTPException(404, "No open attendance record found")

    punch_in_at = record["punch_in"]
    if punch_in_at.tzinfo is None:
        punch_in_at = punch_in_at.replace(tzinfo=timezone.utc)

    if ts <= punch_in_at:
        raise HTTPException(422, "Punch-out must be after punch-in")

    work_hours = compute_work_hours(punch_in_at, ts)

    overtime_minutes = compute_overtime(
        ts_ist,
        emp["shift_end"],
        record["date"],
        emp["shift_start"],
    )

    half_day = work_hours < 4.50

    updated = db.attendance_logs.update_one(
        {
            "_id": record["_id"],
            "punch_out": None,
        },
        {
            "$set": {
                "punch_out": ts,
                "work_hours": work_hours,
                "overtime_minutes": overtime_minutes,
                "half_day": half_day,
            }
        },
    )

    if updated.modified_count != 1:
        raise HTTPException(409, "Attendance was already punched out")

    record.update({
        "punch_out": ts,
        "work_hours": work_hours,
        "overtime_minutes": overtime_minutes,
        "half_day": half_day,
    })

    return {
    "emp_code": record["emp_code"],
    "date": record["date"],
    "status": record["status"],
    "punch_in": _epoch_ms(record.get("punch_in")),
    "punch_out": _epoch_ms(record.get("punch_out")),
    "work_hours": record.get("work_hours"),
    "late_minutes": record.get("late_minutes", 0),
    "overtime_minutes": record.get("overtime_minutes", 0),
    "half_day": record.get("half_day", False),
    "history": record.get("history", []),
}


@app.patch("/attendance/{emp_code}/{date}")
def correct_attendance(
    emp_code: str,
    date: str,
    body: AttendanceCorrectionIn,
):
    record = db.attendance_logs.find_one({
        "emp_code": emp_code,
        "date": date,
    })

    if record is None:
        raise HTTPException(404, "Attendance record not found")

    changes = {}
    updates = {}

    if body.status is not None:
        if body.status not in {
            "PRESENT", "WFH", "ON_DUTY", "ABSENT", "LEAVE"
        }:
            raise HTTPException(422, "Invalid attendance status")

        if record.get("status") != body.status:
            changes["status"] = {
                "from": record.get("status"),
                "to": body.status,
            }
            updates["status"] = body.status

    for field, value in (
        ("punch_in", body.punch_in),
        ("punch_out", body.punch_out),
    ):
        if value is not None:
            if isinstance(value, bool) or not isinstance(value, int):
                raise HTTPException(
                    422,
                    f"{field} must be an integer epoch timestamp in milliseconds",
                )

            new_value = datetime.fromtimestamp(
                value / 1000,
                tz=timezone.utc,
            ).replace(microsecond=0)

            if record.get(field) != new_value:
                old_value = record.get(field)
                changes[field] = {
                    "from": int(old_value.timestamp() * 1000)
                    if old_value else None,
                    "to": value,
                }
                updates[field] = new_value

    if not changes:
        raise HTTPException(422, "No attendance changes supplied")

    if not body.reason.strip() or not body.regularized_by.strip():
        raise HTTPException(422, "Correction reason and by are required")

    updated_record = dict(record)
    updated_record.update(updates)

    punch_in_at = updated_record.get("punch_in")
    punch_out_at = updated_record.get("punch_out")
    status = updated_record.get("status")

    if not body.reason.strip() or not body.regularized_by.strip():
        raise HTTPException(422, "Correction reason and regularized_by are required")


    if status in {"ABSENT", "LEAVE"}:
        if body.punch_in is not None or body.punch_out is not None:
            raise HTTPException(
                422,
                "ABSENT and LEAVE cannot be supplied with punch times",
            )

        if punch_in_at is not None:
            changes["punch_in"] = {
                "from": _epoch_ms(punch_in_at),
                "to": None,
            }
            updates["punch_in"] = None
            punch_in_at = None

        if punch_out_at is not None:
            changes["punch_out"] = {
                "from": _epoch_ms(punch_out_at),
                "to": None,
            }
            updates["punch_out"] = None
            punch_out_at = None



    derived = {}
    employee = db.employees.find_one({"emp_code": emp_code})

    if employee is None:
        raise HTTPException(404, "Employee not found")

    if punch_in_at is not None:
        punch_in_ist = _as_ist(punch_in_at)

        if punch_in_ist.date().isoformat() != date:
            raise HTTPException(
                422,
                "punch_in must belong to the attendance date in IST",
            )

        derived["late_minutes"] = compute_late_minutes(
            punch_in_ist,
            employee["shift_start"],
            employee["shift_end"],
        )
    else:
        derived["late_minutes"] = 0

    if punch_in_at is not None and punch_out_at is not None:
        if punch_out_at <= punch_in_at:
            raise HTTPException(422, "punch_out must be after punch_in")

        if punch_out_at - punch_in_at > timedelta(hours=24):
            raise HTTPException(
                422,
                "Attendance duration cannot exceed 24 hours",
            )

        derived["work_hours"] = compute_work_hours(
            punch_in_at,
            punch_out_at,
        )
        derived["half_day"] = derived["work_hours"] < 4.50
        derived["overtime_minutes"] = compute_overtime(
            _as_ist(punch_out_at),
            employee["shift_end"],
            date,
            employee["shift_start"],
        )
    else:
        derived["work_hours"] = None
        derived["half_day"] = False
        derived["overtime_minutes"] = 0

    for field, new_value in derived.items():
        old_value = record.get(field)

        if old_value != new_value:
            changes[field] = {
                "from": old_value,
                "to": new_value,
            }

    updates.update(derived)


    history_entry = {
        "at": datetime.now(timezone.utc).replace(microsecond=0),
        "by": body.regularized_by.strip(),
        "reason": body.reason.strip(),
        "changes": changes,
    }

    for field_change in history_entry["changes"].values():
        for key in ("from", "to"):
            value = field_change.get(key)
            if isinstance(value, datetime):
                field_change[key] = _epoch_ms(value)

    result = db.attendance_logs.update_one(
        {"_id": record["_id"]},
        {
            "$set": updates,
            "$push": {"history": history_entry},
        },
    )

    if result.modified_count != 1:
        raise HTTPException(409, "Attendance record could not be updated")


    final_record = db.attendance_logs.find_one({"_id": record["_id"]})

    return {
        "emp_code": final_record["emp_code"],
        "date": final_record["date"],
        "status": final_record["status"],
        "punch_in": _epoch_ms(final_record.get("punch_in")),
        "punch_out": _epoch_ms(final_record.get("punch_out")),
        "work_hours": final_record.get("work_hours"),
        "late_minutes": final_record.get("late_minutes", 0),
        "overtime_minutes": final_record.get("overtime_minutes", 0),
        "half_day": final_record.get("half_day", False),
        "history": [
            {
                **entry,
                "at": _epoch_ms(entry.get("at")),
                "changes": {
                    field: {
                        key: (
                            _epoch_ms(value)
                            if isinstance(value, datetime)
                            else value
                        )
                        for key, value in change.items()
                    }
                    for field, change in entry.get("changes", {}).items()
                },
            }
            for entry in final_record.get("history", [])
        ],
    }



@app.get("/attendance")
def list_attendance(
    emp_code: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    status: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
):
    if page < 1:
        raise HTTPException(422, "page must be at least 1")

    if page_size < 1 or page_size > 100:
        raise HTTPException(422, "page_size must be between 1 and 100")


    if status is not None and status not in {
        "PRESENT", "WFH", "ON_DUTY", "ABSENT", "LEAVE"
    }:
        raise HTTPException(422, "Invalid attendance status")

    for field_name, value in (
        ("date_from", date_from),
        ("date_to", date_to),
    ):
        if value is not None:
            try:
                parsed_date = datetime.strptime(value, "%Y-%m-%d")
                if parsed_date.date().isoformat() != value:
                    raise ValueError
            except ValueError:
                raise HTTPException(
                    422,
                    f"{field_name} must use YYYY-MM-DD format",
                )

    if date_from and date_to and date_from > date_to:
        raise HTTPException(422, "date_from must be on or before date_to")




    q = {}
    if emp_code:
        q["emp_code"] = emp_code
    if date_from or date_to:
        q["date"] = {}
        if date_from:
            q["date"]["$gte"] = date_from
        if date_to:
            q["date"]["$lte"] = date_to
    if status:
        q["status"] = status

    total = db.attendance_logs.count_documents(q)
    skip = (page - 1) * page_size

    page_docs = list(
        db.attendance_logs.find(q, {"_id": 0})
        .sort([("date", -1), ("emp_code", 1)])
        .skip(skip)
        .limit(page_size)
    )

    for item in page_docs:
        item["punch_in"] = _epoch_ms(item.get("punch_in"))
        item["punch_out"] = _epoch_ms(item.get("punch_out"))
        item.setdefault("history", [])
        item.setdefault("half_day", False)

    return {
        "items": page_docs,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@app.get("/analytics/employees/{emp_code}/monthly")
def employee_monthly_analytics(
    emp_code: str,
    month: str,
):
    try:
        month_start = datetime.strptime(month, "%Y-%m").date()
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail="month must use YYYY-MM format",
        )

    employee = db.employees.find_one({"emp_code": emp_code})

    if employee is None:
        raise HTTPException(404, "Employee not found")

    year = month_start.year
    month_number = month_start.month

    if month_number == 12:
        next_month = datetime(year + 1, 1, 1).date()
    else:
        next_month = datetime(year, month_number + 1, 1).date()

    first_day = month_start.isoformat()
    last_day = (next_month - timedelta(days=1)).isoformat()

    pipeline = [
        {
            "$match": {
                "emp_code": emp_code,
                "date": {"$gte": first_day, "$lte": last_day},
            }
        },
        {
            "$group": {
                "_id": None,
                "total_records": {"$sum": 1},
                "present_days": {
                    "$sum": {
                        "$cond": [
                            {
                                "$in": [
                                    "$status",
                                    ["PRESENT", "WFH", "ON_DUTY"],
                                ]
                            },
                            {
                                "$cond": [
                                    "$half_day",
                                    0.5,
                                    1,
                                ]
                            },
                            0,
                        ]
                    }
                },
                "absent_days": {
                    "$sum": {
                        "$cond": [
                            {"$eq": ["$status", "ABSENT"]},
                            1,
                            0,
                        ]
                    }
                },
                "leave_days": {
                    "$sum": {
                        "$cond": [
                            {"$eq": ["$status", "LEAVE"]},
                            1,
                            0,
                        ]
                    }
                },
                "total_late_minutes": {
                    "$sum": {"$ifNull": ["$late_minutes", 0]}
                },
                "total_overtime_minutes": {
                    "$sum": {"$ifNull": ["$overtime_minutes", 0]}
                },
                "total_work_hours": {
                    "$sum": {"$ifNull": ["$work_hours", 0]}
                },
            }
        },
        {"$project": {"_id": 0}},
    ]

    results = list(db.attendance_logs.aggregate(pipeline))

    summary = results[0] if results else {
        "total_records": 0,
        "present_days": 0,
        "absent_days": 0,
        "leave_days": 0,
        "total_late_minutes": 0,
        "total_overtime_minutes": 0,
        "total_work_hours": 0,
    }

    summary["emp_code"] = emp_code
    summary["month"] = month
    summary["name"] = employee["name"]
    summary["department"] = employee["department"]

    return summary


@app.get("/analytics/departments/summary")
def department_summary(month: str):
    try:
        month_start = datetime.strptime(month, "%Y-%m").date()
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail="month must use YYYY-MM format",
        )

    year, month_number = month_start.year, month_start.month

    if month_number == 12:
        next_month = datetime(year + 1, 1, 1).date()
    else:
        next_month = datetime(year, month_number + 1, 1).date()

    month_end = next_month - timedelta(days=1)
    end_str = month_end.isoformat()
    start_str = month_start.isoformat()

    pipeline = [
        {"$match": {"joined_on": {"$lte": end_str}}},
        {
            "$lookup": {
                "from": "attendance_logs",
                "let": {"code": "$emp_code"},
                "pipeline": [
                    {
                        "$match": {
                            "$expr": {"$eq": ["$emp_code", "$$code"]},
                            "date": {"$gte": start_str, "$lte": end_str},
                        }
                    }
                ],
                "as": "logs",
            }
        },
        {
            "$unwind": {
                "path": "$logs",
                "preserveNullAndEmptyArrays": True,
            }
        },
        {
    "$group": {
        "_id": "$department",
        "employee_codes": {"$addToSet": "$emp_code"},
        "records": {"$push": "$logs"},
    }
    },
    {
        "$set": {
            "headcount": {"$size": "$employee_codes"}
        }
    },
        {
            "$project": {
                "_id": 0,
                "department": "$_id",
                "headcount": 1,
                "attendance_records": {
                    "$filter": {
                        "input": "$records",
                        "as": "r",
                        "cond": {"$ne": ["$$r", {}]},
                    }
                },
            }
        },
        {
            "$project": {
                "department": 1,
                "headcount": 1,
                "attendance_records": 1,

                "present_days": {
                    "$sum": {
                        "$cond": [
                            {
                                "$and": [
                                    {
                                        "$in": [
                                            "$status",
                                            ["PRESENT", "WFH", "ON_DUTY"],
                                        ]
                                    },
                                    {
                                        "$lte": [
                                            {
                                                "$isoDayOfWeek": {
                                                    "$dateFromString": {
                                                        "dateString": "$date",
                                                        "format": "%Y-%m-%d",
                                                    }
                                                }
                                            },
                                            5,
                                        ]
                                    },
                                ]
                            },
                            {
                                "$cond": [
                                    {"$ifNull": ["$half_day", False]},
                                    0.5,
                                    1,
                                ]
                            },
                            0,
                        ]
                    }
                },

                "total_late_minutes": {
                    "$sum": {
                        "$map": {
                            "input": "$attendance_records",
                            "as": "r",
                            "in": {"$ifNull": ["$$r.late_minutes", 0]},
                        }
                    }
                },
                "total_overtime_minutes": {
                    "$sum": {
                        "$map": {
                            "input": "$attendance_records",
                            "as": "r",
                            "in": {"$ifNull": ["$$r.overtime_minutes", 0]},
                        }
                    }
                },
                "total_work_hours": {
                    "$sum": {
                        "$map": {
                            "input": "$attendance_records",
                            "as": "r",
                            "in": {"$ifNull": ["$$r.work_hours", 0]},
                        }
                    }
                },
            }
        },
        {"$unset": "attendance_records"},
        {"$sort": {"department": 1}},
    ]

    return {
        "month": month,
        "items": list(db.employees.aggregate(pipeline)),
    }


@app.get("/analytics/leaderboard/late")
def late_leaderboard(
    month: str,
    limit: int = 10,
):
    try:
        month_start = datetime.strptime(month, "%Y-%m").date()
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail="month must use YYYY-MM format",
        )

    if limit < 1 or limit > 100:
        raise HTTPException(
            status_code=422,
            detail="limit must be between 1 and 100",
        )

    year, month_number = month_start.year, month_start.month

    if month_number == 12:
        next_month = datetime(year + 1, 1, 1).date()
    else:
        next_month = datetime(year, month_number + 1, 1).date()

    first_day = month_start.isoformat()
    last_day = (next_month - timedelta(days=1)).isoformat()

    pipeline = [
        {
            "$match": {
                "date": {"$gte": first_day, "$lte": last_day},
            }
        },
        {
            "$group": {
                "_id": "$emp_code",
                "total_late_minutes": {
                    "$sum": {"$ifNull": ["$late_minutes", 0]}
                },
            }
        },
        {
            "$setWindowFields": {
                "sortBy": {
                    "total_late_minutes": -1,
                },
                "output": {
                    "rank": {"$rank": {}},
                },
            }
        },
        {
            "$sort": {
                "rank": 1,
                "_id": 1,
            }
        },
        {"$limit": limit},
        {
            "$lookup": {
                "from": "employees",
                "localField": "_id",
                "foreignField": "emp_code",
                "as": "employee",
            }
        },
        {
            "$unwind": {
                "path": "$employee",
                "preserveNullAndEmptyArrays": True,
            }
        },
        {
            "$project": {
                "_id": 0,
                "emp_code": "$_id",
                "name": "$employee.name",
                "department": "$employee.department",
                "total_late_minutes": 1,
                "rank": 1,
            }
        },
    ]

    return {
        "month": month,
        "items": list(db.attendance_logs.aggregate(pipeline)),
    }

def _build_department_trend_pipeline(
    department: str,
    start_date,
    end_date,
):
    start_dt = datetime.combine(
        start_date, datetime.min.time(), tzinfo=timezone.utc
    )
    end_exclusive = datetime.combine(
        end_date + timedelta(days=1),
        datetime.min.time(),
        tzinfo=timezone.utc,
    )

    return [
        # Create a seed date, so even an empty attendance range has rows.
        {"$documents": [{"_trend_date": start_dt}]},
        {
            "$densify": {
                "field": "_trend_date",
                "range": {
                    "step": 1,
                    "unit": "day",
                    "bounds": [start_dt, end_exclusive],
                },
            }
        },
        {
            "$set": {
                "date": {
                    "$dateToString": {
                        "format": "%Y-%m-%d",
                        "date": "$_trend_date",
                        "timezone": "UTC",
                    }
                },
                "is_working_day": {
                    "$lte": [{"$isoDayOfWeek": "$_trend_date"}, 5]
                },
            }
        },
        {
            "$lookup": {
                "from": "employees",
                "let": {"day": "$date"},
                "pipeline": [
                    {
                        "$match": {
                            "department": department,
                            "$expr": {"$lte": ["$joined_on", "$$day"]},
                        }
                    },
                    {"$project": {"_id": 0, "emp_code": 1}},
                ],
                "as": "eligible_employees",
            }
        },
        {
            "$set": {
                "headcount": {"$size": "$eligible_employees"},
                "employee_codes": "$eligible_employees.emp_code",
            }
        },
        {
            "$lookup": {
                "from": "attendance_logs",
                "let": {
                    "day": "$date",
                    "codes": "$employee_codes",
                },
                "pipeline": [
                    {
                        "$match": {
                            "$expr": {
                                "$and": [
                                    {"$eq": ["$date", "$$day"]},
                                    {"$in": ["$emp_code", "$$codes"]},
                                ]
                            }
                        }
                    },
                    {
                        "$group": {
                            "_id": None,
                            "present_count": {
                                "$sum": {
                                    "$cond": [
                                        {
                                            "$in": [
                                                "$status",
                                                ["PRESENT", "WFH", "ON_DUTY"],
                                            ]
                                        },
                                        {
                                            "$cond": [
                                                {"$ifNull": ["$half_day", False]},
                                                0.5,
                                                1,
                                            ]
                                        },
                                        0,
                                    ]
                                }
                            },
                            "late_count": {
                                "$sum": {
                                    "$cond": [
                                        {"$gt": ["$late_minutes", 0]},
                                        1,
                                        0,
                                    ]
                                }
                            },
                        }
                    },
                ],
                "as": "daily_totals",
            }
        },
        {
            "$set": {
                "present_count": {
                    "$ifNull": [
                        {"$arrayElemAt": ["$daily_totals.present_count", 0]},
                        0,
                    ]
                },
                "late_count": {
                    "$ifNull": [
                        {"$arrayElemAt": ["$daily_totals.late_count", 0]},
                        0,
                    ]
                },
            }
        },
        {
            "$set": {
                "attendance_rate": {
                    "$cond": [
                        {
                            "$and": [
                                "$is_working_day",
                                {"$gt": ["$headcount", 0]},
                            ]
                        },
                        {
                            "$divide": [
                                {
                                    "$floor": [
                                        {
                                            "$add": [
                                                {
                                                    "$multiply": [
                                                        {
                                                            "$divide": [
                                                                "$present_count",
                                                                "$headcount",
                                                            ]
                                                        },
                                                        10000,
                                                    ]
                                                },
                                                0.5,
                                            ]
                                        }
                                    ]
                                },
                                10000,
                            ]
                        },
                        None,
                    ]
                }
            }
        },
        {
            "$setWindowFields": {
                "sortBy": {"_trend_date": 1},
                "output": {
                    "moving_avg_7d": {
                        "$avg": "$attendance_rate",
                        "window": {"documents": [-6, 0]},
                    }
                },
            }
        },
        {
            "$set": {
                "moving_avg_7d": {
                    "$cond": [
                        {"$ne": ["$moving_avg_7d", None]},
                        {
                            "$divide": [
                                {
                                    "$floor": [
                                        {
                                            "$add": [
                                                {
                                                    "$multiply": [
                                                        "$moving_avg_7d",
                                                        10000,
                                                    ]
                                                },
                                                0.5,
                                            ]
                                        }
                                    ]
                                },
                                10000,
                            ]
                        },
                        None,
                    ]
                }
            }
        },
        {
            "$project": {
                "_id": 0,
                "date": 1,
                "is_working_day": 1,
                "headcount": 1,
                "present_count": 1,
                "late_count": 1,
                "attendance_rate": 1,
                "moving_avg_7d": 1,
            }
        },
        {"$sort": {"date": 1}},
    ]


@app.get("/analytics/departments/{department}/trend")
def department_trend(
    department: str,
    from_date: str = Query(..., alias="from"),
    to_date: str = Query(..., alias="to"),
):
    try:
        start_date = datetime.strptime(from_date, "%Y-%m-%d").date()
        end_date = datetime.strptime(to_date, "%Y-%m-%d").date()

        if start_date.isoformat() != from_date or end_date.isoformat() != to_date:
            raise ValueError
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail="from and to must use YYYY-MM-DD format",
        )

    if end_date < start_date:
        raise HTTPException(422, "to must not be before from")

    if (end_date - start_date).days + 1 > 92:
        raise HTTPException(422, "Date range cannot exceed 92 days")

    if db.employees.count_documents({"department": department}) == 0:
        raise HTTPException(404, "Department not found")

    pipeline = _build_department_trend_pipeline(
        department, start_date, end_date
    )

    return {
        "department": department,
        "from": from_date,
        "to": to_date,
        "items": list(db.aggregate(pipeline)),
    }


@app.get("/admin/explain/{endpoint}")
def explain_endpoint(
    endpoint: str,
    emp_code: Optional[str] = None,
    month: Optional[str] = None,
    department: Optional[str] = None,
    limit: int = 10,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    status: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
):
    allowed = {
        "attendance_list",
        "employee_monthly",
        "department_summary",
        "late_leaderboard",
        "department_trend",
    }

    if endpoint not in allowed:
        raise HTTPException(
            status_code=422,
            detail=f"endpoint must be one of: {', '.join(sorted(allowed))}",
        )

    def get_month_range(value):
        if not value:
            raise HTTPException(422, "month is required")
        try:
            parsed = datetime.strptime(value, "%Y-%m").date()
            if parsed.strftime("%Y-%m") != value:
                raise ValueError
        except ValueError:
            raise HTTPException(422, "month must use YYYY-MM format")

        next_month = (
            datetime(parsed.year + 1, 1, 1).date()
            if parsed.month == 12
            else datetime(parsed.year, parsed.month + 1, 1).date()
        )
        return parsed.isoformat(), (next_month - timedelta(days=1)).isoformat()

    if endpoint == "attendance_list":
        if page < 1:
            raise HTTPException(422, "page must be at least 1")
        if page_size < 1 or page_size > 100:
            raise HTTPException(422, "page_size must be between 1 and 100")
        if status is not None and status not in {
            "PRESENT", "WFH", "ON_DUTY", "ABSENT", "LEAVE"
        }:
            raise HTTPException(422, "Invalid attendance status")

        start = date_from or from_date
        end = date_to or to_date
        query = {}

        if emp_code:
            query["emp_code"] = emp_code
        if start or end:
            query["date"] = {}
            if start:
                query["date"]["$gte"] = start
            if end:
                query["date"]["$lte"] = end
            if start and end and start > end:
                raise HTTPException(422, "from date must not be after to date")
        if status:
            query["status"] = status

        explanation = (
            db.attendance_logs.find(query, {"_id": 0})
            .sort([("date", -1), ("emp_code", 1)])
            .skip((page - 1) * page_size)
            .limit(page_size)
            .explain("executionStats")
        )
        return explanation

    if endpoint == "employee_monthly":
        if not emp_code:
            raise HTTPException(422, "emp_code is required")
        start, end = get_month_range(month)

        if db.employees.find_one({"emp_code": emp_code}) is None:
            raise HTTPException(404, "Employee not found")

        pipeline = [
            {
                "$match": {
                    "emp_code": emp_code,
                    "date": {"$gte": start, "$lte": end},
                }
            },
            {
                "$group": {
                    "_id": None,
                    "total_records": {"$sum": 1},

                "present_days": {
                    "$sum": {
                        "$cond": [
                            {
                                "$and": [
                                    {
                                        "$in": [
                                            "$status",
                                            ["PRESENT", "WFH", "ON_DUTY"],
                                        ]
                                    },
                                    {
                                        "$lte": [
                                            {
                                                "$isoDayOfWeek": {
                                                    "$dateFromString": {
                                                        "dateString": "$date",
                                                        "format": "%Y-%m-%d",
                                                    }
                                                }
                                            },
                                            5,
                                        ]
                                    },
                                ]
                            },
                            {
                                "$cond": [
                                    {"$ifNull": ["$half_day", False]},
                                    0.5,
                                    1,
                                ]
                            },
                            0,
                        ]
                    }
                },

                    "absent_days": {
                        "$sum": {
                            "$cond": [
                                {"$eq": ["$status", "ABSENT"]},
                                1,
                                0,
                            ]
                        }
                    },
                    "leave_days": {
                        "$sum": {
                            "$cond": [
                                {"$eq": ["$status", "LEAVE"]},
                                1,
                                0,
                            ]
                        }
                    },
                    "total_late_minutes": {
                        "$sum": {"$ifNull": ["$late_minutes", 0]}
                    },
                    "total_overtime_minutes": {
                        "$sum": {"$ifNull": ["$overtime_minutes", 0]}
                    },
                    "total_work_hours": {
                        "$sum": {"$ifNull": ["$work_hours", 0]}
                    },
                }
            },
            {"$project": {"_id": 0}},
        ]

        explanation = db.attendance_logs.database.command(
            "explain",
            {"aggregate": "attendance_logs", "pipeline": pipeline, "cursor": {}},
            verbosity="executionStats",
        )
        return explanation

    if endpoint == "department_summary":
        start, end = get_month_range(month)

        pipeline = [
            {"$match": {"joined_on": {"$lte": end}}},
            {
                "$lookup": {
                    "from": "attendance_logs",
                    "let": {"code": "$emp_code"},
                    "pipeline": [
                        {
                            "$match": {
                                "$expr": {"$eq": ["$emp_code", "$$code"]},
                                "date": {"$gte": start, "$lte": end},
                            }
                        }
                    ],
                    "as": "logs",
                }
            },
            {
                "$unwind": {
                    "path": "$logs",
                    "preserveNullAndEmptyArrays": True,
                }
            },
            {
                "$group": {
                    "_id": "$department",
                    "employee_codes": {"$addToSet": "$emp_code"},
                    "records": {"$push": "$logs"},
                }
            },
            {"$set": {"headcount": {"$size": "$employee_codes"}}},
            {
                "$project": {
                    "_id": 0,
                    "department": "$_id",
                    "headcount": 1,
                    "attendance_records": {
                        "$filter": {
                            "input": "$records",
                            "as": "r",
                            "cond": {"$ne": ["$$r", {}]},
                        }
                    },
                }
            },
            {
                "$project": {
                    "department": 1,
                    "headcount": 1,
                    "attendance_records": 1,
                    "present_days": {
                        "$sum": {
                            "$map": {
                                "input": "$attendance_records",
                                "as": "r",
                                "in": {
                                    "$cond": [
                                        {
                                            "$and": [
                                                {
                                                    "$in": [
                                                        "$$r.status",
                                                        ["PRESENT", "WFH", "ON_DUTY"],
                                                    ]
                                                },
                                                {
                                                    "$lte": [
                                                        {
                                                            "$isoDayOfWeek": {
                                                                "$dateFromString": {
                                                                    "dateString": "$$r.date",
                                                                    "format": "%Y-%m-%d",
                                                                }
                                                            }
                                                        },
                                                        5,
                                                    ]
                                                },
                                            ]
                                        },
                                        {
                                            "$cond": [
                                                {
                                                    "$ifNull": [
                                                        "$$r.half_day",
                                                        False,
                                                    ]
                                                },
                                                0.5,
                                                1,
                                            ]
                                        },
                                        0,
                                    ]
                                },
                            }
                        }
                    },
                    "total_late_minutes": {
                        "$sum": {
                            "$map": {
                                "input": "$attendance_records",
                                "as": "r",
                                "in": {"$ifNull": ["$$r.late_minutes", 0]},
                            }
                        }
                    },
                    "total_overtime_minutes": {
                        "$sum": {
                            "$map": {
                                "input": "$attendance_records",
                                "as": "r",
                                "in": {"$ifNull": ["$$r.overtime_minutes", 0]},
                            }
                        }
                    },
                    "total_work_hours": {
                        "$sum": {
                            "$map": {
                                "input": "$attendance_records",
                                "as": "r",
                                "in": {"$ifNull": ["$$r.work_hours", 0]},
                            }
                        }
                    },
                }
            },
            {"$unset": "attendance_records"},
            {"$sort": {"department": 1}},
        ]

        return db.employees.database.command(
            "explain",
            {"aggregate": "employees", "pipeline": pipeline, "cursor": {}},
            verbosity="executionStats",
        )

    if endpoint == "late_leaderboard":
        start, end = get_month_range(month)
        if limit < 1 or limit > 100:
            raise HTTPException(422, "limit must be between 1 and 100")

        pipeline = [
            {"$match": {"date": {"$gte": start, "$lte": end}}},
            {"$group": {
                "_id": "$emp_code",
                "total_late_minutes": {
                    "$sum": {"$ifNull": ["$late_minutes", 0]}
                },
            }},
            {"$setWindowFields": {
                "sortBy": {"total_late_minutes": -1},
                "output": {"rank": {"$rank": {}}},
            }},
            {"$sort": {"rank": 1, "_id": 1}},
            {"$limit": limit},
            {"$lookup": {
                "from": "employees",
                "localField": "_id",
                "foreignField": "emp_code",
                "as": "employee",
            }},
            {"$unwind": {
                "path": "$employee",
                "preserveNullAndEmptyArrays": True,
            }},
            {"$project": {
                "_id": 0,
                "emp_code": "$_id",
                "name": "$employee.name",
                "department": "$employee.department",
                "total_late_minutes": 1,
                "rank": 1,
            }},
        ]
        return db.attendance_logs.database.command(
            "explain",
            {"aggregate": "attendance_logs", "pipeline": pipeline, "cursor": {}},
            verbosity="executionStats",
        )



    if endpoint == "department_trend":
        if not department:
            raise HTTPException(422, "department is required")

        if not from_date or not to_date:
            raise HTTPException(422, "from and to are required")

        try:
            start_date = datetime.strptime(from_date, "%Y-%m-%d").date()
            end_date = datetime.strptime(to_date, "%Y-%m-%d").date()

            if (
                start_date.isoformat() != from_date
                or end_date.isoformat() != to_date
            ):
                raise ValueError
        except ValueError:
            raise HTTPException(
                422, "from and to must use YYYY-MM-DD format"
            )

        if end_date < start_date:
            raise HTTPException(422, "to must not be before from")

        if (end_date - start_date).days + 1 > 92:
            raise HTTPException(422, "Date range cannot exceed 92 days")

        if db.employees.count_documents({"department": department}) == 0:
            raise HTTPException(404, "Department not found")

        pipeline = _build_department_trend_pipeline(
            department, start_date, end_date
        )

        return db.command(
            "explain",
            {
                "aggregate": 1,
                "pipeline": pipeline,
                "cursor": {},
            },
            verbosity="executionStats",
        )
