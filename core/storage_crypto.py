"""
Cryptographic utilities for cold storage.

Функции для:
- Вычисления SHA256
- Построения Merkle root
- Подписи и проверки данных (Ed25519)
- Канонической сериализации JSON
"""

import hashlib
import json
from typing import Any, Optional
from datetime import datetime


def canonical_json(obj: Any) -> str:
    """
    Сериализовать объект в канонический JSON (sorted keys, no whitespace).
    
    Гарантирует, что одинаковые данные всегда производят одинаковый JSON.
    Важно для криптографических операций.
    
    Args:
        obj: объект для сериализации
        
    Returns:
        Канонический JSON string
    """
    return json.dumps(
        obj,
        sort_keys=True,
        separators=(',', ':'),
        ensure_ascii=False
    )


def sha256_bytes(data: bytes) -> str:
    """
    Вычислить SHA256 hash bytes.
    
    Args:
        data: байты для хэширования
        
    Returns:
        hex-encoded SHA256 hash
    """
    return hashlib.sha256(data).hexdigest()


def sha256_json(obj: Any) -> str:
    """
    Вычислить SHA256 hash для JSON-объекта.
    
    Args:
        obj: объект для хэширования
        
    Returns:
        hex-encoded SHA256 hash
    """
    canonical = canonical_json(obj)
    return sha256_bytes(canonical.encode('utf-8'))


def sha256_string(s: str) -> str:
    """
    Вычислить SHA256 hash для строки.
    
    Args:
        s: строка для хэширования
        
    Returns:
        hex-encoded SHA256 hash
    """
    return sha256_bytes(s.encode('utf-8'))


def merkle_root(items: list[str]) -> str:
    """
    Вычислить Merkle root для списка хешей.
    
    Алгоритм:
    1. Если нет элементов → вернуть SHA256 of empty
    2. Если 1 элемент → вернуть его
    3. Иначе → попарно объединить, пересчитать слой, повторить
    
    Args:
        items: список hex-encoded SHA256 хешей
        
    Returns:
        hex-encoded Merkle root hash
    """
    if not items:
        # Empty merkle tree хеш
        return sha256_string("")
    
    if len(items) == 1:
        return items[0]
    
    # Построить дерево слой за слоем
    current_level = items[:]
    
    while len(current_level) > 1:
        next_level = []
        # Попарно объединяем элементы
        for i in range(0, len(current_level), 2):
            left = current_level[i]
            right = current_level[i + 1] if i + 1 < len(current_level) else left
            # Объединяем и хешируем
            combined = sha256_bytes((left + right).encode('utf-8'))
            next_level.append(combined)
        current_level = next_level
    
    return current_level[0]


def calculate_namespace_root(items: dict[str, str]) -> str:
    """
    Вычислить Merkle root для namespace (dict of key → sha256(value)).
    
    Args:
        items: {key: sha256_hash_of_value}
        
    Returns:
        hex-encoded Merkle root
    """
    if not items:
        return merkle_root([])
    
    # Отсортировать по ключам и собрать хеши
    sorted_keys = sorted(items.keys())
    hashes = [items[k] for k in sorted_keys]
    
    return merkle_root(hashes)


def calculate_storage_root(namespace_roots: dict[str, str]) -> str:
    """
    Вычислить глобальный Merkle root для всего хранилища.
    
    Args:
        namespace_roots: {namespace: merkle_root_hash}
        
    Returns:
        hex-encoded global Merkle root
    """
    if not namespace_roots:
        return merkle_root([])
    
    # Отсортировать по namespace и собрать хеши
    sorted_ns = sorted(namespace_roots.keys())
    hashes = [namespace_roots[ns] for ns in sorted_ns]
    
    return merkle_root(hashes)
