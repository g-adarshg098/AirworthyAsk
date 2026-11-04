from contextlib import closing
from decimal import Decimal

import psycopg2
from psycopg2.extras import RealDictCursor


def connect(database_url: str):
    return psycopg2.connect(database_url, connect_timeout=3)


def initialize_usage_table(database_url: str) -> None:
    with closing(connect(database_url)) as conn, conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_usage (
                    request_id UUID PRIMARY KEY,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    model TEXT NOT NULL,
                    input_tokens INTEGER,
                    output_tokens INTEGER,
                    cost_usd NUMERIC(14, 8)
                )
                """
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS chat_usage_created_at_idx ON chat_usage (created_at DESC)"
            )


def record_usage(
    database_url: str,
    request_id: str,
    model: str,
    input_tokens: int | None,
    output_tokens: int | None,
    cost_usd: float | None,
) -> None:
    with closing(connect(database_url)) as conn, conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO chat_usage
                    (request_id, model, input_tokens, output_tokens, cost_usd)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (request_id, model, input_tokens, output_tokens, cost_usd),
            )


def get_usage(database_url: str) -> dict:
    with closing(connect(database_url)) as conn, conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(
            """
            SELECT COUNT(*) AS total_requests,
                   COALESCE(SUM(input_tokens), 0) AS input_tokens,
                   COALESCE(SUM(output_tokens), 0) AS output_tokens,
                   SUM(cost_usd) AS estimated_cost_usd
            FROM chat_usage
            """
        )
        totals = cursor.fetchone()
        cursor.execute(
            """
            SELECT request_id, created_at, model, input_tokens, output_tokens, cost_usd
            FROM chat_usage
            ORDER BY created_at DESC
            LIMIT 100
            """
        )
        recent = cursor.fetchall()

    return {
        "total_requests": totals["total_requests"],
        "input_tokens": totals["input_tokens"],
        "output_tokens": totals["output_tokens"],
        "estimated_cost_usd": (
            float(totals["estimated_cost_usd"])
            if isinstance(totals["estimated_cost_usd"], Decimal)
            else totals["estimated_cost_usd"]
        ),
        "recent": [
            {
                **row,
                "request_id": str(row["request_id"]),
                "created_at": row["created_at"].isoformat(),
                "cost_usd": float(row["cost_usd"]) if row["cost_usd"] is not None else None,
            }
            for row in recent
        ],
    }
