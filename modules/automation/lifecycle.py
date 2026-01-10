"""
Lifecycle hooks для automation модуля.

on_start/on_stop вызываются из CoreRuntime при старте/остановке.
"""


async def on_start(runtime) -> None:
    """
    Вызывается при старте runtime.

    В текущей реализации automation не требует инициализации при старте,
    так как подписка на события происходит в register_automation().

    Args:
        runtime: экземпляр CoreRuntime
    """
    # Automation модуль не требует специальной инициализации при старте
    # Все подписки уже установлены в register_automation()
    pass


async def on_stop(runtime) -> None:
    """
    Вызывается при остановке runtime.

    В текущей реализации отписка от событий происходит через unregister(),
    который вызывается из CoreRuntime.shutdown().

    Args:
        runtime: экземпляр CoreRuntime
    """
    # Отписка от событий происходит через unregister() в __init__.py
    # Этот hook оставлен для будущего расширения, если потребуется
    # дополнительная логика при остановке
    pass
