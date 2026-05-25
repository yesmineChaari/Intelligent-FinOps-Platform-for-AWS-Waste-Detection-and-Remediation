from fastapi import APIRouter, HTTPException
from core.db import get_connection

router = APIRouter()


@router.get("/")
def list_ec2_instances():
    """List all EC2 instances with metadata."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT r.id, r.name, e.instance_type, e.region, e.status,
                       e.role, e.environment, e.team, e.os, e.launched_at
                FROM resources r
                JOIN ec2_instances e ON e.resource_id = r.id
                WHERE r.resource_type = 'ec2'
                ORDER BY r.name
            """)
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]


@router.get("/{name}")
def get_ec2_instance(name: str):
    """Get a single EC2 instance by name."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT r.id, r.name, e.instance_type, e.region, e.status,
                       e.role, e.environment, e.team, e.os, e.launched_at
                FROM resources r
                JOIN ec2_instances e ON e.resource_id = r.id
                WHERE r.resource_type = 'ec2' AND r.name = %s
            """, (name,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail=f"EC2 instance '{name}' not found")
            cols = [d[0] for d in cur.description]
            return dict(zip(cols, row))


@router.get("/{name}/metrics")
def get_ec2_metrics(name: str, limit: int = 100):
    """Get recent metrics for an EC2 instance."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM resources WHERE name = %s AND resource_type = 'ec2'", (name,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail=f"EC2 instance '{name}' not found")

            cur.execute("""
                SELECT timestamp, cpu_pct, ram_pct, network_in, network_out, disk_read, disk_write
                FROM ec2_metrics
                WHERE resource_id = %s
                ORDER BY timestamp DESC
                LIMIT %s
            """, (row[0], limit))
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]


@router.get("/{name}/metrics/summary")
def get_ec2_metrics_summary(name: str):
    """Avg and p95 CPU/RAM over full metric history."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM resources WHERE name = %s AND resource_type = 'ec2'", (name,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail=f"EC2 instance '{name}' not found")

            cur.execute("""
                SELECT
                    ROUND(AVG(cpu_pct)::numeric, 2)                                              AS avg_cpu,
                    ROUND(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY cpu_pct)::numeric, 2)     AS p95_cpu,
                    ROUND(AVG(ram_pct)::numeric, 2)                                              AS avg_ram,
                    COUNT(*)                                                                      AS datapoint_count,
                    MAX(timestamp)                                                                AS latest_metric_at
                FROM ec2_metrics
                WHERE resource_id = %s
            """, (row[0],))
            cols = [d[0] for d in cur.description]
            return dict(zip(cols, cur.fetchone()))
