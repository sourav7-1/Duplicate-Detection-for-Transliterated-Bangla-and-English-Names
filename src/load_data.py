"""Load data/names.csv and data/gold_pairs.csv into PostgreSQL with COPY.

Replaces existing data: person, name_record and gold_pair are truncated first
(CASCADE also clears name_token and match_result, which reference old records).
All of it runs in one transaction, so a failed load leaves the old data intact.

Usage: python src/load_data.py
"""
import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


def connect():
    load_dotenv(ROOT / ".env")
    return psycopg.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        # Fail fast instead of hanging when the server is unreachable. Applies per
        # address, so "localhost" (::1 then 127.0.0.1) can take up to ~6 s to fail.
        connect_timeout=3,
    )


def copy_csv(cur, sql, path):
    with cur.copy(sql) as copy, open(path, "rb") as f:
        while chunk := f.read(1 << 16):
            copy.write(chunk)


def main():
    with connect() as conn, conn.cursor() as cur:
        cur.execute("TRUNCATE gold_pair, person, name_record CASCADE")

        # names.csv has one row per record; person rows are derived from it.
        cur.execute("""
            CREATE TEMP TABLE staging_names (
                record_id INTEGER, person_id INTEGER, full_name TEXT, variant_type TEXT
            ) ON COMMIT DROP
        """)
        copy_csv(cur, "COPY staging_names FROM STDIN (FORMAT csv, HEADER true)",
                 DATA / "names.csv")
        cur.execute("""
            INSERT INTO person (person_id, canonical_name, is_hard_negative)
            SELECT person_id, full_name, variant_type = 'hard_negative'
            FROM staging_names
            WHERE variant_type IN ('original', 'hard_negative')
        """)
        cur.execute("""
            INSERT INTO name_record (record_id, person_id, full_name, variant_type)
            SELECT record_id, person_id, full_name, variant_type FROM staging_names
        """)

        copy_csv(cur, "COPY gold_pair (record_id_a, record_id_b, is_duplicate) "
                      "FROM STDIN (FORMAT csv, HEADER true)",
                 DATA / "gold_pairs.csv")

        for table in ("person", "name_record", "gold_pair"):
            cur.execute(f"SELECT count(*) FROM {table}")
            print(f"{table:<12} {cur.fetchone()[0]:>7} rows")
        cur.execute("SELECT count(*) FILTER (WHERE is_duplicate), "
                    "count(*) FILTER (WHERE NOT is_duplicate) FROM gold_pair")
        dup, non = cur.fetchone()
        print(f"  duplicate pairs {dup}, non-duplicate pairs {non}")


if __name__ == "__main__":
    main()
