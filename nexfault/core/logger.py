import csv
import json
from pathlib import Path
from datetime import datetime
from typing import List, Optional
from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    DateTime,
    JSON,
    LargeBinary,
    ForeignKey,
)
from sqlalchemy.orm import declarative_base, sessionmaker, Session, relationship
from fastapi import FastAPI, Depends, HTTPException
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.middleware.cors import CORSMiddleware
import bcrypt
import base64


# DB setup
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
    test_name = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    log_timestamp = Column(String)
    raw_data = Column(LargeBinary)
    hex_data = Column(String)
    ascii_data = Column(String)
    data_type = Column(String)

    owner = relationship("User", back_populates="logs")

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True, nullable=False, index=True)
    hashed_password = Column(String, nullable=False)

    logs = relationship("LogEntry", back_populates="owner")

Base.metadata.create_all(engine)

def hash_password(password: str) -> str:
    pwd_bytes = password.encode('utf-8')
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(pwd_bytes, salt)
    return hashed.decode('utf-8')

def verify_password(plain_password: str, hashed_password: str) -> bool:
    password_bytes = plain_password.encode('utf-8')
    hashed_bytes = hashed_password.encode('utf-8')
    return bcrypt.checkpw(password_bytes, hashed_bytes)

# API HELPER
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# USER VERIFICATION
def get_current_user(credentials: HTTPBasicCredentials = Depends(security), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == credentials.username).first()
    
    if not user or not verify_password(credentials.password, user.hashed_password):
        raise HTTPException(
            status_code=401,
            detail="Unauthorized: Invalid username or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    return user

# API FRAMEWORK
app = FastAPI(title="LogParser")

# ENDPOINTS
@app.post("/users/register")
def register_user(username: str, password: str, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.username == username).first()
    if existing:
        raise HTTPException(status_code=400, detail="Username taken")
    
    new_user = User(
        username=username, 
        hashed_password=hash_password(password)
    )
    db.add(new_user)
    db.commit()
    return {"message": "User created successfully"}

@app.get("/tests", response_model=List[str])
def list_unique_tests(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """
    Returns a list of all unique test names.
    """
    query = db.query(LogEntry.test_name).filter(LogEntry.owner_id == current_user.id).distinct().all()
    return [name[0] for name in query]

@app.get("/tests/{test_name}")
def get_logs_for_test(test_name: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """
    Retrieves all entries for a specific test name.
    """

    results = db.query(LogEntry).filter(LogEntry.test_name == test_name, LogEntry.owner_id == current_user.id).all()

    if not results:
        raise HTTPException(status_code=404, detail="test was not found.")
    
    output = []
    for entry in results:
        b64_data = None
        if entry.raw_data:
            b64_data = base64.b64encode(entry.raw_data).decode('utf-8')

        output.append({
            "id": entry.id,
            "test_name": entry.test_name,
            "log_timestamp": entry.log_timestamp,
            "created_at": entry.created_at,
            "raw_data": b64_data, 
            "hex_data": entry.hex_data,
            "ascii_data": entry.ascii_data,
            "data_type": entry.data_type
        })
    return output


# internal log file creation and manipulation logic
class LogFile:

    def __init__(self, name, owner_id):
        """
        Creates file in parser-core/logs. The intended name of the log file should be provided by caller.
        """

        self.name = name
        self.owner_id = owner_id
        Path(LOG_DIR).mkdir(exist_ok=True)
    
    def log_csv(self, headers: list[str], rows: list[list[str]]):
        """
        Saves all logs (provided in nested array form) in .csv format.
        """

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
        Converts all bytes into strings to prevent json errors. Does not affect safe types.
        """
        if isinstance(data, bytes):
            return data.decode("utf-8", "ignore").strip()
        elif isinstance(data, list):
            return [self.sanitize_json(values) for values in data]
        else:
            return data
    
    def log_json(self, params: list[str], data: list[list[str]]):
        """
        Saves all logs (provided in nested array form) in .json format.
        """

        if len(params) != len(data[0]):
            print ("parameters do not match values.")
            return None

        sanitized_data = self.sanitize_json(data)
        decoded_data = [{params[param]: value for param, value in enumerate(row)} for row in sanitized_data]

        # hardcoded string cleanup. necessary for JSON implementation, must be updated with additions to log files
        for entry in decoded_data:
            # takes raw string and removes escape sequences if expected "Data (ASCII)"
            if "Data (ASCII)" in entry:
                val = entry["Data (ASCII)"]
                if isinstance(val, str):
                    entry["Data (ASCII)"] = val.replace("\r", "").replace("\n", "")
            # also converts object type name to a string literal if expected "Data Type"
            if "Data Type" in entry:
                val = entry["Data Type"]
                entry["Data Type"] = f"{val.__module__}.{val.__name__}"

        timestamp = datetime.now().strftime("%H_%M_%S")
        filepath = Path(LOG_DIR) / f"{self.name}_{timestamp}.json"
                

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(decoded_data, f, indent=2)
        
        return filepath
    
    def log_db(self, params: list[str], data: list[list[str]]):
        """
        Saves logs to SQLite database using SQLAlchemy. will sanitize json data and commit
        """

        if not data:
            return None
        if len(params) != len(data[0]):
            print ("params do not match values!")
            return None

        session = SessionLocal()

        try:
            p = {name: i for i, name in enumerate(params)}

            for row in data:

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
                    owner_id = self.owner_id,
                    log_timestamp=str(row[p.get("Timestamp")]),
                    raw_data=raw_val,
                    hex_data=str(hex_val),
                    ascii_data=ascii_val,
                    data_type=dtype_str
                )

                session.add(log_entry)
            
            session.commit()
        
        except Exception as e:
            session.rollback()
            print(f"Database Error: {e}")
            raise e
        
        finally:
            session.close()

    def retrieve_logs(self, testname: str):
        """
        Searches the database for any entries with the specified test name.
        """

        session = SessionLocal()
        try:
            results = session.query(LogEntry).filter(LogEntry.test_name == testname, LogEntry.owner_id == self.owner_id).all()

            output = []
            for entry in results:
                output.append({
                    "id": entry.id,
                    "test_name": entry.test_name,
                    "log_timestamp": entry.log_timestamp,
                    "created_at": entry.created_at,
                    "raw_data": entry.raw_data,
                    "hex_data": entry.hex_data,
                    "ascii_data": entry.ascii_data,
                    "data_type": entry.data_type
                })
            return output
        except Exception as e:
            print(f"Error retrieving test: {e}")
            return []
        finally:
            session.close()
    
    def retrieve_tests(self):
        """
        Returns all unique test names
        """
        session = SessionLocal()
        try:
            query = session.query(LogEntry.test_name).distinct().all()
            unique_tests = [name[0] for name in query]
            return unique_tests
        except Exception as e:
            print(f"Error retrieving test names: {e}")
            return []
        finally:
            session.close()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)