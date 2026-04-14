# These relationship_type_enum values are required by Phase 2 guardrails.
# Apply migrations/add_relationship_types.sql before running this code.

import asyncpg


async def check_type_e_redundancy(conn: asyncpg.Connection, resource_id: int) -> bool:
    sql = """
        SELECT EXISTS (
          SELECT 1
          FROM resource_relationships rr
          JOIN ec2_instances e ON e.resource_id = rr.resource_id
          WHERE rr.related_resource_id = $1
            AND rr.relationship_type IN (
              'replicates_to', 'failover_for', 'backup_of'
            )
            AND e.status = 'active'
        )
    """
    return bool(await conn.fetchval(sql, resource_id))


async def get_upstream_callers(
    conn: asyncpg.Connection,
    resource_id: int,
    max_depth: int = 3,
) -> list[dict]:
    sql = """
        WITH RECURSIVE upstream AS (
          SELECT
            rr.resource_id        AS source_id,
            rr.relationship_type  AS relationship_type,
            1                     AS depth
          FROM resource_relationships rr
          JOIN ec2_instances e ON e.resource_id = rr.resource_id
          WHERE rr.related_resource_id = $1
            AND rr.relationship_type NOT IN ('sends_logs_to', 'monitored_by')
            AND e.status = 'active'

          UNION ALL

          SELECT
            rr.resource_id,
            rr.relationship_type,
            u.depth + 1
          FROM resource_relationships rr
          JOIN ec2_instances e ON e.resource_id = rr.resource_id
          JOIN upstream u ON rr.related_resource_id = u.source_id
          WHERE rr.relationship_type NOT IN ('sends_logs_to', 'monitored_by')
            AND e.status = 'active'
            AND u.depth < $2
        )
        SELECT DISTINCT
          source_id,
          relationship_type::text,
          MIN(depth) AS depth
        FROM upstream
        GROUP BY source_id, relationship_type
        ORDER BY depth ASC
    """
    rows = await conn.fetch(sql, resource_id, max_depth)
    return [dict(row) for row in rows]


async def count_active_lb_targets(conn: asyncpg.Connection, lb_resource_id: int) -> int:
    sql = """
        SELECT COUNT(DISTINCT rr.related_resource_id)
        FROM resource_relationships rr
        JOIN ec2_instances e ON e.resource_id = rr.related_resource_id
        WHERE rr.resource_id = $1
          AND rr.relationship_type IN ('routes_traffic_to', 'load_balances_to')
          AND e.status = 'active'
          AND rr.related_resource_id != $1
    """
    value = await conn.fetchval(sql, lb_resource_id)
    return int(value or 0)


async def write_waste_rows(conn: asyncpg.Connection, rows: list[dict]) -> None:
    insert_sql = """
        INSERT INTO waste (
          resource_id,
          waste_type,
          detection_window,
          avg_cpu,
          peak_cpu,
          avg_ram,
          current_instance_type,
          recommended_type,
          current_cost_per_hour,
          recommended_cost_per_hour,
          waste_per_hour,
          waste_per_month,
          action,
          safety_status,
          block_reason,
          pipeline_warning,
          redundancy_node,
          depth_of_block,
          calculated_at
        ) VALUES (
          $1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
          NULL, $11, $12, $13, $14, $15, $16, $17, NOW()
        )
        ON CONFLICT (resource_id, waste_type)
        DO UPDATE SET
          detection_window = EXCLUDED.detection_window,
          avg_cpu = EXCLUDED.avg_cpu,
          peak_cpu = EXCLUDED.peak_cpu,
          avg_ram = EXCLUDED.avg_ram,
          current_instance_type = EXCLUDED.current_instance_type,
          recommended_type = EXCLUDED.recommended_type,
          current_cost_per_hour = EXCLUDED.current_cost_per_hour,
          recommended_cost_per_hour = EXCLUDED.recommended_cost_per_hour,
          waste_per_month = EXCLUDED.waste_per_month,
          action = EXCLUDED.action,
          safety_status = EXCLUDED.safety_status,
          block_reason = EXCLUDED.block_reason,
          pipeline_warning = EXCLUDED.pipeline_warning,
          redundancy_node = EXCLUDED.redundancy_node,
          depth_of_block = EXCLUDED.depth_of_block,
          calculated_at = NOW()
    """

    tuples = [
        (
            row["resource_id"],
            row["waste_type"],
            str(row["detection_window"]) if row["detection_window"] is not None else '0',
            row["avg_cpu"],
            row["peak_cpu"],
            row["avg_ram"],
            row["current_instance_type"],
            row["recommended_type"],
            row["current_cost_per_hour"],
            row["recommended_cost_per_hour"],
            row["waste_per_month"],
            row["action"],
            row["safety_status"],
            row["block_reason"],
            row["pipeline_warning"],
            row["redundancy_node"],
            row["depth_of_block"],
        )
        for row in rows
    ]

    async with conn.transaction():
        await conn.executemany(insert_sql, tuples)
