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

        # hardcoded string cleanup. This will NOT take effect and remove /r/n if the entry is not named "Data (ASCII)".
        for entry in decoded_data:
            if "Data (ASCII)" in entry:
                val = entry["Data (ASCII)"]
                if isinstance(val, str):
                    entry["Data (ASCII)"] = val.replace("\r", "").replace("\n", "")

        timestamp = datetime.now().strftime("%H_%M_%S")
        filepath = Path(LOG_DIR) / f"{self.name}_{timestamp}.json"
                

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(decoded_data, f, indent=2)
        
        return filepath