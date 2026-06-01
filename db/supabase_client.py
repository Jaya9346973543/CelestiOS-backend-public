from supabase import create_client, Client
from typing import Optional
from core.config import settings

def get_supabase() -> Optional[Client]:
    # If the URL and key are missing, skip client creation.
    if not settings.SUPABASE_URL or not settings.SUPABASE_KEY:
        print("WARNING: Supabase URL or Key is not configured. Database operations will fail.")
        return None
        
    url: str = settings.SUPABASE_URL
    key: str = settings.SUPABASE_KEY
    supabase: Client = create_client(url, key)
    return supabase

supabase_client = get_supabase()
