import os
from pathlib import Path

import psycopg

from dotenv import load_dotenv

import pandas as pd

project_root = Path(__file__).resolve().parents[2]
load_dotenv(project_root / ".env")


def get_connection():
    """Return a secure connection to the Neon PostgreSQL database."""

    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        raise ValueError(
            "DATABASE_URL is missing. Add the Neon connection string to your .env file."
        )

    return psycopg.connect(database_url)


def _query(sql_text, params=None):
    """Run a SELECT and return the result as a DataFrame."""
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql_text, params)
            rows = cursor.fetchall()
            column_names = [column.name for column in cursor.description]

    return pd.DataFrame(rows, columns=column_names)


def fetch_all():
    """Retrieve every row from the robot_readings table as a pandas DataFrame."""
    return _query("SELECT * FROM robot_readings ORDER BY reading_time")


def fetch_since(last_ts):
    """Rows newer than last_ts, for the dashboard's polling loop.

    Passing None returns the whole table, so a caller can use this for its
    first poll without special-casing the start.
    """
    if last_ts is None:
        return fetch_all()

    return _query(
        "SELECT * FROM robot_readings WHERE reading_time > %s ORDER BY reading_time",
        (last_ts,),
    )


def insert_reading(record: dict):
    """Insert one reading. Keys must match the column names: trait, axis_1..axis_8, reading_time."""
    values = (
        record["trait"],
        *(record[f"axis_{i}"] for i in range(1, 9)),
        record["reading_time"],
    )
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """INSERT INTO robot_readings
                       (trait, axis_1, axis_2, axis_3, axis_4,
                        axis_5, axis_6, axis_7, axis_8, reading_time)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                values,
            )
        connection.commit()
