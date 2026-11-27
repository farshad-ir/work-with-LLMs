import json

from app.mt5_sqlite import _connect


def main():
    conn = _connect()

    try:
        rows = conn.execute("""
            SELECT
                sequence,
                role,
                event_type,
                tool_call_id,
                content,
                created_at
            FROM Debate
            ORDER BY sequence ASC
        """).fetchall()

        if not rows:
            print("Debate table is empty.")
            return

        print(f"\nTotal events: {len(rows)}")
        print("=" * 80)

        for row in rows:
            print(f"\nSequence : {row['sequence']}")
            print(f"Role     : {row['role']}")
            print(f"Event    : {row['event_type']}")
            print(f"Tool ID  : {row['tool_call_id']}")
            print(f"Created  : {row['created_at']}")

            content = row["content"]

            try:
                content = json.loads(content)
                content = json.dumps(
                    content,
                    ensure_ascii=False,
                    indent=2
                )
            except (json.JSONDecodeError, TypeError):
                pass

            print("Content:")
            print(content)
            print("-" * 80)

    except Exception as exc:
        print(f"Error reading Debate: {exc}")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
