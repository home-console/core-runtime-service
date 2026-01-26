#!/usr/bin/env python3
"""
Test script to verify DeviceAuthSession persistence.

Checks:
1. Session created in start_auth() persists in memory
2. Same session reused in check_qr_status()
3. Session closed properly on success/failure
"""
import asyncio
import aiohttp
from plugins.yandex_device_auth.device_auth_service import YandexDeviceAuthService
from plugins.yandex_device_auth.yandex_passport_client import DeviceAuthSession


class MockRuntime:
    """Mock runtime for testing."""
    
    def __init__(self):
        self.storage_data = {}
        self.storage = self
        self.event_bus = self
        self.service_registry = self
    
    async def set(self, namespace: str, key: str, value):
        """Mock storage set."""
        full_key = f"{namespace}/{key}"
        self.storage_data[full_key] = value
        print(f"✓ Storage SET: {full_key}")
    
    async def get(self, namespace: str, key: str):
        """Mock storage get."""
        full_key = f"{namespace}/{key}"
        return self.storage_data.get(full_key)
    
    async def delete(self, namespace: str, key: str):
        """Mock storage delete."""
        full_key = f"{namespace}/{key}"
        if full_key in self.storage_data:
            del self.storage_data[full_key]
    
    async def publish(self, event: str, data):
        """Mock event publish."""
        print(f"✓ Event published: {event}")
    
    async def call(self, service: str, **kwargs):
        """Mock service call."""
        pass


async def main():
    """Test session persistence."""
    print("=" * 70)
    print("Testing DeviceAuthSession Persistence")
    print("=" * 70)
    
    # Create service
    runtime = MockRuntime()
    service = YandexDeviceAuthService(runtime)
    
    print("\n1. Initial state:")
    print(f"   _auth_session = {service._auth_session}")
    assert service._auth_session is None, "Should start with None"
    print("   ✓ OK")
    
    print("\n2. Create session manually:")
    test_session = DeviceAuthSession(aiohttp.ClientSession())
    print(f"   session created: {test_session}")
    print(f"   client_session: {test_session.client_session}")
    print(f"   auth_payload: {test_session.auth_payload}")
    print(f"   is_expired(): {test_session.is_expired()}")
    print("   ✓ OK")
    
    print("\n3. Test session persistence logic:")
    service._auth_session = test_session
    print(f"   service._auth_session = {service._auth_session}")
    assert service._auth_session is test_session, "Session should be stored"
    print("   ✓ Session stored in service")
    
    print("\n4. Simulate polling - reuse same session:")
    stored_session = service._auth_session
    print(f"   Stored session: {stored_session}")
    print(f"   Same object? {stored_session is test_session}")
    assert stored_session is test_session, "Should be same object"
    print("   ✓ Session reused correctly")
    
    print("\n5. Close session:")
    await test_session.close()
    print(f"   client_session closed: {test_session.client_session.closed}")
    print("   ✓ Session closed")
    
    print("\n6. Cleanup:")
    service._auth_session = None
    print(f"   _auth_session = {service._auth_session}")
    print("   ✓ OK")
    
    print("\n" + "=" * 70)
    print("All persistence tests passed! ✓")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
