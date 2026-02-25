"""
Тесты для Network Scanner плагина.
"""

import pytest
from plugins.network_scanner.plugin import NetworkScannerPlugin
from plugins.network_scanner.scanner import NetworkScanner, NetworkHost


class TestNetworkHost:
    """Тесты для NetworkHost dataclass."""
    
    def test_network_host_creation(self):
        """Тест создания объекта NetworkHost."""
        host = NetworkHost(
            ip_address="192.168.1.100",
            hostname="test.local",
            is_online=True
        )
        
        assert host.ip_address == "192.168.1.100"
        assert host.hostname == "test.local"
        assert host.is_online is True
        assert host.open_ports == []
        assert host.services == []
        assert host.last_seen is not None

    def test_network_host_to_dict(self):
        """Тест преобразования NetworkHost в словарь."""
        host = NetworkHost(
            ip_address="192.168.1.100",
            hostname="test.local",
            is_online=True
        )
        
        host_dict = host.to_dict()
        assert host_dict["ip_address"] == "192.168.1.100"
        assert host_dict["hostname"] == "test.local"
        assert host_dict["is_online"] is True


class TestNetworkScanner:
    """Тесты для NetworkScanner."""
    
    def test_scanner_initialization(self):
        """Тест инициализации сканера."""
        scanner = NetworkScanner()
        assert scanner.discovered_hosts == {}
        assert len(scanner.get_discovered_hosts()) == 0

    async def test_discovery_hosts_cache(self):
        """Тест кэширования обнаруженных хостов."""
        scanner = NetworkScanner()
        
        # Добавляем хост в кэш
        host = NetworkHost(ip_address="192.168.1.100")
        scanner.discovered_hosts["192.168.1.100"] = host
        
        # Проверяем что можем получить хост
        discovered = scanner.get_discovered_hosts()
        assert len(discovered) == 1
        assert discovered[0].ip_address == "192.168.1.100"

    async def test_clear_cache(self):
        """Тест очистки кэша."""
        scanner = NetworkScanner()
        
        # Добавляем хосты
        scanner.discovered_hosts["192.168.1.100"] = NetworkHost(ip_address="192.168.1.100")
        scanner.discovered_hosts["192.168.1.101"] = NetworkHost(ip_address="192.168.1.101")
        
        assert len(scanner.get_discovered_hosts()) == 2
        
        # Очищаем кэш
        scanner.clear_discovered_hosts()
        assert len(scanner.get_discovered_hosts()) == 0


class TestNetworkScannerPlugin:
    """Тесты для NetworkScannerPlugin."""
    
    def test_plugin_metadata(self):
        """Тест метаданных плагина."""
        plugin = NetworkScannerPlugin()
        metadata = plugin.metadata
        
        assert metadata.name == "network_scanner"
        assert metadata.version == "0.1.0"
        assert metadata.author == "Home Console"
        assert metadata.capabilities_required == []

    def test_plugin_name(self):
        """Тест имени плагина."""
        plugin = NetworkScannerPlugin()
        assert plugin.metadata.name == "network_scanner"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
