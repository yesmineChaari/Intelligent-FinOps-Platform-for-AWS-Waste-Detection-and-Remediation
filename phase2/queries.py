import asyncpg

from phase2.models import RelationshipEdge


async def load_local_relationships(
    conn: asyncpg.Connection,
    flagged_ids: list[int],
) -> list[RelationshipEdge]:
    """Load all local relationships touching flagged instances in one query."""
    if not flagged_ids:
        return []

    sql = """
        WITH flagged AS (
          SELECT UNNEST($1::bigint[]) AS instance_id
        ),
        relationships AS (
          SELECT
            rr.resource_id,
            rr.related_resource_id,
            rr.relationship_type::text AS relationship_type,
            related.resource_type::text AS related_resource_type
          FROM resource_relationships rr
          LEFT JOIN resources related ON related.id = rr.related_resource_id
          WHERE rr.resource_id IN (SELECT instance_id FROM flagged)
             OR rr.related_resource_id IN (SELECT instance_id FROM flagged)
        )
        SELECT *
        FROM relationships
    """

    rows = await conn.fetch(sql, flagged_ids)
    return [RelationshipEdge(**dict(row)) for row in rows]
