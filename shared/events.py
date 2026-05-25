from __future__ import annotations


INGESTION_STREAM = "ingestion_stream"
OPTIMIZATION_STREAM = "optimization_stream"
EVENT_INGESTION_COMPLETE = "ingestion_complete"
EVENT_DETERMINISTIC_COMPLETE = "deterministic_complete"
EVENT_PHASE3_COMPLETE = "phase3_complete"
EVENT_PHASE3_FAILED = "phase3_failed"


def _as_text(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return str(value)


def decode_stream_fields(fields: dict) -> dict[str, str]:
    return {_as_text(key): _as_text(value) for key, value in fields.items()}


def build_deterministic_complete_payload(
    run_id: int,
    workspace_key: str | None = None,
    terraform_repo_url: str | None = None,
    terraform_ref: str | None = None,
    terraform_subdir: str | None = None,
) -> dict[str, str]:
    values: dict[str, object | None] = {
        "run_id": run_id,
        "workspace_key": workspace_key,
        "terraform_repo_url": terraform_repo_url,
        "terraform_ref": terraform_ref,
        "terraform_subdir": terraform_subdir,
    }
    return {key: str(value) for key, value in values.items() if value is not None}


async def wait_for_event(
    redis_client,
    stream_name: str,
    event_name: str,
    *,
    block_ms: int = 0,
    count: int = 1,
) -> dict[str, str]:
    last_id: str | bytes = "$"
    while True:
        messages = await redis_client.xread(
            {stream_name: last_id},
            block=block_ms,
            count=count,
        )
        for _stream, entries in messages:
            for entry_id, fields in entries:
                last_id = entry_id
                decoded = decode_stream_fields(fields)
                if decoded.get("event") == event_name:
                    return decoded


async def publish_event(
    redis_client,
    stream_name: str,
    event_name: str,
    payload: dict[str, object] | None = None,
) -> str:
    fields = {
        key: str(value)
        for key, value in (payload or {}).items()
        if value is not None
    }
    fields["event"] = event_name
    entry_id = await redis_client.xadd(stream_name, fields)
    return _as_text(entry_id)
