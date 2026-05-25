from fastapi import APIRouter, HTTPException
from core.db import get_connection

router = APIRouter()


@router.get("/")
def list_all_relationships():
    """List all resource relationships across the infrastructure."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    rr.id,
                    r1.name              AS resource_name,
                    r1.resource_type     AS resource_type,
                    rr.relationship_type,
                    r2.name              AS related_resource_name,
                    r2.resource_type     AS related_resource_type,
                    rr.confidence_score,
                    rr.created_at
                FROM resource_relationships rr
                JOIN resources r1 ON r1.id = rr.resource_id
                JOIN resources r2 ON r2.id = rr.related_resource_id
                ORDER BY r1.name, rr.relationship_type
            """)
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]


@router.get("/{name}")
def get_resource_relationships(name: str):
    """
    Get all relationships for a resource — outbound (this → other)
    and inbound (other → this).
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM resources WHERE name = %s", (name,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail=f"Resource '{name}' not found")
            resource_id = row[0]

            cur.execute("""
                SELECT rr.relationship_type, r2.name AS target_name,
                       r2.resource_type AS target_type, rr.confidence_score
                FROM resource_relationships rr
                JOIN resources r2 ON r2.id = rr.related_resource_id
                WHERE rr.resource_id = %s
                ORDER BY rr.relationship_type
            """, (resource_id,))
            cols     = [d[0] for d in cur.description]
            outbound = [dict(zip(cols, r)) for r in cur.fetchall()]

            cur.execute("""
                SELECT rr.relationship_type, r1.name AS source_name,
                       r1.resource_type AS source_type, rr.confidence_score
                FROM resource_relationships rr
                JOIN resources r1 ON r1.id = rr.resource_id
                WHERE rr.related_resource_id = %s
                ORDER BY rr.relationship_type
            """, (resource_id,))
            cols    = [d[0] for d in cur.description]
            inbound = [dict(zip(cols, r)) for r in cur.fetchall()]

            return {"resource": name, "outbound": outbound, "inbound": inbound}
