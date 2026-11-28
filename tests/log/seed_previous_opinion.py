import sys
import json
from pathlib import Path
from datetime import datetime, timezone

ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT_DIR))

from app.mt5_sqlite import _connect, DB_PATH


LOG_PATH = ROOT_DIR / "tests" / "log" / "The_first_Debate.log"
H1_ID = 72


def read_final_result():
    text = LOG_PATH.read_text(encoding="utf-8")

    event_marker = "Event    : FINAL_RESULT"
    event_index = text.rfind(event_marker)

    if event_index < 0:
        raise ValueError("FINAL_RESULT event was not found.")

    content_marker = "Content:\n"
    content_index = text.find(content_marker, event_index)

    if content_index < 0:
        raise ValueError("FINAL_RESULT content was not found.")

    content_start = content_index + len(content_marker)
    content_end = text.find("\n--------------------------------", content_start)

    if content_end < 0:
        raise ValueError("FINAL_RESULT ending separator was not found.")

    result = text[content_start:content_end].strip()

    if not result:
        raise ValueError("FINAL_RESULT is empty.")

    return result


def main():
    if not LOG_PATH.is_file():
        raise FileNotFoundError(f"Debate log not found: {LOG_PATH}")

    if not DB_PATH.is_file():
        raise FileNotFoundError(
            f"SQLite database does not exist: {DB_PATH}"
        )

    final_result = read_final_result()

    conn = _connect()

    try:
        conn.execute("BEGIN IMMEDIATE")

        tables = {
            row["name"]
            for row in conn.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                """
            ).fetchall()
        }

        if "h1Candles" not in tables or "Opinions" not in tables:
            raise ValueError(
                "Required tables h1Candles or Opinions do not exist."
            )

        h1 = conn.execute(
            """
            SELECT id, symbol
            FROM h1Candles
            WHERE id = ?
            """,
            (H1_ID,),
        ).fetchone()

        if h1 is None:
            raise ValueError(
                f"H1 candle ID {H1_ID} does not exist."
            )

        if not h1["symbol"]:
            raise ValueError(
                f"H1 candle ID {H1_ID} has no symbol."
            )

        opinion_columns = {
            row["name"]
            for row in conn.execute(
                "PRAGMA table_info('Opinions')"
            ).fetchall()
        }

        required_columns = {
            "created_at",
            "symbol",
            "timeframe",
            "candle_reference",
            "opinion",
        }

        missing = required_columns - opinion_columns

        if missing:
            raise ValueError(
                f"Opinions table is missing columns: {sorted(missing)}"
            )

        existing = conn.execute(
            """
            SELECT id
            FROM Opinions
            WHERE timeframe = ?
              AND candle_reference = ?
              AND opinion = ?
            LIMIT 1
            """,
            ("H1", str(H1_ID), final_result),
        ).fetchone()

        if existing is not None:
            conn.rollback()
            print(
                "This exact opinion is already registered.",
                f"Opinion row ID: {existing['id']}",
            )
            return

        cursor = conn.execute(
            """
            INSERT INTO Opinions (
                created_at,
                symbol,
                timeframe,
                candle_reference,
                opinion
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                datetime.now(timezone.utc).isoformat(),
                h1["symbol"],
                "H1",
                str(H1_ID),
                final_result,
            ),
        )

        opinion_row_id = cursor.lastrowid

        saved = conn.execute(
            """
            SELECT *
            FROM Opinions
            WHERE id = ?
            """,
            (opinion_row_id,),
        ).fetchone()

        conn.commit()

        print("Opinion successfully registered.")
        print(json.dumps(dict(saved), ensure_ascii=False, indent=2))

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()


if __name__ == "__main__":
    main()
