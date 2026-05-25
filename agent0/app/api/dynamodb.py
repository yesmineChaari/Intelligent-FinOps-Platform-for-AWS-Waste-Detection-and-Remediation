from fastapi import APIRouter, HTTPException
from core.db import get_connection

router = APIRouter()


@router.get("/")
def list_dynamodb_tables():
    """List all DynamoDB tables with metadata."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT r.id, r.name, d.region, d.status, d.role,
                       d.environment, d.team, d.read_capacity, d.write_capacity,
                       d.billing_mode, d.launched_at
                FROM resources r
                JOIN dynamodb_instances d ON d.resource_id = r.id
                WHERE r.resource_type = 'dynamodb'
                ORDER BY r.name
            """)
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]


@router.get("/{name}")
def get_dynamodb_table(name: str):
    """Get a single DynamoDB table by name."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT r.id, r.name, d.region, d.status, d.role,
                       d.environment, d.team, d.read_capacity, d.write_capacity,
                       d.billing_mode, d.launched_at
                FROM resources r
                JOIN dynamodb_instances d ON d.resource_id = r.id
                WHERE r.resource_type = 'dynamodb' AND r.name = %s
            """, (name,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail=f"DynamoDB table '{name}' not found")
            cols = [d[0] for d in cur.description]
            return dict(zip(cols, row))


@router.get("/{name}/metrics")
def get_dynamodb_metrics(name: str, limit: int = 100):
    """Get recent DynamoDB metrics."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM resources WHERE name = %s AND resource_type = 'dynamodb'", (name,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail=f"DynamoDB table '{name}' not found")

            cur.execute("""
                SELECT timestamp, read_capacity_units, write_capacity_units,
                       consumed_read_cu, consumed_write_cu, throttled_requests, latency_ms
                FROM dynamodb_metrics
                WHERE resource_id = %s
                ORDER BY timestamp DESC
                LIMIT %s
            """, (row[0], limit))
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]


@router.get("/{name}/metrics/summary")
def get_dynamodb_metrics_summary(name: str):
    """Avg consumed vs provisioned capacity — shows the over-provisioning gap."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM resources WHERE name = %s AND resource_type = 'dynamodb'", (name,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail=f"DynamoDB table '{name}' not found")

            cur.execute("""
                SELECT
                    AVG(read_capacity_units)                         AS provisioned_rcu,
                    AVG(write_capacity_units)                        AS provisioned_wcu,
                    ROUND(AVG(consumed_read_cu)::numeric,  2)        AS avg_consumed_rcu,
                    ROUND(AVG(consumed_write_cu)::numeric, 2)        AS avg_consumed_wcu,
                    ROUND(AVG(throttled_requests)::numeric, 2)       AS avg_throttled,
                    ROUND(AVG(latency_ms)::numeric, 3)               AS avg_latency_ms,
                    COUNT(*)                                          AS datapoint_count,
                    MAX(timestamp)                                    AS latest_metric_at
                FROM dynamodb_metrics
                WHERE resource_id = %s
            """, (row[0],))
            cols = [d[0] for d in cur.description]
            return dict(zip(cols, cur.fetchone()))
