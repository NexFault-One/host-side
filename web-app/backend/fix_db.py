import sqlite3
from pathlib import Path

# Connect to the database
LOGS_DB = Path(__file__).resolve().parent.parent / "logs" / "logs.db"
conn = sqlite3.connect(LOGS_DB)
cursor = conn.cursor()

# Force add the missing columns
columns_to_add = [
    "ALTER TABLE users ADD COLUMN email VARCHAR UNIQUE;",
    "ALTER TABLE users ADD COLUMN first_name VARCHAR;",
    "ALTER TABLE users ADD COLUMN last_name VARCHAR;",
    "ALTER TABLE profiles ADD COLUMN payload VARCHAR;",
    "ALTER TABLE profiles ADD COLUMN duration_str VARCHAR;",
    "ALTER TABLE profiles ADD COLUMN injection_params_str VARCHAR;"
]

print("Updating database schema...")
for cmd in columns_to_add:
    try:
        cursor.execute(cmd)
        print(f"Success: {cmd}")
    except sqlite3.OperationalError:
        print(f"Skipped (already exists): {cmd}")

conn.commit()
conn.close()
print("Done! You can now log in.")