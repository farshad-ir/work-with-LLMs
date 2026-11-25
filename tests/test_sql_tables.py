import re
import sys
import sqlite3
from pathlib import Path
from datetime import datetime

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

from app.mt5_sqlite import DB_PATH


DATE_NOTICE_FILE = DB_PATH.parent / "last_h1_date_notice.txt"


def parse_datetime(value):
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value)

    text = str(value).strip()

    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        match = re.search(
            r"(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}(?::\d{2})?)",
            text
        )
        if match:
            return datetime.fromisoformat(
                f"{match.group(1)} {match.group(2)}"
            )

    return None


def last_candle_time(conn, table, time_column):
    row = conn.execute(
        f'SELECT "{time_column}" FROM "{table}" ORDER BY id DESC LIMIT 1'
    ).fetchone()

    return parse_datetime(row[0]) if row else None


def last_box_hour(conn):
    row = conn.execute(
        'SELECT "EndTime" FROM "SmallBoxes" ORDER BY "EndTime" DESC LIMIT 1'
    ).fetchone()

    if not row:
        return None

    box_time = parse_datetime(row[0])
    return box_time.hour if box_time else None


def show_h1_date_once(candle_time):
    if candle_time is None or candle_time.hour != 1:
        return

    current_date = candle_time.date().isoformat()

    try:
        previous_date = DATE_NOTICE_FILE.read_text(
            encoding="utf-8"
        ).strip()
    except FileNotFoundError:
        previous_date = ""

    if current_date == previous_date:
        return

    print(f"({current_date})")
    DATE_NOTICE_FILE.parent.mkdir(parents=True, exist_ok=True)
    DATE_NOTICE_FILE.write_text(current_date, encoding="utf-8")


def main():
    with sqlite3.connect(DB_PATH) as conn:
        h1_time = last_candle_time(conn, "h1Candles", "time")
        h6_time = last_candle_time(conn, "h6Candles", "time")

        h1 = h1_time.hour if h1_time else None
        h6 = h6_time.hour if h6_time else None

        print(f"({h1},{h6})")
        show_h1_date_once(h1_time)

        box = last_box_hour(conn)

        if box is not None:
            print(f"Box {box}")


if __name__ == "__main__":
    main()
    
