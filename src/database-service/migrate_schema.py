"""One-off migration: rebuild robot_readings with an explicit schema.

Run one step at a time, checking the output before moving on:

    python src/database-service/migrate_schema.py create
    python src/database-service/migrate_schema.py load
    python src/database-service/migrate_schema.py verify
    python src/database-service/migrate_schema.py swap
"""

import os
import sys
from pathlib import Path

import pandas as pd
import psycopg
from dotenv import load_dotenv
from sqlalchemy import create_engine

project_root = Path(__file__).resolve().parents[2]
load_dotenv(project_root / ".env")

CSV_PATH = project_root / "data" / "RMBR4-2_export_test.csv"
AXES = range(1, 9)

DDL = """
CREATE TABLE IF NOT EXISTS robot_readings_new (
    id           SERIAL PRIMARY KEY,
    trait        TEXT NOT NULL,
    axis_1       DOUBLE PRECISION,
    axis_2       DOUBLE PRECISION,
    axis_3       DOUBLE PRECISION,
    axis_4       DOUBLE PRECISION,
    axis_5       DOUBLE PRECISION,
    axis_6       DOUBLE PRECISION,
    axis_7       DOUBLE PRECISION,
    axis_8       DOUBLE PRECISION,
    reading_time TIMESTAMPTZ NOT NULL,
    inserted_at  TIMESTAMPTZ DEFAULT now()
);
"""


def database_url():
    url = os.getenv("DATABASE_URL")
    if not url:
        raise ValueError("DATABASE_URL is missing. Add it to your .env file.")
    return url


def create():
    with psycopg.connect(database_url()) as conn:
        conn.execute(DDL)
        conn.commit()
    print("robot_readings_new created.")


def load():
    df = pd.read_csv(CSV_PATH)
    df = df[["Trait", *[f"Axis #{i}" for i in AXES], "Time"]]
    df = df.rename(
        columns={
            "Trait": "trait",
            "Time": "reading_time",
            **{f"Axis #{i}": f"axis_{i}" for i in AXES},
        }
    )
    df["reading_time"] = pd.to_datetime(df["reading_time"], utc=True)

    engine = create_engine(database_url().replace("postgresql://", "postgresql+psycopg://", 1))
    df.to_sql(
        "robot_readings_new",
        engine,
        if_exists="append",
        index=False,
        chunksize=1000,
        method="multi",
    )
    print(f"loaded {len(df):,} rows")


def verify():
    with psycopg.connect(database_url()) as conn:
        old = conn.execute("SELECT count(*) FROM robot_readings").fetchone()[0]
        new = conn.execute("SELECT count(*) FROM robot_readings_new").fetchone()[0]
        span = conn.execute(
            "SELECT min(reading_time), max(reading_time) FROM robot_readings_new"
        ).fetchone()
        nulls = conn.execute(
            "SELECT count(*) FROM robot_readings_new WHERE reading_time IS NULL"
        ).fetchone()[0]

    print(f"old table rows : {old:,}")
    print(f"new table rows : {new:,}")
    print(f"time span      : {span[0]} -> {span[1]}")
    print(f"null timestamps: {nulls}")
    print("MATCH" if old == new and nulls == 0 else "MISMATCH - do not swap")


def swap():
    with psycopg.connect(database_url()) as conn:
        conn.execute("ALTER TABLE robot_readings RENAME TO robot_readings_old")
        conn.execute("ALTER TABLE robot_readings_new RENAME TO robot_readings")
        conn.commit()
    print("swapped. old table kept as robot_readings_old")


STEPS = {"create": create, "load": load, "verify": verify, "swap": swap}

if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in STEPS:
        sys.exit(f"usage: {sys.argv[0]} [{'|'.join(STEPS)}]")
    STEPS[sys.argv[1]]()
