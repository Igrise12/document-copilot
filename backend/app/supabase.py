from supabase import Client, ClientOptions, create_client

from app.config import settings


def create_user_client(access_token: str) -> Client:
    return create_client(
        str(settings.supabase_url),
        settings.supabase_anon_key,
        options=ClientOptions(headers={"Authorization": f"Bearer {access_token}"}),
    )


def service_role_client() -> Client:
    return create_client(str(settings.supabase_url), settings.supabase_service_role_key)
