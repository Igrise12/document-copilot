from typing import Any
from uuid import UUID, uuid4

import structlog

from app.supabase import async_service_role_client

PUBLIC_COLUMNS = "id,event_type,resource_id,label,created_at"
logger = structlog.get_logger()


async def record_activity(
    owner_id: UUID,
    event_type: str,
    label: str,
    resource_id: UUID | None = None,
) -> None:
    try:
        client = await async_service_role_client()
        await client.table("activity_events").insert(
            {
                "id": str(uuid4()),
                "owner_id": str(owner_id),
                "event_type": event_type,
                "resource_id": str(resource_id) if resource_id else None,
                "label": label,
            }
        ).execute()
    except Exception:
        logger.exception("activity_event_recording_failed", event_type=event_type, owner_id=str(owner_id))


async def list_activity(owner_id: UUID, limit: int) -> list[dict[str, Any]]:
    client = await async_service_role_client()
    response = await (
        client.table("activity_events")
        .select(PUBLIC_COLUMNS)
        .eq("owner_id", str(owner_id))
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return response.data
