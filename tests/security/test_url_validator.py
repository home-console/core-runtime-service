"""
Тесты для URL validator (SSRF protection).
"""

import pytest
from modules.api.security.url_validator import (
    validate_external_url,
    validate_url_for_plugin,
    is_private_ip,
    is_allowed_scheme,
)
from core.exceptions import BadRequestError


class TestIsPrivateIp:
    """Тесты для проверки приватных IP адресов."""
    
    def test_localhost_string(self):
        """localhost должен быть приватным."""
        assert is_private_ip("localhost") is True
    
    def test_127_0_0_1(self):
        """127.0.0.1 должен быть приватным."""
        assert is_private_ip("127.0.0.1") is True
    
    def test_ipv6_loopback(self):
        """::1 должен быть приватным."""
        assert is_private_ip("::1") is True
    
    def test_private_range_10(self):
        """10.x.x.x диапазон приватный."""
        assert is_private_ip("10.0.0.1") is True
        assert is_private_ip("10.255.255.255") is True
    
    def test_private_range_172(self):
        """172.16-31.x.x диапазон приватный."""
        assert is_private_ip("172.16.0.1") is True
        assert is_private_ip("172.31.255.255") is True
    
    def test_private_range_192(self):
        """192.168.x.x диапазон приватный."""
        assert is_private_ip("192.168.0.1") is True
        assert is_private_ip("192.168.255.255") is True
    
    def test_link_local_range(self):
        """169.254.x.x (link-local) приватный."""
        assert is_private_ip("169.254.0.1") is True
    
    def test_public_ip(self):
        """Публичный IP не должен быть приватным."""
        assert is_private_ip("8.8.8.8") is False
        assert is_private_ip("1.1.1.1") is False


class TestIsAllowedScheme:
    """Тесты для проверки разрешённых схем URL."""
    
    def test_http_scheme_allowed(self):
        """http:// должен быть разрешён."""
        assert is_allowed_scheme("http://example.com") is True
    
    def test_https_scheme_allowed(self):
        """https:// должен быть разрешён."""
        assert is_allowed_scheme("https://example.com") is True
    
    def test_file_scheme_not_allowed(self):
        """file:// должен быть запрещён."""
        assert is_allowed_scheme("file:///etc/passwd") is False
    
    def test_ftp_scheme_not_allowed(self):
        """ftp:// должен быть запрещён."""
        assert is_allowed_scheme("ftp://example.com") is False
    
    def test_gopher_scheme_not_allowed(self):
        """gopher:// должен быть запрещён."""
        assert is_allowed_scheme("gopher://example.com") is False
    
    def test_telnet_scheme_not_allowed(self):
        """telnet:// должен быть запрещён."""
        assert is_allowed_scheme("telnet://example.com") is False
    
    def test_case_insensitive(self):
        """Проверка должна быть case-insensitive."""
        assert is_allowed_scheme("HTTP://example.com") is True
        assert is_allowed_scheme("HTTPS://example.com") is True
        assert is_allowed_scheme("FILE:///etc/passwd") is False


class TestValidateExternalUrl:
    """Тесты для основного валидатора URL."""
    
    def test_valid_https_url(self):
        """Обычный HTTPS URL должен быть валиден."""
        assert validate_external_url("https://api.example.com/data") is True
    
    def test_valid_http_url(self):
        """Обычный HTTP URL должен быть валиден."""
        assert validate_external_url("http://api.example.com/data") is True
    
    def test_localhost_url_fails(self):
        """localhost URL должен быть запрещён по умолчанию."""
        with pytest.raises(BadRequestError):
            validate_external_url("http://localhost:8080")
    
    def test_127_0_0_1_url_fails(self):
        """127.0.0.1 URL должен быть запрещён по умолчанию."""
        with pytest.raises(BadRequestError):
            validate_external_url("http://127.0.0.1:5000")
    
    def test_private_ip_url_fails(self):
        """Приватный IP URL должен быть запрещён по умолчанию."""
        with pytest.raises(BadRequestError):
            validate_external_url("http://192.168.1.1")
    
    def test_file_url_fails(self):
        """file:// URL должен быть запрещён."""
        with pytest.raises(BadRequestError):
            validate_external_url("file:///etc/passwd")
    
    def test_empty_url_fails(self):
        """Пустой URL должен быть запрещён."""
        with pytest.raises(BadRequestError):
            validate_external_url("")
    
    def test_none_url_fails(self):
        """None URL должен быть запрещён."""
        with pytest.raises(BadRequestError):
            validate_external_url(None)
    
    def test_too_long_url_fails(self):
        """Слишком длинный URL должен быть запрещён."""
        long_url = "https://example.com/" + "a" * 3000
        with pytest.raises(BadRequestError):
            validate_external_url(long_url)
    
    def test_allow_private_flag(self):
        """С allow_private=True приватные IPs должны быть разрешены."""
        assert validate_external_url("http://127.0.0.1:8080", allow_private=True) is True
        assert validate_external_url("http://192.168.1.1", allow_private=True) is True

    def test_hostname_dns_to_private_ip_fails(self, monkeypatch):
        """Hostname that resolves to private IP must be rejected (SSRF protection)."""
        import socket

        def fake_getaddrinfo(host, *args, **kwargs):
            assert host == "evil.example"
            # Return IPv4 loopback
            return [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0)),
            ]

        monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

        with pytest.raises(BadRequestError):
            validate_external_url("https://evil.example/path")


class TestValidateUrlForPlugin:
    """Тесты для строгой валидации (для плагинов)."""
    
    def test_valid_public_url(self):
        """Публичный URL должен быть валиден."""
        assert validate_url_for_plugin("https://api.example.com") is True
    
    def test_private_ip_always_fails(self):
        """Приватный IP всегда запрещён для плагинов."""
        with pytest.raises(BadRequestError):
            validate_url_for_plugin("http://localhost:8080")
        
        with pytest.raises(BadRequestError):
            validate_url_for_plugin("http://192.168.1.1")
    
    def test_file_url_fails(self):
        """file:// всегда запрещён."""
        with pytest.raises(BadRequestError):
            validate_url_for_plugin("file:///etc/passwd")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
