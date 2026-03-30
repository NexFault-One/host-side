import base64
import csv
import io
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import bcrypt
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel
from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    create_engine,
)
from sqlalchemy.orm import (
    Session,
    declarative_base,
    relationship,
    sessionmaker,
)
from sqlalchemy.sql import func

# PROFILE SCHEMAS


class ProfileCreate(BaseModel):
    name: str
    description: str | None = None
    transport: str | None = None
    injection_type: str | None = None
    duration_ms: int | None = None
    params: dict[str, Any] | None = None
    modbus_config: dict[str, Any] | None = None


class ProfileUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    transport: str | None = None
    injection_type: str | None = None
    duration_ms: int | None = None
    params: dict[str, Any] | None = None
    modbus_config: dict[str, Any] | None = None


class ProfileResponse(BaseModel):
    profile_id: str
    name: str
    description: str | None
    transport: str | None
    injection_type: str | None
    duration_ms: int | None
    params: dict[str, Any] | None
    modbus_config: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# DB setup (local file path). Change connection information here.
LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
DB_PATH = LOG_DIR / "logs.db"
DB_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(DB_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()
security = HTTPBasic()


class LogEntry(Base):
    __tablename__ = "logs"

    id = Column(Integer, primary_key=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    owner = relationship("User", back_populates="logs")
    test_name = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    log_timestamp = Column(String)
    raw_data = Column(LargeBinary)
    hex_data = Column(String)
    ascii_data = Column(String)
    data_type = Column(String)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True, nullable=False, index=True)
    hashed_password = Column(String, nullable=False)
    logs = relationship("LogEntry", back_populates="owner")
    profiles = relationship("Profile", back_populates="owner")


class Profile(Base):
    __tablename__ = "profiles"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    owner = relationship("User", back_populates="profiles")
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    transport = Column(String, nullable=True)
    injection_type = Column(String, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    params = Column(JSON, nullable=True)
    modbus_config = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(
        DateTime, default=func.now(), onupdate=func.now(), nullable=False
    )


Base.metadata.create_all(engine)

# ----------------------------- AUTH HELPERS ----------------------------------


def hash_password(password: str) -> str:
    """Hash a plaintext password using bcrypt."""
    pwd_bytes = password.encode("utf-8")
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(pwd_bytes, salt)
    return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against a bcrypt hash."""
    password_bytes = plain_password.encode("utf-8")
    hashed_bytes = hashed_password.encode("utf-8")
    return bcrypt.checkpw(password_bytes, hashed_bytes)


# ----------------------------- DB / API HELPERS ------------------------------


def get_db():
    """Yield a database session and ensure it is closed after use."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(
    credentials: HTTPBasicCredentials = Depends(security),
    db: Session = Depends(get_db),
):
    """Authenticate and return the current user from Basic Auth credentials."""
    user = db.query(User).filter(User.username == credentials.username).first()
    if not user or not verify_password(credentials.password, user.hashed_password):
        raise HTTPException(
            status_code=401,
            detail="Invalid username or password.",
            headers={"WWW-Authenticate": "Basic"},
        )
    return user


def get_profile_or_404(profile_id: str, user_id: int, db: Session) -> Profile:
    profile = (
        db.query(Profile)
        .filter(Profile.id == profile_id, Profile.owner_id == user_id)
        .first()
    )
    if not profile:
        raise HTTPException(status_code=404, detail=f"Profile {profile_id} not found.")
    return profile


# --------------------------------- API --------------------------------------

app = FastAPI(title="LogParser")


@app.post("/users/register")
def register_user(username: str, password: str, db: Session = Depends(get_db)):
    """Register a new user."""
    existing = db.query(User).filter(User.username == username).first()
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"Username {username} is already taken.",
        )
    new_user = User(username=username, hashed_password=hash_password(password))
    db.add(new_user)
    db.commit()
    return {"message": "User created successfully."}


@app.get("/profiles", response_model=list[ProfileResponse])
def list_profiles(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return all profiles for the current user."""
    profiles = db.query(Profile).filter(Profile.owner_id == current_user.id).all()
    return [
        ProfileResponse(
            profile_id=p.id,
            name=p.name,
            description=p.description,
            transport=p.transport,
            injection_type=p.injection_type,
            duration_ms=p.duration_ms,
            params=p.params,
            modbus_config=p.modbus_config,
            created_at=p.created_at,
            updated_at=p.updated_at,
        )
        for p in profiles
    ]


@app.post("/profiles", response_model=ProfileResponse, status_code=201)
def create_profile(
    body: ProfileCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new profile for the current user."""
    profile = Profile(
        owner_id=current_user.id,
        **body.model_dump(),
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return ProfileResponse(
        profile_id=profile.id,
        name=profile.name,
        description=profile.description,
        transport=profile.transport,
        injection_type=profile.injection_type,
        duration_ms=profile.duration_ms,
        params=profile.params,
        modbus_config=profile.modbus_config,
        created_at=profile.created_at,
        updated_at=profile.updated_at,
    )


@app.get("/profiles/{profile_id}", response_model=ProfileResponse)
def get_profile(
    profile_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Fetch a single profile by ID."""
    profile = get_profile_or_404(profile_id, current_user.id, db)
    return ProfileResponse(
        profile_id=profile.id,
        name=profile.name,
        description=profile.description,
        transport=profile.transport,
        injection_type=profile.injection_type,
        duration_ms=profile.duration_ms,
        params=profile.params,
        modbus_config=profile.modbus_config,
        created_at=profile.created_at,
        updated_at=profile.updated_at,
    )


@app.put("/profiles/{profile_id}", response_model=ProfileResponse)
def update_profile(
    profile_id: str,
    body: ProfileUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update an existing profile. Only provided fields are changed."""
    profile = get_profile_or_404(profile_id, current_user.id, db)

    updates = body.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(profile, field, value)

    db.commit()
    db.refresh(profile)
    return ProfileResponse(
        profile_id=profile.id,
        name=profile.name,
        description=profile.description,
        transport=profile.transport,
        injection_type=profile.injection_type,
        duration_ms=profile.duration_ms,
        params=profile.params,
        modbus_config=profile.modbus_config,
        created_at=profile.created_at,
        updated_at=profile.updated_at,
    )


@app.delete("/profiles/{profile_id}", status_code=204)
def delete_profile(
    profile_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a profile by ID."""
    profile = get_profile_or_404(profile_id, current_user.id, db)
    db.delete(profile)
    db.commit()


@app.get("/tests", response_model=list[str])
def list_unique_tests(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return a list of all unique test names."""
    query = (
        db.query(LogEntry.test_name)
        .filter(LogEntry.owner_id == current_user.id)
        .distinct()
        .all()
    )
    return [name[0] for name in query]


@app.get("/tests/{test_name}")
def get_logs_for_test(
    test_name: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retrieve all entries for a specific test name."""
    results = (
        db.query(LogEntry)
        .filter(
            LogEntry.test_name == test_name,
            LogEntry.owner_id == current_user.id,
        )
        .all()
    )
    if not results:
        raise HTTPException(
            status_code=404,
            detail=f"Test {test_name} for user {current_user} was not found.",
        )
    output = []
    for entry in results:
        b64_data = None
        if entry.raw_data:
            b64_data = base64.b64encode(entry.raw_data).decode("utf-8")
        output.append(
            {
                "id": entry.id,
                "test_name": entry.test_name,
                "log_timestamp": entry.log_timestamp,
                "created_at": entry.created_at,
                "raw_data": b64_data,
                "hex_data": entry.hex_data,
                "ascii_data": entry.ascii_data,
                "data_type": entry.data_type,
            }
        )
    return output


@app.get("/tests/{test_name}/export")
def export_logs(
    test_name: str,
    format: str = "json",  # "csv" or "json"
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Export all log entries for a test run (in CSV/JSON)."""
    results = (
        db.query(LogEntry)
        .filter(
            LogEntry.test_name == test_name,
            LogEntry.owner_id == current_user.id,
        )
        .all()
    )
    if not results:
        raise HTTPException(status_code=404, detail=f"Test '{test_name}' not found.")

    rows = [
        {
            "id": entry.id,
            "test_name": entry.test_name,
            "log_timestamp": entry.log_timestamp,
            "created_at": str(entry.created_at),
            "hex_data": entry.hex_data,
            "ascii_data": entry.ascii_data,
            "data_type": entry.data_type,
            "raw_data": (
                base64.b64encode(entry.raw_data).decode("utf-8")
                if entry.raw_data
                else None
            ),
        }
        for entry in results
    ]

    filename = f"{test_name}_export"

    if format == "json":
        content = json.dumps(rows, indent=2)
        return StreamingResponse(
            io.BytesIO(content.encode("utf-8")),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{filename}.json"'},
        )

    elif format == "csv":
        buffer = io.StringIO()
        writer = csv.DictWrite(buffer, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
        return StreamingResponse(
            io.BytesIO(buffer.getvalue().encode("utf-8")),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachnemt; filename="{filename}.csv"'},
        )

    else:
        raise HTTPException(status_code=400, detail="format must be 'csv' or 'json'")


# ------------------------------ LOG FILE ------------------------------------


class LogFile:
    """Internal log file creation and manipulation logic."""

    def __init__(self, name: str, username: str):
        """
        Create a log file in parser-core/logs.
        The intended name of the log file should be provided by the caller.
        """
        self.name = name
        self.username = username
        Path(LOG_DIR).mkdir(exist_ok=True)  # try statement?

    def log_csv(self, headers: list[str], rows: list[list[str]]):
        """Save all logs (provided in nested array form) in .csv format."""
        timestamp = datetime.now().strftime("%H_%M_%S")
        filepath = Path(LOG_DIR) / f"{self.name}_{timestamp}.csv"
        file_exists = filepath.exists()

        with open(filepath, mode="a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(headers)
            writer.writerows(rows)

        return filepath

    def sanitize_json(self, data):
        """
        Convert all bytes to strings to prevent JSON errors.
        Does not affect safe types.
        """
        if isinstance(data, bytes):
            return data.decode("utf-8", "ignore").strip()
        elif isinstance(data, list):
            return [self.sanitize_json(values) for values in data]
        else:
            return data

    def log_json(self, params: list[str], data: list[list[str]]):
        """Save all logs (provided in nested array form) in .json format."""
        if len(params) != len(data[0]):
            print(
                f"{len(params)} given parameters do not match "
                f"{len(data[0])} values provided."
            )
            return None

        sanitized_data = self.sanitize_json(data)
        decoded_data = [
            {params[i]: value for i, value in enumerate(row)} for row in sanitized_data
        ]

        # Hardcoded string cleanup. Necessary for JSON implementation.
        # Must be updated with additions to log files.
        for entry in decoded_data:
            # Remove escape sequences from "Data (ASCII)" values.
            if "Data (ASCII)" in entry:
                val = entry["Data (ASCII)"]
                if isinstance(val, str):
                    entry["Data (ASCII)"] = val.replace("\r", "").replace("\n", "")
            # Convert object type name to a string literal for "Data Type".
            if "Data Type" in entry:
                val = entry["Data Type"]
                entry["Data Type"] = f"{val.__module__}.{val.__name__}"

        timestamp = datetime.now().strftime("%H_%M_%S")
        filepath = Path(LOG_DIR) / f"{self.name}_{timestamp}.json"

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(decoded_data, f, indent=2)

        return filepath

    def _get_owner_id(self, session: Session) -> int:
        """Retrieve the owner ID for the current username."""
        user = session.query(User).filter(User.username == self.username).first()
        if not user:
            raise ValueError(f"No user found with username '{self.username}'.")
        return user.id

    def log_db(self, params: list[str], data: list[list[str]]):
        """
        Save logs to the SQLite database using SQLAlchemy.
        Sanitizes data and commits. Uses hardcoded parameters.
        """
        if not data:
            return None
        if len(params) != len(data[0]):
            print(
                f"{len(params)} given parameters do not match "
                f"{len(data[0])} values provided."
            )
            return None

        session = SessionLocal()
        try:
            owner_id = self._get_owner_id(session)
            p = {name: i for i, name in enumerate(params)}

            for row in data:
                # Hardcoded raw, hex, ascii, and datatype handling.
                raw_val = row[p.get("Data (Raw)")]
                if not isinstance(raw_val, bytes):
                    raw_val = str(raw_val).encode("utf-8")

                hex_val = row[p.get("Data (Hex)")]
                if isinstance(hex_val, bytes):
                    hex_val = hex_val.hex()

                ascii_val = row[p.get("Data (ASCII)")]
                if isinstance(ascii_val, bytes):
                    ascii_val = ascii_val.decode("utf-8", "ignore")
                ascii_val = str(ascii_val).replace("\r", "").replace("\n", "")

                dtype_val = row[p.get("Data Type")]
                if hasattr(dtype_val, "module") and hasattr(dtype_val, "name"):
                    dtype_str = f"{dtype_val.module}.{dtype_val.name}"
                else:
                    dtype_str = str(dtype_val)

                log_entry = LogEntry(
                    test_name=self.name,
                    owner_id=owner_id,
                    log_timestamp=str(row[p.get("Timestamp")]),
                    raw_data=raw_val,
                    hex_data=str(hex_val),
                    ascii_data=ascii_val,
                    data_type=dtype_str,
                )
                session.add(log_entry)

            session.commit()

        except Exception as e:
            session.rollback()
            print(f"Database error: {e}")
            raise e

        finally:
            session.close()

    def retrieve_logs(self, testname: str):
        """Search the database for any entries with the specified test name."""
        session = SessionLocal()
        try:
            owner_id = self._get_owner_id(session)
            results = (
                session.query(LogEntry)
                .filter(
                    LogEntry.test_name == testname,
                    LogEntry.owner_id == owner_id,
                )
                .all()
            )
            return [
                {
                    "id": entry.id,
                    "test_name": entry.test_name,
                    "log_timestamp": entry.log_timestamp,
                    "created_at": entry.created_at,
                    "raw_data": entry.raw_data,
                    "hex_data": entry.hex_data,
                    "ascii_data": entry.ascii_data,
                    "data_type": entry.data_type,
                }
                for entry in results
            ]
        except Exception as e:
            print(f"Error retrieving test: {e}")
            return []
        finally:
            session.close()

    def retrieve_tests(self):
        """Return all unique test names."""
        session = SessionLocal()
        try:
            owner_id = self._get_owner_id(session)
            query = (
                session.query(LogEntry.test_name)
                .filter(LogEntry.owner_id == owner_id)
                .distinct()
                .all()
            )
            return [name[0] for name in query]
        except Exception as e:
            print(f"Error retrieving test names: {e}")
            return []
        finally:
            session.close()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
