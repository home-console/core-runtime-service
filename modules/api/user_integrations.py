"""
User integrations service.

Provides user-scoped integrations data:
- Currently connected integrations  
- OAuth flow status
- Integration metadata
"""
from typing import Any, List, Dict


async def user_v1_integrations(runtime: Any) -> List[Dict[str, Any]]:
    """Return list of user integrations (currently connected).
    
    This differs from admin.v1.integrations which returns available integrations.
    User integrations track OAuth connections and user-specific state.
    
    Returns:
        List of user's connected integrations
    """
    # User-specific OAuth/integration tracking — placeholder.
    # Future: query user OAuth token storage, provider status, connectedAt, etc.
    # 1. Query user-specific OAuth token storage
    # 2. Get integration status from each provider
    # 3. Return list of {id, provider, status, connectedAt, etc.}
    
    return []
