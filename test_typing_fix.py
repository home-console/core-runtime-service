#!/usr/bin/env python3
"""Quick test to verify runtime typing and plugin loading."""

import asyncio
import pytest
from pathlib import Path
from config import Config
from core.runtime import CoreRuntime
from adapters.sqlite_adapter import SQLiteAdapter
from plugins.system_logger_plugin import SystemLoggerPlugin
from plugins.automation_plugin import AutomationPlugin


@pytest.mark.asyncio
async def test():
    config = Config(db_path=':memory:')
    adapter = SQLiteAdapter(':memory:')
    await adapter.initialize_schema()
    
    runtime = CoreRuntime(adapter)
    logger = SystemLoggerPlugin()
    automation = AutomationPlugin()
    
    # Загружаем плагины
    await runtime.plugin_manager.load_plugin(logger)
    print('✓ Logger plugin loaded successfully')
    print(f'  logger.runtime type: {type(logger.runtime).__name__}')
    
    await runtime.plugin_manager.load_plugin(automation)
    print('✓ Automation plugin loaded successfully')
    print(f'  automation.runtime type: {type(automation.runtime).__name__}')
    
    await runtime.start()
    print('✓ Runtime started')
    
    # Пытаемся использовать runtime через плагины
    try:
        await runtime.service_registry.call('logger.log', level='info', message='Test message')
        print('✓ Logger service call successful')
    except Exception as e:
        print(f'✗ Logger service call failed: {e}')
    
    await runtime.shutdown()
    print('✓ Runtime shutdown')


if __name__ == '__main__':
    asyncio.run(test())
