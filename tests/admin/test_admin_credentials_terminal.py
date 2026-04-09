from __future__ import annotations

from collections import deque
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from modules.admin import credentials_handlers
from modules.admin.services.ssh_terminal import _SshSession


class FakeWebSocket:
    def __init__(self, messages: list[dict[str, object]] | None = None):
        self.query_params: dict[str, str] = {}
        self._messages = deque(messages or [])
        self.sent_bytes: list[bytes] = []
        self.closed: tuple[int | None, str | None] | None = None

    async def send_bytes(self, data: bytes) -> None:
        self.sent_bytes.append(data)

    async def receive(self) -> dict[str, object]:
        if self._messages:
            return self._messages.popleft()
        return {"type": "websocket.disconnect"}

    async def close(self, code: int | None = None, reason: str | None = None) -> None:
        self.closed = (code, reason)


@pytest.fixture(autouse=True)
def clear_terminal_state() -> None:
    credentials_handlers._ACTIVE_TERMINAL_SESSIONS.clear()
    credentials_handlers._TERMINAL_HANDLES.clear()
    yield
    credentials_handlers._ACTIVE_TERMINAL_SESSIONS.clear()
    credentials_handlers._TERMINAL_HANDLES.clear()


@pytest.mark.asyncio
async def test_admin_credentials_terminal_ws_requires_credential_id() -> None:
    runtime = SimpleNamespace()
    websocket = FakeWebSocket()

    await credentials_handlers.admin_credentials_terminal_ws(runtime, websocket)

    assert websocket.closed == (4000, "credential_id required")
    assert credentials_handlers._ACTIVE_TERMINAL_SESSIONS == {}
    assert credentials_handlers._TERMINAL_HANDLES == {}


@pytest.mark.asyncio
async def test_admin_credentials_terminal_ws_returns_close_when_repo_missing() -> None:
    runtime = SimpleNamespace()
    websocket = FakeWebSocket()
    websocket.query_params["credential_id"] = "cred-1"

    original_get_repo = credentials_handlers._get_repo
    credentials_handlers._get_repo = lambda _runtime: None
    try:
        await credentials_handlers.admin_credentials_terminal_ws(runtime, websocket)
    finally:
        credentials_handlers._get_repo = original_get_repo

    assert websocket.closed == (4001, "Credentials not available")
    assert credentials_handlers._ACTIVE_TERMINAL_SESSIONS == {}
    assert credentials_handlers._TERMINAL_HANDLES == {}


@pytest.mark.asyncio
async def test_admin_credentials_terminal_ws_cleans_up_after_disconnect() -> None:
    runtime = SimpleNamespace()
    websocket = FakeWebSocket(
        messages=[
            {"type": "websocket.receive", "text": "ping"},
            {"type": "websocket.disconnect"},
        ]
    )
    websocket.query_params["credential_id"] = "cred-1"

    cred = SimpleNamespace(
        type=credentials_handlers.CredentialType.SSH_PASSWORD,
        host="example.com",
        username="admin",
        port=22,
    )

    repo = AsyncMock()
    repo.get_with_secret = AsyncMock(return_value=(cred, b"secret"))

    class FakeChannel:
        def __init__(self) -> None:
            self.sent: list[bytes] = []
            self.closed = False
            self._chunks = deque([b"hello", b""])

        def recv(self, _size: int) -> bytes:
            if self._chunks:
                return self._chunks.popleft()
            return b""

        def send(self, data: bytes) -> None:
            self.sent.append(data)

        def resize_pty(self, width: int, height: int) -> None:
            return None

        def close(self) -> None:
            self.closed = True

    class FakeClient:
        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    fake_client = FakeClient()
    fake_channel = FakeChannel()

    original_get_repo = credentials_handlers._get_repo
    original_ssh_open_shell = credentials_handlers._ssh_open_shell
    credentials_handlers._get_repo = lambda _runtime: repo
    credentials_handlers._ssh_open_shell = lambda _cred, _secret: (
        fake_client,
        fake_channel,
    )
    try:
        await credentials_handlers.admin_credentials_terminal_ws(runtime, websocket)
    finally:
        credentials_handlers._get_repo = original_get_repo
        credentials_handlers._ssh_open_shell = original_ssh_open_shell

    assert websocket.closed is None
    assert websocket.sent_bytes == [b"hello"]
    assert fake_channel.sent == [b"ping"]
    assert fake_channel.closed is True
    assert fake_client.closed is True
    assert credentials_handlers._ACTIVE_TERMINAL_SESSIONS == {}
    assert credentials_handlers._TERMINAL_HANDLES == {}


@pytest.mark.asyncio
async def test_admin_credentials_terminal_session_close_closes_handles() -> None:
    session_id = "cred-1:handle"
    channel = SimpleNamespace(closed=False)
    client = SimpleNamespace(closed=False)

    def close_channel() -> None:
        channel.closed = True

    def close_client() -> None:
        client.closed = True

    channel.close = close_channel
    client.close = close_client

    credentials_handlers._ACTIVE_TERMINAL_SESSIONS[session_id] = {
        "credential_id": "cred-1"
    }
    credentials_handlers._TERMINAL_HANDLES[session_id] = {
        "channel": channel,
        "client": client,
    }

    result = await credentials_handlers.admin_credentials_terminal_session_close(
        runtime=SimpleNamespace(),
        session_id=session_id,
    )

    assert result == {"deleted": True}
    assert channel.closed is True
    assert client.closed is True
    assert credentials_handlers._ACTIVE_TERMINAL_SESSIONS == {}
    assert credentials_handlers._TERMINAL_HANDLES == {}


def test_ssh_terminal_broadcast_swallows_type_error() -> None:
    session = _SshSession("sid-1", "cred-1", "host", "user")

    class BadLoop:
        def call_soon_threadsafe(self, *_args: object, **_kwargs: object) -> None:
            raise TypeError("bad queue")

    class DummyQueue:
        def put_nowait(self, _value: object) -> None:
            return None

    session._loop = BadLoop()  # type: ignore[assignment]
    session._subscribers.append(DummyQueue())

    session._broadcast(b"chunk")


def test_ssh_terminal_close_swallows_oserror() -> None:
    session = _SshSession("sid-2", "cred-2", "host", "user")

    class BadChannel:
        def close(self) -> None:
            raise OSError("channel close failed")

    class BadClient:
        def close(self) -> None:
            raise OSError("client close failed")

    session.channel = BadChannel()
    session.client = BadClient()

    session.close()

    assert session._closed is True
