"""
DEPRECATED: This file contains old PWL implementation with HTML parsing.

NEW APPROACH (in yandex_passport_client.py):
- Device bootstrap via POST /auth/device/start
- No HTML parsing - just verify noPWL flag
- No magic endpoints - simple retpath-based QR
- Direct cookie polling without complex state

This file is kept for reference only.
DO NOT USE - Use YandexPassportClient instead.
"""

# Deprecated - see yandex_passport_client.py for current implementation


