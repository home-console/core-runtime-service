"""
HTTP Bootstrap Layer — временный слой для HTTP endpoints.

ВАЖНО: Это scaffolding на время рефакторинга.
После C3.1 admin introspection endpoints мигрированы в AdminModule.
Bootstrap слой пока не нужен, т.к. все HTTP endpoints регистрируются
напрямую в модулях через HttpRegistry.
"""

# Temporary bootstrap - currently empty
# All HTTP endpoints now registered directly in modules via HttpRegistry

def register_core_http(runtime):
    """
    Bootstrap регистрация HTTP endpoints.
    
    После C3.1: admin introspection endpoints мигрированы в AdminModule.
    Этот слой оставлен для будущих временных регистраций.
    
    Args:
        runtime: CoreRuntime instance
    """
    # C4: Webhook demo endpoint
    # Демонстрирует webhooks как first-class inbound механизм
    # NOTE: Webhook service регистрация откложена - сервис будет зарегистрирован
    # во время первого вызова через lazy registration pattern
    try:
        from core.http_registry import HttpEndpoint
        
        # Register webhook test endpoint
        runtime.http.register(HttpEndpoint(
            method="POST",
            path="/webhooks/test",
            service="system.webhook_test",
            description="Webhook test endpoint - demonstrates webhook mechanism",
            kind="webhook"
        ))
        
        import logging
        logging.info("C4: Webhook demo endpoint registered at POST /webhooks/test")
        # NOTE: Service registration is lazy - will be done by ApiModule during startup
    
    except Exception as e:
        import logging
        logging.warning(f"Failed to register webhook demo endpoint: {str(e)}")

