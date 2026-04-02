import base64
import csv
import io
import json
import uuid
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any

import bcrypt
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.middleware.cors import CORSMiddleware
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
# ----------------------------- DB SETUP --------------------------------------
LOG_DIR = Path(__file__).resolve().parent.parent / "logs"

# Automatically creates the 'logs' folder to prevent SQLite OperationalErrors
LOG_DIR.mkdir(parents=True, exist_ok=True) 

# CHANGE THE LINE BELOW
DB_PATH = LOG_DIR / "app_data.db"
DB_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(DB_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()
security = HTTPBasic()

# ----------------------------- DB MODELS -------------------------------------
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
    username = Column(String, unique=True, nullable=True, index=True)
    email = Column(String, unique=True, nullable=True, index=True)
    first_name = Column(String, nullable=True)
    last_name = Column(String, nullable=True)
    hashed_password = Column(String, nullable=False)
    logs = relationship("LogEntry", back_populates="owner")
    profiles = relationship("Profile", back_populates="owner")

class Profile(Base):
    __tablename__ = "profiles"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    owner = relationship("User", back_populates="profiles")
    
    # Original Logging Fields
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    transport = Column(String, nullable=True)
    injection_type = Column(String, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    params = Column(JSON, nullable=True)
    modbus_config = Column(JSON, nullable=True)
    
    # React Frontend Fields
    payload = Column(String, nullable=True)
    duration_str = Column(String, nullable=True)
    injection_params_str = Column(String, nullable=True)
    
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)

Base.metadata.create_all(engine)

# ----------------------------- AUTH HELPERS ----------------------------------
def hash_password_bcrypt(password: str) -> str:
    pwd_bytes = password.encode("utf-8")
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(pwd_bytes, salt).decode("utf-8")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    if len(hashed_password) == 64 and "$" not in hashed_password:
        return hashlib.sha256(plain_password.encode()).hexdigest() == hashed_password
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except ValueError:
        return False

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_current_user(
    credentials: HTTPBasicCredentials = Depends(security),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.username == credentials.username).first()
    if not user or not verify_password(credentials.password, user.hashed_password):
        raise HTTPException(
            status_code=401,
            detail="Invalid username or password.",
            headers={"WWW-Authenticate": "Basic"},
        )
    return user

# ----------------------------- PYDANTIC SCHEMAS ------------------------------
class UserCreateReact(BaseModel):
    firstName: str
    lastName: str
    email: str
    password: str

class UserLogin(BaseModel):
    email: str
    password: str

class UserResponseReact(BaseModel):
    id: str
    firstName: str
    lastName: str
    email: str

class ProfileBaseReact(BaseModel):
    userId: str
    profileName: str
    description: str = ""
    injectionType: str
    transport: str
    payload: str = ""
    injectionParams: str = ""
    duration: str

class ProfileResponseReact(ProfileBaseReact):
    id: str
    class Config:
        from_attributes = True

# --------------------------------- API --------------------------------------
app = FastAPI(title="LogParser Unified API")

# Added CORS for the React Frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- REACT AUTH ENDPOINTS ---
@app.post("/users/register", response_model=UserResponseReact)
def register_user(user: UserCreateReact, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == user.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")
    
    db_user = User(
        username=user.email.split('@')[0], 
        first_name=user.firstName,
        last_name=user.lastName,
        email=user.email,
        hashed_password=hash_password_bcrypt(user.password)
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return UserResponseReact(id=str(db_user.id), firstName=db_user.first_name or "", lastName=db_user.last_name or "", email=db_user.email)

@app.post("/users/login", response_model=UserResponseReact)
def login_user(user: UserLogin, db: Session = Depends(get_db)):
    db_user = db.query(User).filter(User.email == user.email).first()
    if not db_user or not verify_password(user.password, db_user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid email or password")
        
    return UserResponseReact(id=str(db_user.id), firstName=db_user.first_name or "", lastName=db_user.last_name or "", email=db_user.email)

# --- REACT PROFILE ENDPOINTS ---
@app.post("/profiles", response_model=ProfileResponseReact, status_code=201)
def create_profile(profile: ProfileBaseReact, db: Session = Depends(get_db)):
    db_profile = Profile(
        id=str(uuid.uuid4()),
        owner_id=int(profile.userId),
        name=profile.profileName,
        description=profile.description,
        injection_type=profile.injectionType,
        transport=profile.transport,
        payload=profile.payload,
        injection_params_str=profile.injectionParams,
        duration_str=profile.duration
    )
    db.add(db_profile)
    db.commit()
    db.refresh(db_profile)
    return ProfileResponseReact(id=db_profile.id, **profile.model_dump())

@app.get("/profiles", response_model=list[ProfileResponseReact])
def get_profiles(user_id: str = None, db: Session = Depends(get_db)):
    if user_id:
        profiles = db.query(Profile).filter(Profile.owner_id == int(user_id)).all()
    else:
        profiles = db.query(Profile).all()
        
    return [
        ProfileResponseReact(
            id=p.id, userId=str(p.owner_id), profileName=p.name, description=p.description or "",
            injectionType=p.injection_type or "", transport=p.transport or "", payload=p.payload or "",
            injectionParams=p.injection_params_str or "", duration=p.duration_str or ""
        ) for p in profiles
    ]

@app.put("/profiles/{profile_id}", response_model=ProfileResponseReact)
def update_profile(profile_id: str, profile: ProfileBaseReact, db: Session = Depends(get_db)):
    db_profile = db.query(Profile).filter(Profile.id == profile_id).first()
    if not db_profile: raise HTTPException(status_code=404, detail="Profile not found")
    
    db_profile.name = profile.profileName
    db_profile.description = profile.description
    db_profile.injection_type = profile.injectionType
    db_profile.transport = profile.transport
    db_profile.payload = profile.payload
    db_profile.injection_params_str = profile.injectionParams
    db_profile.duration_str = profile.duration

    db.commit()
    return ProfileResponseReact(id=db_profile.id, **profile.model_dump())

@app.delete("/profiles/{profile_id}", status_code=204)
def delete_profile(profile_id: str, db: Session = Depends(get_db)):
    db_profile = db.query(Profile).filter(Profile.id == profile_id).first()
    if not db_profile: raise HTTPException(status_code=404, detail="Profile not found")
    db.delete(db_profile)
    db.commit()

# --- LEGACY LOGGING ENDPOINTS ---
@app.get("/tests", response_model=list[str])
def list_unique_tests(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(LogEntry.test_name).filter(LogEntry.owner_id == current_user.id).distinct().all()
    return [name[0] for name in query]

@app.get("/tests/{test_name}")
def get_logs_for_test(
    test_name: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    results = db.query(LogEntry).filter(LogEntry.test_name == test_name, LogEntry.owner_id == current_user.id).all()
    if not results:
        raise HTTPException(status_code=404, detail=f"Test {test_name} not found.")
    
    output = []
    for entry in results:
        b64_data = base64.b64encode(entry.raw_data).decode("utf-8") if entry.raw_data else None
        output.append({
            "id": entry.id, "test_name": entry.test_name, "log_timestamp": entry.log_timestamp,
            "created_at": entry.created_at, "raw_data": b64_data, "hex_data": entry.hex_data,
            "ascii_data": entry.ascii_data, "data_type": entry.data_type,
        })
    return output

@app.get("/tests/{test_name}/export")
def export_logs(
    test_name: str,
    format: str = "json",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    results = db.query(LogEntry).filter(LogEntry.test_name == test_name, LogEntry.owner_id == current_user.id).all()
    if not results:
        raise HTTPException(status_code=404, detail=f"Test '{test_name}' not found.")

    rows = [{
        "id": entry.id, "test_name": entry.test_name, "log_timestamp": entry.log_timestamp,
        "created_at": str(entry.created_at), "hex_data": entry.hex_data, "ascii_data": entry.ascii_data,
        "data_type": entry.data_type,
        "raw_data": base64.b64encode(entry.raw_data).decode("utf-8") if entry.raw_data else None,
    } for entry in results]

    filename = f"{test_name}_export"

    if format == "json":
        return StreamingResponse(io.BytesIO(json.dumps(rows, indent=2).encode("utf-8")), media_type="application/json", headers={"Content-Disposition": f'attachment; filename="{filename}.json"'})
    elif format == "csv":
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
        return StreamingResponse(io.BytesIO(buffer.getvalue().encode("utf-8")), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{filename}.csv"'})
    
    raise HTTPException(status_code=400, detail="format must be 'csv' or 'json'")

# ------------------------------ LOG FILE CLASS ------------------------------------
class LogFile:
    def __init__(self, name: str, username: str):
        self.name = name
        self.username = username
        Path(LOG_DIR).mkdir(exist_ok=True)

    def log_csv(self, headers: list[str], rows: list[list[str]]):
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
        if isinstance(data, bytes):
            return data.decode("utf-8", "ignore").strip()
        elif isinstance(data, list):
            return [self.sanitize_json(values) for values in data]
        return data

    def log_json(self, params: list[str], data: list[list[str]]):
        if len(params) != len(data[0]):
            return None
        sanitized_data = self.sanitize_json(data)
        decoded_data = [{params[i]: value for i, value in enumerate(row)} for row in sanitized_data]

        for entry in decoded_data:
            if "Data (ASCII)" in entry and isinstance(entry["Data (ASCII)"], str):
                entry["Data (ASCII)"] = entry["Data (ASCII)"].replace("\r", "").replace("\n", "")
            if "Data Type" in entry:
                val = entry["Data Type"]
                entry["Data Type"] = f"{val.__module__}.{val.__name__}"

        timestamp = datetime.now().strftime("%H_%M_%S")
        filepath = Path(LOG_DIR) / f"{self.name}_{timestamp}.json"
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(decoded_data, f, indent=2)
        return filepath

    def _get_owner_id(self, session: Session) -> int:
        user = session.query(User).filter(User.username == self.username).first()
        if not user:
            raise ValueError(f"No user found with username '{self.username}'.")
        return user.id

    def log_db(self, params: list[str], data: list[list[str]]):
        if not data or len(params) != len(data[0]):
            return None
        session = SessionLocal()
        try:
            owner_id = self._get_owner_id(session)
            p = {name: i for i, name in enumerate(params)}
            for row in data:
                raw_val = row[p.get("Data (Raw)")]
                if not isinstance(raw_val, bytes):
                    raw_val = str(raw_val).encode("utf-8")
                
                hex_val = row[p.get("Data (Hex)")]
                if isinstance(hex_val, bytes): hex_val = hex_val.hex()

                ascii_val = row[p.get("Data (ASCII)")]
                if isinstance(ascii_val, bytes): ascii_val = ascii_val.decode("utf-8", "ignore")
                ascii_val = str(ascii_val).replace("\r", "").replace("\n", "")

                dtype_val = row[p.get("Data Type")]
                dtype_str = f"{dtype_val.module}.{dtype_val.name}" if hasattr(dtype_val, "module") and hasattr(dtype_val, "name") else str(dtype_val)

                log_entry = LogEntry(
                    test_name=self.name, owner_id=owner_id, log_timestamp=str(row[p.get("Timestamp")]),
                    raw_data=raw_val, hex_data=str(hex_val), ascii_data=ascii_val, data_type=dtype_str,
                )
                session.add(log_entry)
            session.commit()
        except Exception as e:
            session.rollback()
            raise e
        finally:
            session.close()

    def retrieve_logs(self, testname: str):
        session = SessionLocal()
        try:
            owner_id = self._get_owner_id(session)
            results = session.query(LogEntry).filter(LogEntry.test_name == testname, LogEntry.owner_id == owner_id).all()
            return [{
                "id": entry.id, "test_name": entry.test_name, "log_timestamp": entry.log_timestamp,
                "created_at": entry.created_at, "raw_data": entry.raw_data, "hex_data": entry.hex_data,
                "ascii_data": entry.ascii_data, "data_type": entry.data_type,
            } for entry in results]
        except Exception as e:
            print(f"Error retrieving test: {e}")
            return []
        finally:
            session.close()

    def retrieve_tests(self):
        session = SessionLocal()
        try:
            owner_id = self._get_owner_id(session)
            query = session.query(LogEntry.test_name).filter(LogEntry.owner_id == owner_id).distinct().all()
            return [name[0] for name in query]
        except Exception as e:
            print(f"Error retrieving test names: {e}")
            return []
        finally:
            session.close()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)