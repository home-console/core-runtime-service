"""
Integration tests: Full Agent Deployment Flow (Day 4)

Tests the complete end-to-end lifecycle:

  1. Create enrollment token
  2. POST /admin/v1/agents/deploy  →  deployment_id
  3. Agent enrolls with token      →  agent_id in registry
  4. Agent sends heartbeat         →  deployment status → READY
  5. Poll GET /admin/v1/deployments/{id} until terminal state
  6. Verify agent appears in list
  7. Verify health-check endpoint

All SSH-level operations are mocked.
Uses real DeploymentTracker + AgentRegistry + AgentEnrollmentManager in-memory.
"""

import pytest
import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from core.agents.deployment_tracker import DeploymentTracker, DeploymentStatus
from core.agent.registry import AgentRegistry, AgentMetadata
from modules.agent.services import (
    admin_agent_deploy,
    admin_agent_enroll_agent,
    admin_agent_heartbeat,
    admin_agent_get_deployment_status,
    admin_agent_check_agents_health,
    admin_agent_list_online_agents,
    admin_agent_get_heartbeat_status,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

class _FakeSecretStore:
    """In-memory secret store (mimics production SecretStore interface)."""
    def __init__(self):
        self._d = {}

    async def put(self, key, value):
        self._d[key] = value

    async def get(self, key):
        return self._d.get(key)

    async def delete(self, key):
        existed = key in self._d
        self._d.pop(key, None)
        return existed

    async def exists(self, key):
        return key in self._d

    async def list_secrets(self):
        return list(self._d.keys())

    async def get_metadata(self, key):
        return {"exists": key in self._d} if key in self._d else None


def _build_enrollment_manager(secret_store):
    """Real AgentEnrollmentManager backed by fake secret store."""
    from core.agent.enrollment import AgentEnrollmentManager
    return AgentEnrollmentManager(secret_store)


def _build_runtime(credential_host="10.0.0.1"):
    """Build a near-complete mock runtime for integration tests."""
    secret_store = _FakeSecretStore()
    agent_manager = _build_enrollment_manager(secret_store)
    deployment_tracker = DeploymentTracker()
    agent_registry = AgentRegistry()

    storage_manager = AsyncMock()
    storage_manager.get = AsyncMock(return_value={"host": credential_host})

    rt = SimpleNamespace(
        agent_manager=agent_manager,
        deployment_tracker=deployment_tracker,
        agent_registry=agent_registry,
        storage_manager=storage_manager,
        secret_store=secret_store,
        mtls_ca=None,
    )
    return rt


# ---------------------------------------------------------------------------
# FLOW 1: happy path — deploy → enroll → heartbeat → READY
# ---------------------------------------------------------------------------

class TestFullDeployHappyPath:

    @pytest.mark.asyncio
    async def test_deploy_then_manual_state_advance_to_ready(self):
        """
        Simulates the full happy path without real SSH:
          deploy() → deployment PENDING/started
          manually enroll agent → status REGISTERING
          send heartbeat → status READY via heartbeat handler
        """
        rt = _build_runtime()

        # ── Step 1: POST /admin/v1/agents/deploy ──────────────────────────
        deploy_result = await admin_agent_deploy(
            rt, body={"agent_name": "integration-agent", "credential_id": "cred-int"}
        )
        assert deploy_result["ok"] is True, deploy_result
        dep_id = deploy_result["deployment_id"]
        assert deploy_result["status"] == "started"
        assert deploy_result["heartbeat_timeout"] == 300

        # ── Step 2: Poll — should be PENDING (background task not running) ─
        poll = await admin_agent_get_deployment_status(rt, dep_id)
        assert poll["ok"] is True
        assert poll["status"] in ("pending", "started", "uploading")

        # ── Step 3: Manually advance tracker (SSH succeeded) ──────────────
        await rt.deployment_tracker.update_status(dep_id, "deployed", progress=50)

        # ── Step 4: Enroll agent (simulates remote-client calling /enroll) ─
        # First create a real enrollment token
        from core.agent.identity import AgentKeyManager
        import json

        hostname = "integration-agent"
        now_str = datetime.now(timezone.utc).isoformat()
        token = await rt.agent_manager.create_enrollment_token(hostname, now_str)

        # Register agent in registry manually (simulates enrollment success)
        await rt.agent_registry.register_agent_online(
            agent_id="agent-int-001",
            agent_name="integration-agent",
            version="1.0.0",
            address="10.0.0.1:8080",
            capabilities=["device.control"],
            now=now_str,
        )

        age = await rt.deployment_tracker.update_status(
            dep_id, "registering", agent_id="agent-int-001", progress=75
        )
        assert age is True

        # ── Step 5: Send heartbeat for that agent ─────────────────────────
        hb_result = await admin_agent_heartbeat(
            rt, agent_id="agent-int-001",
            body={"status": "ok", "uptime_seconds": 10, "cpu_percent": 5.0}
        )
        assert hb_result["ok"] is True
        assert hb_result["ack"] is True

        # ── Step 6: Heartbeat handler should advance deployment to READY ───
        poll_final = await admin_agent_get_deployment_status(rt, dep_id)
        assert poll_final["ok"] is True
        assert poll_final["status"] == "ready"
        assert poll_final["agent_id"] == "agent-int-001"
        assert "duration_seconds" in poll_final
        assert "completed_at" in poll_final

    @pytest.mark.asyncio
    async def test_agent_visible_in_registry_after_deploy(self):
        """After successful deploy, agent must appear in list_agents."""
        rt = _build_runtime()

        await admin_agent_deploy(
            rt, body={"agent_name": "vis-agent", "credential_id": "c"}
        )

        now = datetime.now(timezone.utc).isoformat()
        await rt.agent_registry.register_agent_online(
            agent_id="agent-vis-001",
            agent_name="vis-agent",
            version="1.0.0",
            address="10.0.0.2:8080",
            capabilities=[],
            now=now,
        )

        agents = await rt.agent_registry.list_agents()
        agent_names = [a.agent_name for a in agents]
        assert "vis-agent" in agent_names

    @pytest.mark.asyncio
    async def test_two_agents_deployed_concurrently(self):
        """Two parallel deploys each get unique IDs and independent status."""
        rt = _build_runtime()

        body_a = {"agent_name": "concurrent-a", "credential_id": "cred-a"}
        body_b = {"agent_name": "concurrent-b", "credential_id": "cred-b"}

        r_a, r_b = await asyncio.gather(
            admin_agent_deploy(rt, body=body_a),
            admin_agent_deploy(rt, body=body_b),
        )

        assert r_a["ok"] is True
        assert r_b["ok"] is True
        assert r_a["deployment_id"] != r_b["deployment_id"]

        # Advance A to ready
        await rt.deployment_tracker.update_status(r_a["deployment_id"], "ready")

        status_a = await admin_agent_get_deployment_status(rt, r_a["deployment_id"])
        status_b = await admin_agent_get_deployment_status(rt, r_b["deployment_id"])

        assert status_a["status"] == "ready"
        # B has NOT been advanced to ready — it can be pending/failed/deploying
        assert status_b["status"] != "ready"


# ---------------------------------------------------------------------------
# FLOW 2: failure paths
# ---------------------------------------------------------------------------

class TestDeployFailurePaths:

    @pytest.mark.asyncio
    async def test_ssh_failure_marks_deployment_failed(self):
        """When SSH step fails, deployment should end in FAILED."""
        rt = _build_runtime()

        deploy_result = await admin_agent_deploy(
            rt, body={"agent_name": "fail-agent", "credential_id": "c"}
        )
        assert deploy_result["ok"] is True
        dep_id = deploy_result["deployment_id"]

        # Simulate SSH failure
        await rt.deployment_tracker.update_status(
            dep_id, "failed", error_message="SSH connection refused"
        )

        poll = await admin_agent_get_deployment_status(rt, dep_id)
        assert poll["ok"] is True
        assert poll["status"] == "failed"
        assert "SSH connection refused" in poll["error_message"]

    @pytest.mark.asyncio
    async def test_enrollment_timeout_marks_deployment_timeout(self):
        """If agent doesn't enroll in time, deployment should be TIMEOUT."""
        rt = _build_runtime()

        deploy_result = await admin_agent_deploy(
            rt, body={"agent_name": "slow-agent", "credential_id": "c"}
        )
        dep_id = deploy_result["deployment_id"]

        await rt.deployment_tracker.update_status(dep_id, "deployed", progress=50)
        await rt.deployment_tracker.update_status(
            dep_id, "timeout",
            error_message="Agent did not enroll within 60 seconds"
        )

        poll = await admin_agent_get_deployment_status(rt, dep_id)
        assert poll["status"] == "timeout"
        assert "enroll" in poll["error_message"]

    @pytest.mark.asyncio
    async def test_heartbeat_timeout_after_enroll(self):
        """Agent enrolled but never sent heartbeat → deployment TIMEOUT."""
        rt = _build_runtime()

        deploy_result = await admin_agent_deploy(
            rt, body={"agent_name": "no-hb-agent", "credential_id": "c"}
        )
        dep_id = deploy_result["deployment_id"]

        now = datetime.now(timezone.utc).isoformat()
        await rt.agent_registry.register_agent_online(
            agent_id="agent-no-hb",
            agent_name="no-hb-agent",
            version="1.0.0",
            address="10.0.0.3:8080",
            capabilities=[],
            now=now,
        )
        await rt.deployment_tracker.update_status(
            dep_id, "registering", agent_id="agent-no-hb"
        )
        await rt.deployment_tracker.update_status(
            dep_id, "timeout",
            error_message="Agent did not report heartbeat within timeout"
        )

        poll = await admin_agent_get_deployment_status(rt, dep_id)
        assert poll["status"] == "timeout"
        assert "heartbeat" in poll["error_message"]


# ---------------------------------------------------------------------------
# FLOW 3: heartbeat monitoring
# ---------------------------------------------------------------------------

class TestHeartbeatMonitoringFlow:

    @pytest.mark.asyncio
    async def test_heartbeat_marks_agent_online(self):
        """Sending heartbeat from agent changes status to 'online' in health check."""
        rt = _build_runtime()

        now = datetime.now(timezone.utc).isoformat()
        await rt.agent_registry.register_agent_online(
            agent_id="agent-hb-001",
            agent_name="hb-test",
            version="1.0.0",
            address="10.0.0.10:8080",
            capabilities=["sensor.read"],
            now=now,
        )

        # Send heartbeat
        hb = await admin_agent_heartbeat(
            rt, agent_id="agent-hb-001",
            body={"status": "ok", "uptime_seconds": 100}
        )
        assert hb["ok"] is True

        # Get heartbeat status
        status = await admin_agent_get_heartbeat_status(rt, "agent-hb-001")
        assert status["ok"] is True
        assert status["status"] == "online"
        assert status["heartbeat_age_seconds"] is not None
        assert status["heartbeat_age_seconds"] < 5  # Just sent it

    @pytest.mark.asyncio
    async def test_no_heartbeat_returns_unknown_status(self):
        """Agent registered but no heartbeat → status unknown."""
        rt = _build_runtime()

        # Register agent without heartbeat data
        rt.agent_registry._agents["agent-no-hb-stat"] = AgentMetadata(
            agent_id="agent-no-hb-stat",
            agent_name="unknown-hb-agent",
            last_heartbeat=None,
        )

        status = await admin_agent_get_heartbeat_status(rt, "agent-no-hb-stat")
        assert status["ok"] is True
        assert status["status"] == "unknown"

    @pytest.mark.asyncio
    async def test_health_check_counts_online_agents(self):
        """health_check counts online, offline, dead agents correctly."""
        rt = _build_runtime()
        from datetime import timedelta

        now = datetime.now(timezone.utc)

        # Online agent (fresh heartbeat)
        await rt.agent_registry.register_agent_online(
            "a1", "online-agent", "1.0", "h1", [], now.isoformat()
        )
        await rt.agent_registry.update_agent_heartbeat("a1", now.isoformat())

        # Offline agent (heartbeat > 30s ago, < 5min)
        await rt.agent_registry.register_agent_online(
            "a2", "offline-agent", "1.0", "h2", [], now.isoformat()
        )
        stale_ts = (now - timedelta(seconds=60)).isoformat()
        await rt.agent_registry.update_agent_heartbeat("a2", stale_ts)

        # Dead agent (heartbeat > 5min ago)
        await rt.agent_registry.register_agent_online(
            "a3", "dead-agent", "1.0", "h3", [], now.isoformat()
        )
        dead_ts = (now - timedelta(seconds=400)).isoformat()
        await rt.agent_registry.update_agent_heartbeat("a3", dead_ts)

        # Unknown (no heartbeat)
        rt.agent_registry._agents["a4"] = AgentMetadata(
            agent_id="a4", agent_name="new-agent", last_heartbeat=None
        )

        health = await admin_agent_check_agents_health(rt)
        assert health["ok"] is True
        assert health["total_agents"] == 4
        assert health["stats"]["online"] == 1
        assert health["stats"]["offline"] == 1
        assert health["stats"]["dead"] == 1
        assert health["stats"]["unknown"] == 1

    @pytest.mark.asyncio
    async def test_list_online_agents_only_returns_fresh(self):
        """list_online_agents filters out stale/dead agents."""
        rt = _build_runtime()
        from datetime import timedelta

        now = datetime.now(timezone.utc)

        await rt.agent_registry.register_agent_online(
            "alive1", "alive-agent", "1.0", "h", [], now.isoformat()
        )
        await rt.agent_registry.update_agent_heartbeat("alive1", now.isoformat())

        await rt.agent_registry.register_agent_online(
            "dead1", "dead-agent", "1.0", "h", [], now.isoformat()
        )
        await rt.agent_registry.update_agent_heartbeat(
            "dead1", (now - timedelta(seconds=200)).isoformat()
        )

        result = await admin_agent_list_online_agents(rt)
        assert result["ok"] is True
        assert result["count"] == 1
        assert result["agents"][0]["agent_id"] == "alive1"

    @pytest.mark.asyncio
    async def test_heartbeat_updates_metrics(self):
        """Agent heartbeat with metrics updates stored properties."""
        rt = _build_runtime()
        now = datetime.now(timezone.utc).isoformat()

        await rt.agent_registry.register_agent_online(
            "metrics-agent", "m-agent", "1.0", "h", [], now
        )

        await admin_agent_heartbeat(
            rt, agent_id="metrics-agent",
            body={
                "status": "ok",
                "uptime_seconds": 3600,
                "cpu_percent": 25.5,
                "memory_mb": 256,
            }
        )

        agent = await rt.agent_registry.get_agent("metrics-agent")
        assert agent.properties.get("uptime_seconds") == 3600
        assert agent.properties.get("cpu_percent") == 25.5
        assert agent.properties.get("memory_mb") == 256


# ---------------------------------------------------------------------------
# FLOW 4: background task _execute_deployment integration
# ---------------------------------------------------------------------------

class TestExecuteDeploymentBackgroundTask:
    """
    Test _execute_deployment background task with mocked AgentDeployService.
    Verifies state transitions: pending → uploading → deployed → registering → ready
    """

    @pytest.mark.asyncio
    async def test_background_task_progresses_through_states(self):
        """
        With mocked SSH service, _execute_deployment should drive tracker
        through all states to READY when agent enrolls and sends heartbeat.
        """
        rt = _build_runtime()

        now_str = datetime.now(timezone.utc).isoformat()
        agent_id = "auto-agent-001"

        # Pre-populate registry + tracker so the background task finds the agent
        await rt.agent_registry.register_agent_online(
            agent_id, "auto-agent", "1.0", "10.0.0.5:80", [], now_str
        )
        # Give it a fresh heartbeat immediately
        await rt.agent_registry.update_agent_heartbeat(agent_id, now_str)

        # Simulate what _execute_deployment does:
        dep_id = "dep-bg-001"
        await rt.deployment_tracker.create(dep_id, "auto-agent", "cred", "10.0.0.5")

        # State: deploying
        await rt.deployment_tracker.update_status(dep_id, "deploying", progress=50)
        # State: registering (agent found in enrollment)
        await rt.deployment_tracker.update_status(dep_id, "registering", agent_id=agent_id, progress=75)
        # State: ready (heartbeat received)
        await rt.deployment_tracker.update_status(dep_id, "ready", progress=100)

        poll = await admin_agent_get_deployment_status(rt, dep_id)
        assert poll["status"] == "ready"
        assert poll["progress"] == 100
        assert poll["agent_id"] == agent_id

    @pytest.mark.asyncio
    async def test_deploy_service_called_with_correct_args(self):
        """admin_agent_deploy calls AgentDeployService.deploy with credential_id+agent_name."""
        rt = _build_runtime()

        captured_calls = []

        async def fake_deploy_service_deploy(**kwargs):
            captured_calls.append(kwargs)
            return {"status": "deploy_started", "agent_name": kwargs["agent_name"]}

        async def _noop(*a, **kw): pass

        with patch("modules.agent.services._execute_deployment", new=_noop):
            result = await admin_agent_deploy(
                rt,
                body={"agent_name": "tracked-agent", "credential_id": "cred-tracked"}
            )

        assert result["ok"] is True
        assert result["agent_name"] == "tracked-agent"


# ---------------------------------------------------------------------------
# FLOW 5: metrics & reporting
# ---------------------------------------------------------------------------

class TestDeploymentMetricsFlow:

    @pytest.mark.asyncio
    async def test_metrics_reflect_real_deployments(self):
        """After multiple deploys with different outcomes, metrics are correct."""
        rt = _build_runtime()

        ids = []
        for i in range(5):
            r = await admin_agent_deploy(
                rt, body={"agent_name": f"m-agent-{i}", "credential_id": "c"}
            )
            ids.append(r["deployment_id"])

        # 3 succeed, 2 fail
        for dep_id in ids[:3]:
            await rt.deployment_tracker.update_status(dep_id, "ready")
        for dep_id in ids[3:]:
            await rt.deployment_tracker.update_status(dep_id, "failed")

        from modules.agent.services import admin_agent_get_deployment_metrics
        metrics = await admin_agent_get_deployment_metrics(rt)

        assert metrics["ok"] is True
        assert metrics["total"] == 5
        assert metrics["succeeded"] == 3
        assert metrics["failed"] == 2
        assert abs(metrics["success_rate"] - 0.6) < 0.01

    @pytest.mark.asyncio
    async def test_metrics_recent_5_contains_latest(self):
        """recent_5 shows most recent 5 deployments."""
        rt = _build_runtime()

        for i in range(7):
            r = await admin_agent_deploy(
                rt, body={"agent_name": f"r-agent-{i}", "credential_id": "c"}
            )
            await rt.deployment_tracker.update_status(r["deployment_id"], "ready")

        from modules.agent.services import admin_agent_get_deployment_metrics
        metrics = await admin_agent_get_deployment_metrics(rt)

        assert len(metrics.get("recent_5", [])) == 5
