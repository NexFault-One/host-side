import csv
import json
from pathlib import Path
from datetime import datetime

# always direct to host-side/logs, assuming logger.py is present in parser-core folder. modify if necessary.
LOG_DIR = Path(__file__).resolve().parent.parent / "logs"

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
    
    def log_json(self, data: list[list[str]]):
        """
        Saves all logs (provided in nested array form) in .json format.
        """

        timestamp = datetime.now().strftime("%H_%M_%S")
        filepath = Path(LOG_DIR) / f"{self.name}_{timestamp}.json"

        decoded_data = [ {"data": row[0].decode("utf-8", "ignore").strip(), "timestamp": row[1]} for row in data]
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(decoded_data, f, indent=2)
        
        return filepath