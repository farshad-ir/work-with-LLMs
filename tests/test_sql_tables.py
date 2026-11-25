import re
import sys
import sqlite3
from pathlib import Path
from datetime import datetime

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

from app.mt5_sqlite import DB_PATH


DATE_NOTICE_FILE = DB_PATH.parent / "last_h1_date_notice.txt"


def get_hour(value):
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value).hour

    match = re.search(r'(?:T|\s)(\d{2}):\d{2}', str(value))
    if match:
        return int(match.group(1))

    return None


def get_date(value):
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value).date()

    match = re.search(
        r'(\d{4})[.-](\d{2})[.-](\d{2})',
        str(value)
    )

    if match:
        try:
            return datetime(
                int(match.group(1)),
                int(match.group(2)),
                int(match.group(3))
            ).date()
        except ValueError:
            pass

    return None


def last_hour(conn, table, time_column):
    row = conn.execute(
        f'SELECT "{time_column}" FROM "{table}" ORDER BY id DESC LIMIT 1'
    ).fetchone()

    return get_hour(row[0]) if row else None


def main():
    with sqlite3.connect(DB_PATH) as conn:

        h1_row = conn.execute(
            'SELECT "time" FROM "h1Candles" ORDER BY id DESC LIMIT 1'
        ).fetchone()

        h1 = get_hour(h1_row[0]) if h1_row else None
        h6 = last_hour(conn, "h6Candles", "time")

        output = f"({h1},{h6})"

        # نمایش تاریخ فقط یک بار در روز و در ساعت ۱
        if h1 == 1 and h1_row:
            current_date = get_date(h1_row[0])

            if current_date is not None:
                date_text = current_date.isoformat()

                try:
                    previous_date = DATE_NOTICE_FILE.read_text(
                        encoding="utf-8"
                    ).strip()
                except FileNotFoundError:
                    previous_date = ""

                if date_text != previous_date:
                    output += f" ({date_text})"

                    DATE_NOTICE_FILE.parent.mkdir(
                        parents=True,
                        exist_ok=True
                    )

                    DATE_NOTICE_FILE.write_text(
                        date_text,
                        encoding="utf-8"
                    )

        print(output)

        box = last_hour(conn, "SmallBoxes", "EndTime")

        if box is not None:
            print(f"Box {box}")


if __name__ == "__main__":
    main()
