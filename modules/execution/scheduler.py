from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Dict, Literal, Optional
from uuid import uuid4
from zoneinfo import ZoneInfo

ScheduleTriggerType = Literal["delay", "interval", "cron"]


@dataclass
class ExecutionSchedule:
    """
    ExecutionSchedule — декларативное описание расписания, не execution.

    Важно:
    - schedule_id уникален
    - execution_id для каждого запуска всегда новый (генерируется ExecutionController)
    - schedule immutable, кроме:
      - enabled
      - run_count
      - last_run_at
      - next_run_at
    """

    schedule_id: str
    operation_type: str
    trigger_type: ScheduleTriggerType
    trigger_at: Optional[datetime] = None  # delay
    trigger_every_seconds: Optional[int] = None  # interval
    trigger_cron: Optional[str] = None  # legacy cron field

    # Cron trigger metadata
    cron_expr: Optional[str] = None
    cron_timezone: Optional[str] = "UTC"

    enabled: bool = True
    max_runs: Optional[int] = None
    run_count: int = 0
    last_run_at: Optional[datetime] = None
    next_run_at: datetime | None = None
    created_at: datetime = datetime.now(UTC)

    # Mutable fields with default_factory (must be at the end)
    params: Dict[str, Any] = field(default_factory=dict)
    context: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schedule_id": self.schedule_id,
            "operation_type": self.operation_type,
            "params": self.params,
            "context": self.context,
            "trigger": {
                "type": self.trigger_type,
                "at": self.trigger_at.isoformat() if self.trigger_at else None,
                "every_seconds": self.trigger_every_seconds,
                "cron": self.cron_expr or self.trigger_cron,
                "timezone": self.cron_timezone,
            },
            "enabled": self.enabled,
            "max_runs": self.max_runs,
            "run_count": self.run_count,
            "last_run_at": self.last_run_at.isoformat() if self.last_run_at else None,
            "next_run_at": self.next_run_at.isoformat() if self.next_run_at else None,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExecutionSchedule":
        trigger = data.get("trigger") or {}
        cron = trigger.get("cron")
        tz = trigger.get("timezone") or "UTC"
        return cls(
            schedule_id=str(data["schedule_id"]),
            operation_type=str(data["operation_type"]),
            trigger_type=str(trigger.get("type") or "interval"),  # default interval
            trigger_at=_parse_datetime_optional(trigger.get("at")),
            trigger_every_seconds=_parse_int_optional(trigger.get("every_seconds")),
            trigger_cron=cron,
            cron_expr=cron,
            cron_timezone=str(tz),
            enabled=bool(data.get("enabled", True)),
            max_runs=_parse_int_optional(data.get("max_runs")),
            run_count=int(data.get("run_count") or 0),
            last_run_at=_parse_datetime_optional(data.get("last_run_at")),
            next_run_at=_parse_datetime_optional(data.get("next_run_at")),
            created_at=_parse_datetime(data.get("created_at")),
            params=data.get("params") or {},
            context=data.get("context") or {},
        )

    def ensure_next_run_at(self, now: datetime) -> None:
        """
        Выставляет next_run_at, если оно отсутствует, исходя из trigger_* полей.
        """
        if self.next_run_at is not None:
            return

        if self.trigger_type == "delay":
            # Один запуск в момент trigger_at (или сразу, если уже прошёл).
            if self.trigger_at is None:
                self.next_run_at = now
            else:
                self.next_run_at = self.trigger_at
        elif self.trigger_type == "interval":
            sec = self.trigger_every_seconds or 0
            if sec <= 0:
                # Некорректный interval — отключаем расписание.
                self.enabled = False
                self.next_run_at = None
            else:
                self.next_run_at = now + timedelta(seconds=sec)
        elif self.trigger_type == "cron":
            expr = self.cron_expr or self.trigger_cron
            if not expr:
                self.enabled = False
                self.next_run_at = None
                return
            try:
                self.next_run_at = compute_next_run(
                    cron_expr=expr,
                    timezone=self.cron_timezone or "UTC",
                    last_run_at=self.last_run_at,
                    now=now,
                )
            except Exception:
                # Некорректное cron-выражение — отключаем расписание.
                self.enabled = False
                self.next_run_at = None
        else:
            # Неизвестный trigger_type — отключаем.
            self.enabled = False
            self.next_run_at = None

    def compute_next_after_run(self, now: datetime) -> None:
        """
        Пересчитывает next_run_at после успешного запуска.
        """
        if self.trigger_type == "delay":
            # Один запуск — затем отключаем.
            self.enabled = False
            self.next_run_at = None
        elif self.trigger_type == "interval":
            sec = self.trigger_every_seconds or 0
            if sec <= 0:
                self.enabled = False
                self.next_run_at = None
            else:
                self.next_run_at = now + timedelta(seconds=sec)
        elif self.trigger_type == "cron":
            expr = self.cron_expr or self.trigger_cron
            if not expr:
                self.enabled = False
                self.next_run_at = None
                return
            try:
                self.next_run_at = compute_next_run(
                    cron_expr=expr,
                    timezone=self.cron_timezone or "UTC",
                    last_run_at=now,
                    now=now,
                )
            except Exception:
                self.enabled = False
                self.next_run_at = None
        else:
            self.enabled = False
            self.next_run_at = None


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=UTC)
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value)
            return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
        except Exception:
            try:
                return datetime.fromtimestamp(float(value), tz=UTC)
            except Exception:
                pass
    return datetime.now(UTC)


def _parse_datetime_optional(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    return _parse_datetime(value)


def _parse_int_optional(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def compute_next_run(
    *,
    cron_expr: str,
    timezone: str,
    last_run_at: Optional[datetime],
    now: datetime,
) -> datetime:
    """
    Вычисляет следующий cron-tick по выражению вида "*/N * * * *" или "* * * * *".

    Ограничения (MVP ):
    - поддерживается только минутное поле:
      - "*"       → каждую минуту
      - "*/N"    → каждые N минут
      - "M" (int) → конкретная минута в часе
    - остальные поля должны быть "*"

    now и last_run_at — timezone-aware; возвращаемое значение тоже timezone-aware.
    """
    parts = cron_expr.split()
    if len(parts) != 5:
        raise ValueError(f"Unsupported cron expression: {cron_expr}")

    minute_field, hour_field, dom_field, month_field, dow_field = parts
    if hour_field != "*" or dom_field != "*" or month_field != "*" or dow_field != "*":
        raise ValueError(
            f"Unsupported cron expression (only minute-level '*' supported): {cron_expr}"
        )

    # Разбираем минутное поле
    step: Optional[int] = None
    exact_minute: Optional[int] = None

    if minute_field == "*":
        step = 1
    elif minute_field.startswith("*/"):
        try:
            step = int(minute_field[2:])
            if step <= 0:
                raise ValueError
        except Exception:
            raise ValueError(
                f"Invalid minute step in cron expression: {cron_expr}"
            ) from None
    else:
        try:
            exact_minute = int(minute_field)
            if not (0 <= exact_minute < 60):
                raise ValueError
        except Exception:
            raise ValueError(
                f"Invalid minute field in cron expression: {cron_expr}"
            ) from None

    try:
        tz = ZoneInfo(timezone)
    except Exception:
        raise ValueError(f"Invalid timezone for cron expression: {timezone}") from None

    base = last_run_at or now
    base = base.astimezone(tz)

    # Нормализуем к минуте
    base = base.replace(second=0, microsecond=0)

    if exact_minute is not None:
        # Следующий раз — в ближайший момент, когда минуты == exact_minute.
        candidate = base
        if candidate.minute >= exact_minute:
            candidate = candidate.replace(minute=exact_minute) + timedelta(hours=1)
        else:
            candidate = candidate.replace(minute=exact_minute)
    else:
        # step mode
        step = step or 1
        minute = base.minute
        # ближайшая минута, кратная step, строго после base
        next_minute = ((minute // step) + 1) * step
        add_hours = 0
        if next_minute >= 60:
            next_minute = next_minute % 60
            add_hours = 1
        candidate = base + timedelta(hours=add_hours)
        candidate = candidate.replace(minute=next_minute)

    return candidate.astimezone(UTC)


def generate_schedule_id() -> str:
    """Генерирует уникальный идентификатор расписания."""
    return f"sched-{uuid4().hex[:16]}"


class ExecutionScheduler:
    """
    Scheduler для запуска ExecutionSchedule по next_run_at.
    Хранит расписания в storage (namespace execution, ключи schedules/<schedule_id>).
    """

    def __init__(self, runtime: Any, controller: Any) -> None:
        self._runtime = runtime
        self._controller = controller
        self._ns = "execution"
        self._prefix = "schedules/"

    async def save_schedule(self, sched: ExecutionSchedule) -> None:
        """Сохраняет расписание в storage."""
        storage = getattr(self._runtime, "storage", None)
        if storage is None:
            return
        key = f"{self._prefix}{sched.schedule_id}"
        data = sched.to_dict()
        # Сериализуем datetime в ISO строки для JSON-совместимого хранения
        await storage.set(self._ns, key, data)

    async def _load_schedule(self, schedule_id: str) -> Optional[ExecutionSchedule]:
        """Загружает одно расписание по id."""
        storage = getattr(self._runtime, "storage", None)
        if storage is None:
            return None
        key = f"{self._prefix}{schedule_id}"
        try:
            data = await storage.get(self._ns, key)
        except Exception:
            return None
        if not isinstance(data, dict):
            return None
        return ExecutionSchedule.from_dict(data)

    async def tick(self, now: Optional[datetime] = None) -> None:
        """
        Один проход: загружает расписания, для которых next_run_at <= now,
        запускает execution через controller, обновляет и сохраняет.
        """
        now = now or datetime.now(UTC)
        storage = getattr(self._runtime, "storage", None)
        if storage is None:
            return
        try:
            keys = await storage.list_keys(self._ns)
        except Exception:
            return
        schedule_keys = [k for k in keys if k.startswith(self._prefix)]
        for key in schedule_keys:
            schedule_id = key[len(self._prefix) :]
            sched = await self._load_schedule(schedule_id)
            if sched is None or not sched.enabled:
                continue
            if sched.next_run_at is None:
                sched.ensure_next_run_at(now)
            if sched.next_run_at is None or sched.next_run_at > now:
                if sched.next_run_at is not None:
                    await self.save_schedule(sched)
                continue
            # Запускаем выполнение
            try:
                await self._controller.execute_operation(
                    operation_id=generate_schedule_id(),
                    operation_type=sched.operation_type,
                    params=sched.params,
                    context=dict(sched.context),
                )
            except Exception:
                # Не отмечаем запуск успешным и оставляем schedule доступным для retry на следующем tick.
                continue
            sched.run_count += 1
            sched.last_run_at = now
            sched.compute_next_after_run(now)
            if sched.max_runs is not None and sched.run_count >= sched.max_runs:
                sched.enabled = False
            await self.save_schedule(sched)
