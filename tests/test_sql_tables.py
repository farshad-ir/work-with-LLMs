import re
import sys
import sqlite3
from pathlib import Path
from datetime import datetime

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

from app.mt5_sqlite import DB_PATH


def get_hour(value):
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value).hour

    match = re.search(r'(?:T|\s)(\d{2}):\d{2}', str(value))
    if match:
        return int(match.group(1))

    return None


def last_hour(conn, table, time_column):
    row = conn.execute(
        f'SELECT "{time_column}" FROM "{table}" ORDER BY id DESC LIMIT 1'
    ).fetchone()

    return get_hour(row[0]) if row else None


def main():
    with sqlite3.connect(DB_PATH) as conn:

        h1 = last_hour(conn, "h1Candles", "time")
        h6 = last_hour(conn, "h6Candles", "time")

        print(f"({h1},{h6})")

        box = last_hour(conn, "SmallBoxes", "EndTime")

        if box is not None:
            print(f"Box {box}")


if __name__ == "__main__":
    main()
