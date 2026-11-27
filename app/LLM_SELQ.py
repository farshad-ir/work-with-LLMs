import sys
import json
import argparse
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT_DIR))

from app.mt5_sqlite import (
    _connect,
    _prepare_smallbox_h1_mapping,
)


def run_llm_selq(limit):
    conn = _connect()

    try:
        # Determine the H1 selection window.
        recent_h1 = conn.execute(
            """
            SELECT id, time
            FROM (
                SELECT id, time
                FROM h1Candles
                ORDER BY id DESC
                LIMIT ?
            )
            ORDER BY id ASC
            """,
            (limit,),
        ).fetchall()

        if not recent_h1:
            raise ValueError("No H1 candles are available.")

        window_start = recent_h1[0]["time"]
        window_end = recent_h1[-1]["time"]

        # Prepare SmallBoxes H1 mapping.
        mapping_result = _prepare_smallbox_h1_mapping(
            limit,
            conn=conn,
        )

        conn.commit()

        # Select H1 candles.
        h1_rows = conn.execute(
            """
            SELECT *
            FROM (
                SELECT *
                FROM h1Candles
                ORDER BY id DESC
                LIMIT ?
            )
            ORDER BY id ASC
            """,
            (limit,),
        ).fetchall()

        # Select H6 candles within the same time window.
        h6_rows = conn.execute(
            """
            SELECT *
            FROM h6Candles
            WHERE time >= ?
              AND time <= ?
            ORDER BY id ASC
            """,
            (window_start, window_end),
        ).fetchall()

        # Select only successfully mapped SmallBoxes.
        box_rows = conn.execute(
            """
            SELECT *
            FROM SmallBoxes
            WHERE EndTime >= ?
              AND EndTime <= ?
              AND StartH1ID IS NOT NULL
              AND EndH1ID IS NOT NULL
              AND H1MappingError IS NULL
            ORDER BY id ASC
            """,
            (window_start, window_end),
        ).fetchall()

        # Remove time columns from the LLM data.
        h1_data = [
            {
                key: row[key]
                for key in row.keys()
                if key.lower() != "time"
            }
            for row in h1_rows
        ]

        h6_data = [
            {
                key: row[key]
                for key in row.keys()
                if key.lower() != "time"
            }
            for row in h6_rows
        ]

        boxes_data = [
            {
                key: row[key]
                for key in row.keys()
                if key not in ("StartTime", "EndTime")
            }
            for row in box_rows
        ]

        return {
            "debug": {
                "window_start": window_start,
                "window_end": window_end,
                "mapping": mapping_result,
            },
            "llm_selq": {
                "requested_h1_count": limit,
                "h1_candles": h1_data,
                "h6_candles": h6_data,
                "small_boxes": boxes_data,
            },
        }

    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(
        description="Standalone LLM-SELQ test"
    )

    parser.add_argument(
        "count",
        type=int,
        help="Number of recent H1 candles",
    )

    args = parser.parse_args()

    if args.count < 1:
        parser.error("count must be greater than zero")

    result = run_llm_selq(args.count)

    print(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
