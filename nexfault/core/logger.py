import csv
import json
from pathlib import Path
from datetime import datetime
from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    DateTime,
    JSON,
)
from sqlalchemy.orm import declarative_base, sessionmaker

# always direct to host-side/logs, assuming logger.py is present in parser-core folder. modify if necessary.
LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
DB_PATH = LOG_DIR / "logs.db"
DB_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(DB_URL, echo=False)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

class LogEntry(Base):
    __tablename__ = "logs"

    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    log_name = Column(String, nullable=False)
    data = Column(JSON, nullable=False)

Base.metadata.create_all(engine)

# log file creation and manipulation logic
class LogFile:

    def __init__(self, name):
        """
        Creates file in parser-core/logs. The intended name of the log file should be provided by caller.
        """

        self.name = name
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
        sanitized_data = self.sanitize_json(data)
        

        session = SessionLocal()

        try:
            for row in sanitized_data:

                entry_data = {}

                # hard coded sanitization for python data types
                for i in range(len(params)):
                    key = params[i]
                    value = row[i]

                    if key == "Data Type" and isinstance(value, type):
                        value = f"{value.__module__}.{value.__name__}"

                    entry_data[key] = value

                log_entry = LogEntry(
                    log_name=self.name,
                    data=entry_data,
                )

                session.add(log_entry)
            
            session.commit()
        
        except Exception as e:
            session.rollback()
            raise e
        
        finally:
            session.close()
