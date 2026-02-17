"""
Storage security exceptions.

Исключения для обнаружения и обработки нарушений целостности хранилища.
"""


class StorageCorruptionError(RuntimeError):
    """
    Обнаружена коррупция данных в хранилище.
    
    Варианты:
    - JSON парсинг не прошел
    - Подпись не совпадает
    - Merkle root не совпадает
    - Данные не заполнены при нулевом ожидании
    """
    pass


class StorageRollbackDetected(RuntimeError):
    """
    Обнаружена попытка отката состояния (rollback attack).
    
    Сценарий:
    - Сохраняем epoch=42
    - Перезагружаемся, файл БД откатывается к epoch=40
    - Система обнаруживает снижение epoch → StorageRollbackDetected
    
    Это FATAL ошибка — система должна прекратить запуск.
    """
    pass


class StorageTamperDetected(RuntimeError):
    """
    Обнаружено намеренное или случайное изменение защищённых данных.
    
    Варианты:
    - Измененная подпись root hash
    - Нарушена непрерывность audit log (prev_hash не совпадает)
    - Изменена система тега без корректного обновления epoch
    """
    pass
