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

from nexfault.protobuf_msgs.proto_msgs import uart_data_pb2
from nexfault.core.parser import SerialDevice
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
    profile_id = Column(String, ForeignKey("profiles.id"), nullable=True, index=True)
    profile = relationship("Profile", back_populates="logs")
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
    
    logs = relationship("LogEntry", back_populates="profile")
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
    user = db.query(User).filter((User.username == credentials.username) | (User.email == credentials.username)).first()    
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

class InjectionRunRequest(BaseModel):
    port: str
    baud: int = 9600

class InjectionReportResponse(BaseModel):
    test_name: str
    profile_name: str
    run_id: int
    injection_type: str
    transport_type: str
    injection_duration_ms: int
    bytes_transmitted: int
    bytes_received: int
    bytes_dropped: int
    bits_flipped: int
    phantom_bytes_added: int
    frames_sent: int
    responses_ok: int
    responses_error: int
    responses_timeout: int
    consecutive_timeout_streak: int
    uut_reset_suspected: bool
    crash_timestamp_ms: int
    avg_response_time_ms: int
    max_response_time_ms: int
    verdict: str
    reason: str
    verdict_message: str

class RunHistoryItem(BaseModel): # real history source, not just per-test raw logs
    test_name: str
    profile_name: str
    created_at: str
    injection_type: str
    transport_type: str
    verdict: str
    reason: str
    status: str
    injection_duration_ms: int

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
        injection_type=normalize_injection_type(profile.injectionType),
        transport=normalize_transport(profile.transport),
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

@app.put("/profiles/{profile_name}", response_model=ProfileResponseReact)
def update_profile(
    profile_name: str,
    profile: ProfileBaseReact,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    db_profile = db.query(Profile).filter(
        Profile.name == profile_name, Profile.owner_id == current_user.id
    ).first()
    if not db_profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    db_profile.name = profile.profileName
    db_profile.description = profile.description
    db_profile.injection_type=normalize_injection_type(profile.injectionType),
    db_profile.transport=normalize_transport(profile.transport),
    db_profile.payload = profile.payload
    db_profile.injection_params_str = profile.injectionParams
    db_profile.duration_str = profile.duration
    db.commit()
    return ProfileResponseReact(id=db_profile.id, **profile.model_dump())

@app.delete("/profiles/{profile_name}", status_code=204)
def delete_profile(
    profile_name: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    db_profile = db.query(Profile).filter(
        Profile.name == profile_name, Profile.owner_id == current_user.id
    ).first()
    if not db_profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    db.delete(db_profile)
    db.commit()

# --- PROFILE-SCOPED TEST ENDPOINTS ---
@app.get("/profiles/{profile_name}/tests", response_model=list[str])
def list_tests_for_profile(
    profile_name: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    profile = db.query(Profile).filter(
        Profile.name == profile_name, Profile.owner_id == current_user.id
    ).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found.")
    query = (
        db.query(LogEntry.test_name)
        .filter(LogEntry.profile_id == profile.id)
        .distinct()
        .all()
    )
    return [name[0] for name in query]

@app.get("/profiles/{profile_name}/tests/{test_name}")
def get_logs_for_profile_test(
    profile_name: str,
    test_name: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    profile = db.query(Profile).filter(
        Profile.name == profile_name, Profile.owner_id == current_user.id
    ).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found.")
    results = db.query(LogEntry).filter(
        LogEntry.profile_id == profile.id, LogEntry.test_name == test_name
    ).all()
    if not results:
        raise HTTPException(
            status_code=404, detail=f"Test '{test_name}' not found in profile."
        )
    return [
        {
            "id": entry.id,
            "test_name": entry.test_name,
            "log_timestamp": entry.log_timestamp,
            "created_at": entry.created_at,
            "hex_data": entry.hex_data,
            "ascii_data": entry.ascii_data,
            "data_type": entry.data_type,
            "raw_data": (
                base64.b64encode(entry.raw_data).decode("utf-8")
                if entry.raw_data else None
            ),
        }
        for entry in results
    ]

@app.get("/profiles/{profile_name}/tests/{test_name}/export")
def export_profile_test_logs(
    profile_name: str,
    test_name: str,
    format: str = "json",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    profile = db.query(Profile).filter(
        Profile.name == profile_name, Profile.owner_id == current_user.id
    ).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found.")
    results = db.query(LogEntry).filter(
        LogEntry.profile_id == profile.id, LogEntry.test_name == test_name
    ).all()
    if not results:
        raise HTTPException(
            status_code=404, detail=f"Test '{test_name}' not found in profile."
        )
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
                if entry.raw_data else None
            ),
        }
        for entry in results
    ]
    filename = f"{profile_name}_{test_name}_export"
    if format == "json":
        return StreamingResponse(
            io.BytesIO(json.dumps(rows, indent=2).encode("utf-8")),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{filename}.json"'},
        )
    elif format == "csv":
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
        return StreamingResponse(
            io.BytesIO(buffer.getvalue().encode("utf-8")),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}.csv"'},
        )
    raise HTTPException(status_code=400, detail="format must be 'csv' or 'json'")

@app.get("/runs", response_model=list[RunHistoryItem])
def get_runs(user_id: str, db: Session = Depends(get_db)):
    profiles = {
        p.id: p.name
        for p in db.query(Profile).filter(Profile.owner_id == int(user_id)).all()
    }

    logs = (
        db.query(LogEntry)
        .filter(LogEntry.owner_id == int(user_id))
        .order_by(LogEntry.created_at.desc())
        .all()
    )

    runs = []
    temp_rows = {}

    for log in logs:
        if log.test_name not in temp_rows:
            temp_rows[log.test_name] = []
        temp_rows[log.test_name].append(log)

    parser_device = SerialDevice("FAKE", 9600)

    for test_name, rows in temp_rows.items():
        report = None
        profile_name = profiles.get(rows[0].profile_id, "Unknown Profile")
        created_at = str(rows[0].created_at)

        for row in rows:
            parsed = parser_device.parse_envelope(row.raw_data)
            if isinstance(parsed, uart_data_pb2.TmiReport):
                report = parsed
                break

        if report:
            runs.append({
                "test_name": test_name,
                "profile_name": profile_name,
                "created_at": created_at,
                "injection_type": uart_data_pb2.InjectionType.Name(report.injection_type),
                "transport_type": uart_data_pb2.TransportType.Name(report.transport_type),
                "verdict": uart_data_pb2.TestVerdict.Name(report.verdict),
                "reason": uart_data_pb2.FailureReason.Name(report.reason),
                "status": uart_data_pb2.ExecStatus.Name(report.status),
                "injection_duration_ms": report.injection_duration_ms,
            })

    return runs
# --- INJECTION EXECUTION ENDPOINT ---

INJECTION_TYPE_MAP = {
    "INJ_BYTE_DROP": uart_data_pb2.InjectionType.INJ_BYTE_DROP,
    "INJ_BIT_FLIP": uart_data_pb2.InjectionType.INJ_BIT_FLIP,
    "INJ_PHANTOM_BYTE": uart_data_pb2.InjectionType.INJ_PHANTOM_BYTE,
}

TRANSPORT_MAP = {
    "TRANSPORT_UART": uart_data_pb2.TransportType.TRANSPORT_UART,
    "TRANSPORT_MODBUS": uart_data_pb2.TransportType.TRANSPORT_MODBUS,
}

def normalize_injection_type(value: str) -> str:
    mapping = {
        "BYTE_DROP": "INJ_BYTE_DROP",
        "BIT_FLIP": "INJ_BIT_FLIP",
        "PHANTOM_BYTE": "INJ_PHANTOM_BYTE",
        "INJ_BYTE_DROP": "INJ_BYTE_DROP",
        "INJ_BIT_FLIP": "INJ_BIT_FLIP",
        "INJ_PHANTOM_BYTE": "INJ_PHANTOM_BYTE",
    }
    return mapping.get(value, value)

def normalize_transport(value: str) -> str:
    mapping = {
        "UART": "TRANSPORT_UART",
        "MODBUS": "TRANSPORT_MODBUS",
        "Modbus": "TRANSPORT_MODBUS",
        "TRANSPORT_UART": "TRANSPORT_UART",
        "TRANSPORT_MODBUS": "TRANSPORT_MODBUS",
    }
    return mapping.get(value, value)


def _build_command_from_profile(profile: Profile) -> uart_data_pb2.DsiCommand:
    """Build a DsiCommand protobuf message from a saved profile."""
    cmd = uart_data_pb2.DsiCommand()
    cmd.id = uuid.uuid4().int & 0xFFFFFFFF
    cmd.cmd = uart_data_pb2.CommandType.CMD_INJECT

    normalized_inj = normalize_injection_type(profile.injection_type)
    inj_type = INJECTION_TYPE_MAP.get(normalized_inj)
    if inj_type is None:
        raise ValueError(f"Unknown injection type: {profile.injection_type}")
    cmd.inj_type = inj_type

    normalized_transport = normalize_transport(profile.transport)
    transport = TRANSPORT_MAP.get(
        normalized_transport,
        uart_data_pb2.TransportType.TRANSPORT_UART
    )
    cmd.transport = transport

    duration_ms = profile.duration_ms
    if duration_ms is None and profile.duration_str:
        try:
            duration_ms = int(profile.duration_str)
        except ValueError:
            raise ValueError(f"Invalid duration: {profile.duration_str}")
    cmd.duration_ms = duration_ms or 5000

    # Parse injection-specific parameters
    params = {}
    if profile.injection_params_str:
        try:
            params = json.loads(profile.injection_params_str)
        except json.JSONDecodeError:
            pass
    if profile.params and isinstance(profile.params, dict):
        params.update(profile.params)

    payload = profile.payload or "default"

    if cmd.inj_type == uart_data_pb2.InjectionType.INJ_BYTE_DROP:
        cmd.byte_drop.start_offset = params.get("start_offset", params.get("startOffset", 0))
        cmd.byte_drop.length = params.get("length", 1)
        cmd.byte_drop.payload = payload
    elif cmd.inj_type == uart_data_pb2.InjectionType.INJ_BIT_FLIP:
        cmd.bit_flip.every_n_p = params.get("every_n_p", params.get("everyNPackets", 2))
        cmd.bit_flip.bits_drop = params.get("bits_drop", params.get("bitsToDrop", 1))
        mode = params.get("mode", "BITFLIP_RANDOM")
        if mode in ["BITFLIP_PERIODIC", "Periodic", "Sequential"]:
            cmd.bit_flip.mode = uart_data_pb2.BitFlipMode.BITFLIP_PERIODIC
        else:
            cmd.bit_flip.mode = uart_data_pb2.BitFlipMode.BITFLIP_RANDOM
    elif cmd.inj_type == uart_data_pb2.InjectionType.INJ_PHANTOM_BYTE:
        cmd.phantom_byte.offset = params.get("offset", 0)
        cmd.phantom_byte.byte_value = params.get("byte_value", params.get("byteValue", 0))
        mode = params.get("mode", "PHANTOM_RANDOM")
        if mode in ["PHANTOM_MANUAL", "Manual", "Inject"]:
            cmd.phantom_byte.mode = uart_data_pb2.PhantomByteMode.PHANTOM_MANUAL
        else:
            cmd.phantom_byte.mode = uart_data_pb2.PhantomByteMode.PHANTOM_RANDOM

    # Modbus config
    if transport == uart_data_pb2.TransportType.TRANSPORT_MODBUS:
        modbus = profile.modbus_config or params.get("modbus_config", {})
        if modbus:
            cmd.modbus_config.slave_id = modbus.get("slave_id", 1)
            cmd.modbus_config.func_code = modbus.get("func_code", 0x03)
            cmd.modbus_config.address = modbus.get("address", 0)
            cmd.modbus_config.value_or_quantity = modbus.get(
                "value_or_quantity", modbus.get("value", 0)
            )
            cmd.modbus_config.recalculate_crc = modbus.get("recalculate_crc", True)

    # Burst mode
    cmd.burst_mode = params.get("burst_mode", False)
    cmd.burst_count = params.get("burst_count", 0)

    return cmd


def _report_to_dict(report, test_name: str, profile_name: str) -> dict:
    """Convert a TmiReport protobuf to a serializable dict."""
    return {
        "test_name": test_name,
        "profile_name": profile_name,
        "run_id": report.run_id,
        "injection_type": uart_data_pb2.InjectionType.Name(report.injection_type),
        "transport_type": uart_data_pb2.TransportType.Name(report.transport_type),
        "injection_duration_ms": report.injection_duration_ms,
        "bytes_transmitted": report.bytes_transmitted,
        "bytes_received": report.bytes_received,
        "bytes_dropped": report.bytes_dropped,
        "bits_flipped": report.bits_flipped,
        "phantom_bytes_added": report.phantom_bytes_added,
        "frames_sent": report.frames_sent,
        "responses_ok": report.responses_ok,
        "responses_error": report.responses_error,
        "responses_timeout": report.responses_timeout,
        "consecutive_timeout_streak": report.consecutive_timeout_streak,
        "uut_reset_suspected": report.uut_reset_suspected,
        "crash_timestamp_ms": report.crash_timestamp_ms,
        "avg_response_time_ms": report.avg_response_time_ms,
        "max_response_time_ms": report.max_response_time_ms,
        "verdict": uart_data_pb2.TestVerdict.Name(report.verdict),
        "reason": uart_data_pb2.FailureReason.Name(report.reason),
        "verdict_message": report.verdict_message,
    }


@app.post("/profiles/{profile_name}/run", response_model=InjectionReportResponse)
def run_injection(
    profile_name: str,
    run_req: InjectionRunRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Execute a fault injection test for a given profile and save results."""
    # Look up the profile
    profile = db.query(Profile).filter(
        Profile.name == profile_name, Profile.owner_id == current_user.id
    ).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found.")

    # Build the DsiCommand from profile parameters
    try:
        cmd = _build_command_from_profile(profile)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Connect to DSI device, send command, and read all responses
    dsi = SerialDevice(run_req.port, run_req.baud)
    dsi.connect(do_handshake=False)

    if not dsi.is_connected():
        raise HTTPException(
            status_code=503, detail="Failed to connect to DSI device."
        )

    try:
        if str(run_req.port).upper() == "FAKE":
            tmi = uart_data_pb2.TmiReport()
            tmi.id = cmd.id
            tmi.run_id = cmd.id
            tmi.attempt_no = 1
            tmi.injection_type = cmd.inj_type
            tmi.transport_type = cmd.transport
            tmi.injection_duration_ms = cmd.duration_ms
            tmi.bytes_transmitted = 8
            tmi.bytes_received = 0
            tmi.bytes_dropped = 0
            tmi.bits_flipped = 5 if cmd.inj_type == uart_data_pb2.InjectionType.INJ_BIT_FLIP else 0
            tmi.phantom_bytes_added = 1 if cmd.inj_type == uart_data_pb2.InjectionType.INJ_PHANTOM_BYTE else 0
            tmi.frames_sent = 4
            tmi.responses_ok = 0
            tmi.responses_error = 0
            tmi.responses_timeout = 4
            tmi.consecutive_timeout_streak = 4
            tmi.uut_reset_suspected = False
            tmi.crash_timestamp_ms = 0
            tmi.avg_response_time_ms = 0
            tmi.max_response_time_ms = 0
            tmi.status = uart_data_pb2.ExecStatus.STATUS_DONE
            tmi.verdict = uart_data_pb2.TestVerdict.VERDICT_PASS
            tmi.reason = uart_data_pb2.FailureReason.FAIL_NONE
            tmi.verdict_message = "Simulated run completed successfully."

            env = uart_data_pb2.Envelope()
            env.report.CopyFrom(tmi)
            tmi_raw = env.SerializeToString()

            # Sanity check before logging anything
            parsed = dsi.parse_envelope(tmi_raw)
            if not isinstance(parsed, uart_data_pb2.TmiReport):
                raise HTTPException(
                    status_code=500,
                    detail="FAKE TmiReport round-trip failed before logging."
                )

            # Keeps FAKE mode minimal and deterministic
            data = [dsi.log_entry(tmi_raw)]
        else:
            dsi.write_protobuf(cmd.SerializeToString())
            read_duration = (cmd.duration_ms / 1000.0) + 8.0
            data = dsi.read_buffer(read_duration)
    finally:
        dsi.disconnect()

    if not data:
        raise HTTPException(
            status_code=504,
            detail="No data received from device during injection.",
        )

    # Save all collected messages to the database via LogFile
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    test_name = f"{profile_name}_{timestamp}"
    headers = [
        "Timestamp", "Length", "Data (Hex)",
        "Data (ASCII)", "Data (Raw)", "Data Type",
    ]
    log = LogFile(test_name, current_user.username, profile.id)
    log.log_db(headers, data)

    # Find the TmiReport among collected messages
    report = None
    for row in data:
        raw = row[4]  # Data (Raw)
        parsed = dsi.parse_envelope(raw)
        if isinstance(parsed, uart_data_pb2.TmiReport):
            report = parsed

    if report is None:
        raise HTTPException(
            status_code=504,
            detail="Injection data was logged but no TmiReport "
                   "was received from device.",
        )

    return _report_to_dict(report, test_name, profile_name)


# ------------------------------ LOG FILE CLASS ------------------------------------
class LogFile:
    def __init__(self, name: str, username: str, profile_id: str | None = None):
        self.name = name
        self.username = username
        self.profile_id = profile_id
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
                    test_name=self.name, owner_id=owner_id, profile_id=self.profile_id,
                    log_timestamp=str(row[p.get("Timestamp")]),
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