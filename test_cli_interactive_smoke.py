"""
Smoke-test для интерактивного CLI.

Тест импортирует `console.run_cli` и симулирует ввод, выбирает '/presence/enter', подтверждает
и проверяет, что состояние `presence.home` изменилось.
"""

import asyncio

from config import Config
from core.runtime import CoreRuntime
from adapters.sqlite_adapter import SQLiteAdapter
import console


class InputSimulator:
    def __init__(self, answers):
        self._answers = answers
        self._i = 0

    def __call__(self, prompt: str = ""):
        if self._i >= len(self._answers):
            raise RuntimeError("No more simulated inputs")
        ans = self._answers[self._i]
        self._i += 1
        print(prompt + ans)
        return ans


async def test_cli_interactive():
    # Подготовка: указываем тестовую БД
    Config._overrides = {"db_path": "data/test_cli.db"}

    # Список ответов для интерактивного сеанса:
    # 1) выбираем по пути '/presence/enter'
    # 2) подтверждаем 'y'
    simulator = InputSimulator(["/presence/enter", "y"])

    runtime = await console.run_cli(argv=None, input_func=simulator, shutdown_on_exit=False)

    # После вызова ожидаем, что состояние установлено в True
    cur = await runtime.state_engine.get("presence.home")
    print("presence.home after CLI:", cur)
    assert cur is True

    # Очистка
    await runtime.shutdown()


if __name__ == '__main__':
    asyncio.run(test_cli_interactive())
