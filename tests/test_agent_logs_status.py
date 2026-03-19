"""
Tests: TASK 3.1 (Agent Logs API) + TASK 3.2 (Agent Status endpoint)

Structure:
  TestAgentLogStore          — unit tests for core/agents/log_store.py
  TestAdminAgentSubmitLogs   — admin_agent_submit_logs() service function
  TestAdminAgentGetLogs      — admin_agent_get_logs() service function
  TestAdminAgentGetStatus    — admin_agent_get_status() service function
  TestLogsStatusIntegration  — combined flow (submit → get, heartbeat → status)
"""

import pytest
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace

from core.agent.log_store import AgentLogStore, LogEntry
from core.agent.registry import AgentRegistry, AgentMetadata
from core.agents.deployment_tracker import DeploymentTracker

from modules.agent.services import (
    admin_agent_submit_logs,
    admin_agent_get_logs,
    admin_agent_get_status,
    admin_agent_heartbeat,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _build_runtime(with_log_store: bool = True, with_registry: bool = True):
    rt = SimpleNamespace(
        agent_log_store=AgentLogStore() if with_log_store else None,
        agent_registry=AgentRegistry() if with_registry else None,
        deployment_tracker=DeploymentTracker(),
    )
    return rt


async def _register_agent(registry: AgentRegistry, agent_id: str, name: str = "test-agent"):
    await registry.register_agent_online(
        agent_id=agent_id,
        agent_name=name,
        version="1.0.0",
        address="10.0.0.1:8080",
        capabilities=["sensor.read"],
        now=_now(),
    )


# ===========================================================================
# AgentLogStore unit tests
# ===========================================================================

class TestAgentLogStore:

    def test_push_single_entry(self):
        store = AgentLogStore()
        entry = store.push("agent-1", "info", "hello world")
        assert isinstance(entry, LogEntry)
        assert entry.level == "info"
        assert entry.message == "hello world"
        assert entry.source == "agent"

    def test_push_normalises_warning_to_warn(self):
        store = AgentLogStore()
        e = store.push("a1", "warning", "msg")
        assert e.level == "warn"

    def test_push_unknown_level_defaults_to_info(self):
        store = AgentLogStore()
        e = store.push("a1", "nonsense", "msg")
        assert e.level == "info"

    def test_push_truncates_long_message(self):
        store = AgentLogStore()
        long_msg = "x" * 5000
        e = store.push("a1", "info", long_msg)
        assert len(e.message) <= 4097  # 4096 + "…"
        assert e.message.endswith("…")

    def test_push_custom_source_and_timestamp(self):
        store = AgentLogStore()
        ts = "2026-02-28T12:00:00+00:00"
        e = store.push("a1", "error", "boom", source="kernel", timestamp=ts)
        assert e.source == "kernel"
        assert e.timestamp == ts

    def test_push_metadata(self):
        store = AgentLogStore()
        e = store.push("a1", "debug", "details", metadata={"line": 42})
        assert e.metadata["line"] == 42

    def test_get_returns_all_by_default(self):
        store = AgentLogStore()
        for i in range(10):
            store.push("a1", "info", f"msg-{i}")
        entries = store.get("a1")
        assert len(entries) == 10

    def test_get_unknown_agent_returns_empty(self):
        store = AgentLogStore()
        assert store.get("no-such-agent") == []

    def test_get_with_level_filter(self):
        store = AgentLogStore()
        store.push("a1", "info", "i1")
        store.push("a1", "error", "e1")
        store.push("a1", "warn", "w1")
        store.push("a1", "error", "e2")

        errors = store.get("a1", level_filter="error")
        assert len(errors) == 2
        assert all(e.level == "error" for e in errors)

    def test_get_with_comma_separated_filter(self):
        store = AgentLogStore()
        for lvl in ["debug", "info", "warn", "error"]:
            store.push("a1", lvl, f"{lvl} msg")
        result = store.get("a1", level_filter="warn,error")
        assert len(result) == 2
        levels = {e.level for e in result}
        assert levels == {"warn", "error"}

    def test_get_tail_limits_output(self):
        store = AgentLogStore()
        for i in range(20):
            store.push("a1", "info", f"msg-{i}")
        entries = store.get("a1", tail=5)
        assert len(entries) == 5
        # Last 5 entries
        assert entries[-1].message == "msg-19"
        assert entries[0].message == "msg-15"

    def test_ring_buffer_evicts_oldest(self):
        store = AgentLogStore(max_per_agent=5)
        for i in range(10):
            store.push("a1", "info", f"msg-{i}")
        entries = store.get("a1")
        assert len(entries) == 5
        assert entries[0].message == "msg-5"
        assert entries[-1].message == "msg-9"

    def test_push_batch(self):
        store = AgentLogStore()
        batch = [
            {"level": "info", "message": "batch-1"},
            {"level": "error", "message": "batch-2"},
            {"level": "warn", "message": "batch-3"},
        ]
        added = store.push_batch("a1", batch)
        assert added == 3
        assert store.count("a1") == 3

    def test_push_batch_skips_invalid(self):
        store = AgentLogStore()
        batch = [
            {"level": "info", "message": "ok"},
            {"level": "info"},           # no message → skip
            "not-a-dict",                # wrong type → skip
        ]
        added = store.push_batch("a1", batch)
        assert added == 1

    def test_clear_agent(self):
        store = AgentLogStore()
        for i in range(5):
            store.push("a1", "info", f"msg-{i}")
        removed = store.clear("a1")
        assert removed == 5
        assert store.count("a1") == 0

    def test_clear_all(self):
        store = AgentLogStore()
        for aid in ["a1", "a2", "a3"]:
            store.push(aid, "info", "msg")
        store.clear_all()
        assert store.agent_ids() == []

    def test_multiple_agents_isolated(self):
        store = AgentLogStore()
        store.push("agent-A", "info", "A msg")
        store.push("agent-B", "error", "B msg")
        assert store.count("agent-A") == 1
        assert store.count("agent-B") == 1
        assert store.get("agent-A")[0].message == "A msg"
        assert store.get("agent-B")[0].message == "B msg"

    def test_to_dict(self):
        store = AgentLogStore()
        e = store.push("a1", "info", "hello", source="main")
        d = e.to_dict()
        assert d["level"] == "info"
        assert d["message"] == "hello"
        assert d["source"] == "main"
        assert "timestamp" in d


# ===========================================================================
# admin_agent_submit_logs
# ===========================================================================

class TestAdminAgentSubmitLogs:

    @pytest.mark.asyncio
    async def test_submit_basic_batch(self):
        rt = _build_runtime()
        result = await admin_agent_submit_logs(
            rt, agent_id="a1",
            body={"logs": [
                {"level": "info", "message": "started"},
                {"level": "warn", "message": "low memory"},
            ]}
        )
        assert result["ok"] is True
        assert result["accepted"] == 2

    @pytest.mark.asyncio
    async def test_submit_empty_logs(self):
        rt = _build_runtime()
        result = await admin_agent_submit_logs(rt, "a1", body={"logs": []})
        assert result["ok"] is True
        assert result["accepted"] == 0

    @pytest.mark.asyncio
    async def test_submit_no_body(self):
        rt = _build_runtime()
        result = await admin_agent_submit_logs(rt, "a1", body=None)
        assert result["ok"] is True
        assert result["accepted"] == 0

    @pytest.mark.asyncio
    async def test_submit_missing_agent_id(self):
        rt = _build_runtime()
        result = await admin_agent_submit_logs(rt, agent_id="", body={})
        assert result["ok"] is False
        assert "agent_id" in result["error"]

    @pytest.mark.asyncio
    async def test_submit_no_log_store(self):
        rt = _build_runtime(with_log_store=False)
        result = await admin_agent_submit_logs(rt, "a1", body={"logs": [{"level": "info", "message": "m"}]})
        assert result["ok"] is False
        assert "agent_log_store" in result["error"]

    @pytest.mark.asyncio
    async def test_submit_invalid_logs_not_list(self):
        rt = _build_runtime()
        result = await admin_agent_submit_logs(rt, "a1", body={"logs": "not-a-list"})
        assert result["ok"] is False

    @pytest.mark.asyncio
    async def test_submit_accumulates_across_calls(self):
        rt = _build_runtime()
        await admin_agent_submit_logs(rt, "a1", body={"logs": [{"level": "info", "message": "1"}]})
        await admin_agent_submit_logs(rt, "a1", body={"logs": [{"level": "info", "message": "2"}]})
        assert rt.agent_log_store.count("a1") == 2

    @pytest.mark.asyncio
    async def test_submit_from_multiple_agents_isolated(self):
        rt = _build_runtime()
        await admin_agent_submit_logs(rt, "a1", body={"logs": [{"level": "info", "message": "A"}]})
        await admin_agent_submit_logs(rt, "a2", body={"logs": [{"level": "warn", "message": "B"}]})
        assert rt.agent_log_store.count("a1") == 1
        assert rt.agent_log_store.count("a2") == 1


# ===========================================================================
# admin_agent_get_logs
# ===========================================================================

class TestAdminAgentGetLogs:

    @pytest.mark.asyncio
    async def test_get_logs_empty(self):
        rt = _build_runtime()
        result = await admin_agent_get_logs(rt, "a1")
        assert result["ok"] is True
        assert result["logs"] == []
        assert result["total"] == 0

    @pytest.mark.asyncio
    async def test_get_logs_returns_all_by_default(self):
        rt = _build_runtime()
        for i in range(5):
            rt.agent_log_store.push("a1", "info", f"msg-{i}")
        result = await admin_agent_get_logs(rt, "a1", tail=None)
        assert result["ok"] is True
        assert len(result["logs"]) == 5

    @pytest.mark.asyncio
    async def test_get_logs_default_tail_100(self):
        rt = _build_runtime()
        for i in range(150):
            rt.agent_log_store.push("a1", "info", f"msg-{i}")
        result = await admin_agent_get_logs(rt, "a1")  # tail=100 default
        assert result["ok"] is True
        assert len(result["logs"]) == 100
        assert result["total"] == 150

    @pytest.mark.asyncio
    async def test_get_logs_filter_by_level(self):
        rt = _build_runtime()
        rt.agent_log_store.push("a1", "info", "i1")
        rt.agent_log_store.push("a1", "error", "e1")
        rt.agent_log_store.push("a1", "error", "e2")
        result = await admin_agent_get_logs(rt, "a1", filter="error", tail=None)
        assert result["ok"] is True
        assert len(result["logs"]) == 2
        assert all(e["level"] == "error" for e in result["logs"])

    @pytest.mark.asyncio
    async def test_get_logs_dict_format(self):
        rt = _build_runtime()
        rt.agent_log_store.push("a1", "warn", "test msg", source="kernel")
        result = await admin_agent_get_logs(rt, "a1", tail=None)
        entry = result["logs"][0]
        assert "timestamp" in entry
        assert entry["level"] == "warn"
        assert entry["message"] == "test msg"
        assert entry["source"] == "kernel"

    @pytest.mark.asyncio
    async def test_get_logs_agent_online_flag_true(self):
        rt = _build_runtime()
        await _register_agent(rt.agent_registry, "a1")
        await rt.agent_registry.update_agent_heartbeat("a1", _now())
        result = await admin_agent_get_logs(rt, "a1")
        assert result["agent_online"] is True

    @pytest.mark.asyncio
    async def test_get_logs_agent_online_flag_false_stale(self):
        rt = _build_runtime()
        await _register_agent(rt.agent_registry, "a1")
        stale = (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat()
        await rt.agent_registry.update_agent_heartbeat("a1", stale)
        result = await admin_agent_get_logs(rt, "a1")
        assert result["agent_online"] is False

    @pytest.mark.asyncio
    async def test_get_logs_missing_agent_id(self):
        rt = _build_runtime()
        result = await admin_agent_get_logs(rt, "")
        assert result["ok"] is False

    @pytest.mark.asyncio
    async def test_get_logs_no_log_store(self):
        rt = _build_runtime(with_log_store=False)
        result = await admin_agent_get_logs(rt, "a1")
        assert result["ok"] is False
        assert "agent_log_store" in result["error"]

    @pytest.mark.asyncio
    async def test_get_logs_returned_field(self):
        rt = _build_runtime()
        for i in range(10):
            rt.agent_log_store.push("a1", "info", f"m{i}")
        result = await admin_agent_get_logs(rt, "a1", tail=3)
        assert result["returned"] == 3
        assert result["total"] == 10


# ===========================================================================
# admin_agent_get_status
# ===========================================================================

class TestAdminAgentGetStatus:

    @pytest.mark.asyncio
    async def test_status_online_fresh_heartbeat(self):
        rt = _build_runtime()
        await _register_agent(rt.agent_registry, "a1", "my-agent")
        await rt.agent_registry.update_agent_heartbeat("a1", _now())

        result = await admin_agent_get_status(rt, "a1")
        assert result["ok"] is True
        assert result["agent_id"] == "a1"
        assert result["name"] == "my-agent"
        assert result["status"] == "online"
        assert result["heartbeat_age_seconds"] is not None
        assert result["heartbeat_age_seconds"] < 5

    @pytest.mark.asyncio
    async def test_status_offline_stale_heartbeat(self):
        rt = _build_runtime()
        await _register_agent(rt.agent_registry, "a1")
        stale = (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat()
        await rt.agent_registry.update_agent_heartbeat("a1", stale)

        result = await admin_agent_get_status(rt, "a1")
        assert result["ok"] is True
        assert result["status"] == "offline"
        assert result["heartbeat_age_seconds"] >= 60

    @pytest.mark.asyncio
    async def test_status_dead_very_old_heartbeat(self):
        rt = _build_runtime()
        await _register_agent(rt.agent_registry, "a1")
        dead_ts = (datetime.now(timezone.utc) - timedelta(seconds=400)).isoformat()
        await rt.agent_registry.update_agent_heartbeat("a1", dead_ts)

        result = await admin_agent_get_status(rt, "a1")
        assert result["ok"] is True
        assert result["status"] == "dead"

    @pytest.mark.asyncio
    async def test_status_unknown_no_heartbeat(self):
        rt = _build_runtime()
        rt.agent_registry._agents["a1"] = AgentMetadata(
            agent_id="a1", agent_name="unknown-hb"
        )
        result = await admin_agent_get_status(rt, "a1")
        assert result["ok"] is True
        assert result["status"] == "unknown"
        assert result["heartbeat_age_seconds"] is None

    @pytest.mark.asyncio
    async def test_status_degraded_from_heartbeat_body(self):
        rt = _build_runtime()
        await _register_agent(rt.agent_registry, "a1")
        await rt.agent_registry.update_agent_heartbeat("a1", _now())
        # Mark agent as degraded in properties
        agent = await rt.agent_registry.get_agent("a1")
        agent.properties["status"] = "degraded"

        result = await admin_agent_get_status(rt, "a1")
        assert result["status"] == "degraded"

    @pytest.mark.asyncio
    async def test_status_agent_not_found(self):
        rt = _build_runtime()
        result = await admin_agent_get_status(rt, "no-such-agent")
        assert result["ok"] is False
        assert result["error"] == "agent_not_found"

    @pytest.mark.asyncio
    async def test_status_missing_agent_id(self):
        rt = _build_runtime()
        result = await admin_agent_get_status(rt, "")
        assert result["ok"] is False
        assert "agent_id" in result["error"]

    @pytest.mark.asyncio
    async def test_status_no_registry(self):
        rt = _build_runtime(with_registry=False)
        result = await admin_agent_get_status(rt, "a1")
        assert result["ok"] is False
        assert "agent_registry" in result["error"]

    @pytest.mark.asyncio
    async def test_status_includes_metrics_from_heartbeat(self):
        rt = _build_runtime()
        await _register_agent(rt.agent_registry, "a1")
        # Send heartbeat with CPU/memory metrics
        await admin_agent_heartbeat(
            rt, agent_id="a1",
            body={
                "status": "ok",
                "uptime_seconds": 7200,
                "cpu_percent": 14.5,
                "memory_mb": 512,
            }
        )

        result = await admin_agent_get_status(rt, "a1")
        assert result["ok"] is True
        assert result["uptime_seconds"] == 7200
        assert result["cpu_percent"] == 14.5
        assert result["memory_mb"] == 512

    @pytest.mark.asyncio
    async def test_status_includes_capabilities(self):
        rt = _build_runtime()
        await rt.agent_registry.register_agent_online(
            "cap-agent", "cap-test", "1.0", "h", ["sensor.read", "actuator.write"], _now()
        )
        result = await admin_agent_get_status(rt, "cap-agent")
        assert result["ok"] is True
        assert "sensor.read" in result["capabilities"]
        assert "actuator.write" in result["capabilities"]

    @pytest.mark.asyncio
    async def test_status_includes_version_and_address(self):
        rt = _build_runtime()
        await rt.agent_registry.register_agent_online(
            "ver-agent", "ver-test", "2.3.1", "192.168.1.100:9090", [], _now()
        )
        result = await admin_agent_get_status(rt, "ver-agent")
        assert result["version"] == "2.3.1"
        assert result["address"] == "192.168.1.100:9090"

    @pytest.mark.asyncio
    async def test_status_has_deployment_id_when_deployed(self):
        rt = _build_runtime()
        await _register_agent(rt.agent_registry, "dep-agent")

        dep_id = "deploy-abc-123"
        await rt.deployment_tracker.create(dep_id, "dep-agent-name", "cred", "h")
        await rt.deployment_tracker.update_status(dep_id, "ready", agent_id="dep-agent")

        result = await admin_agent_get_status(rt, "dep-agent")
        assert result["ok"] is True
        assert result["deployment_id"] == dep_id

    @pytest.mark.asyncio
    async def test_status_deployment_id_none_when_not_deployed(self):
        rt = _build_runtime()
        await _register_agent(rt.agent_registry, "no-dep-agent")
        result = await admin_agent_get_status(rt, "no-dep-agent")
        assert result["ok"] is True
        assert result["deployment_id"] is None


# ===========================================================================
# Integration: submit → get → status combined flow
# ===========================================================================

class TestLogsStatusIntegration:

    @pytest.mark.asyncio
    async def test_full_log_submit_and_query_flow(self):
        """Agent submits logs → admin queries → correct data returned."""
        rt = _build_runtime()
        await _register_agent(rt.agent_registry, "full-a1", "full-agent")
        await rt.agent_registry.update_agent_heartbeat("full-a1", _now())

        # Agent pushes logs
        await admin_agent_submit_logs(rt, "full-a1", body={"logs": [
            {"level": "info",  "message": "Agent started",       "source": "main"},
            {"level": "warn",  "message": "High temperature",    "source": "sensor"},
            {"level": "error", "message": "Sensor read failure", "source": "sensor"},
            {"level": "debug", "message": "Internal state OK",   "source": "core"},
        ]})

        # Admin queries all logs
        all_logs = await admin_agent_get_logs(rt, "full-a1", tail=None)
        assert all_logs["total"] == 4
        assert all_logs["agent_online"] is True

        # Admin queries only errors
        errors = await admin_agent_get_logs(rt, "full-a1", filter="error", tail=None)
        assert errors["returned"] == 1
        assert errors["logs"][0]["message"] == "Sensor read failure"

    @pytest.mark.asyncio
    async def test_status_reflects_heartbeat_data(self):
        """Heartbeat metrics immediately visible in get_status."""
        rt = _build_runtime()
        await _register_agent(rt.agent_registry, "hb-status-agent")

        await admin_agent_heartbeat(rt, "hb-status-agent", body={
            "status": "ok",
            "uptime_seconds": 1234,
            "cpu_percent": 9.9,
            "memory_mb": 64,
        })

        status = await admin_agent_get_status(rt, "hb-status-agent")
        assert status["status"] == "online"
        assert status["uptime_seconds"] == 1234
        assert status["cpu_percent"] == 9.9
        assert status["memory_mb"] == 64

    @pytest.mark.asyncio
    async def test_logs_and_status_independent_per_agent(self):
        """Two agents have separate logs and status."""
        rt = _build_runtime()
        for aid in ["a1", "a2"]:
            await _register_agent(rt.agent_registry, aid, f"agent-{aid}")
            await rt.agent_registry.update_agent_heartbeat(aid, _now())
            await admin_agent_submit_logs(rt, aid, body={"logs": [
                {"level": "info", "message": f"msg from {aid}"}
            ]})

        logs_a1 = await admin_agent_get_logs(rt, "a1", tail=None)
        logs_a2 = await admin_agent_get_logs(rt, "a2", tail=None)
        assert logs_a1["logs"][0]["message"] == "msg from a1"
        assert logs_a2["logs"][0]["message"] == "msg from a2"

        status_a1 = await admin_agent_get_status(rt, "a1")
        status_a2 = await admin_agent_get_status(rt, "a2")
        assert status_a1["status"] == "online"
        assert status_a2["status"] == "online"

    @pytest.mark.asyncio
    async def test_many_log_entries_tail_returns_latest(self):
        """After 200 log pushes, tail=10 returns the last 10."""
        rt = _build_runtime()
        for i in range(200):
            await admin_agent_submit_logs(rt, "stream-a1", body={"logs": [
                {"level": "info", "message": f"entry-{i:04d}"}
            ]})

        result = await admin_agent_get_logs(rt, "stream-a1", tail=10)
        assert result["returned"] == 10
        messages = [e["message"] for e in result["logs"]]
        # Last 10 entries are entry-0190 through entry-0199
        assert "entry-0199" in messages
        assert "entry-0190" in messages
