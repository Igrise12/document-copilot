from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Header, HTTPException, status
from supabase import AuthApiError, create_async_client

from app.config import settings


@dataclass(frozen=True)
class CurrentUser:
    id: UUID
    email: str


async def current_user(authorization: Annotated[str | None, Header()] = None) -> CurrentUser:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing or invalid bearer token")

    client = await create_async_client(str(settings.supabase_url), settings.supabase_anon_key)
    try:
        response = await client.auth.get_user(authorization.removeprefix("Bearer "))
    except AuthApiError as error:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid bearer token") from error

    user = response.user
    email = user.email.lower() if user and user.email else ""
    if not email:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid bearer token")
    if not email.endswith(f"@{settings.allowed_email_domain}"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "email domain is not allowed")
    return CurrentUser(id=UUID(str(user.id)), email=email)
