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
    # Bootstrap теперь пустой - все endpoints в модулях
    pass
