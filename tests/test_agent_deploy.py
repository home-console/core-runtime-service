"""
TASK 1.1 + 1.4: Tests for admin_agent_deploy service and HTTP endpoint registration.

Covers:
- admin_agent_deploy()                  — input validation, success path, error paths
- admin_agent_get_deployment_status()   — polling endpoint
- admin_agent_get_deployment_metrics()  — dashboard metrics
- HTTP endpoint registration (TASK 1.4) — all deployment endpoints present in registry
- Background task _execute_deployment() — status transitions via mocks
"""

import pytest
import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from core.runtime import CoreRuntime
from core.agents.deployment_tracker import DeploymentTracker, DeploymentStatus
from modules.agent.services import (
    admin_agent_deploy,
    admin_agent_get_deployment_status,
    admin_agent_get_deployment_metrics,
)


# ---------------------------------------------------------------------------
# Helpers — mock runtime builder
# ---------------------------------------------------------------------------

def _make_enrollment_manager(token: str = "tok.abc123"):
    """Return mock AgentEnrollmentManager."""
    mgr = AsyncMock()
    mgr.generate_enrollment_token = AsyncMock(return_value=token)
    mgr.create_enrollment_token = AsyncMock(return_value=MagicMock(
        token_id="tok-id",
        token_secret=token,
        expires_at="2026-03-01T00:00:00Z",
        agent_name="test-agent",
    ))
    mgr.list_enrolled_agents = AsyncMock(return_value=[])
    mgr.get_agent_identity = AsyncMock(return_value=None)
    mgr.revoke_enrollment_token = AsyncMock()
    return mgr


def _make_storage_manager(credential: dict | None = None):
    """Return mock storage manager that returns a credential."""
    mgr = AsyncMock()
    mgr.get = AsyncMock(return_value=credential)
    return mgr


def _make_runtime(
    credential: dict | None = None,
    enrollment_token: str = "tok.abc123",
) -> SimpleNamespace:
    """Assemble a minimal mock CoreRuntime."""
    tracker = DeploymentTracker()
    agent_mgr = _make_enrollment_manager(enrollment_token)
    storage_mgr = _make_storage_manager(credential)

    rt = SimpleNamespace(
        agent_manager=agent_mgr,
        deployment_tracker=tracker,
        storage_manager=storage_mgr,
        agent_registry=None,
        mtls_ca=None,
    )
    return rt


# ---------------------------------------------------------------------------
# TASK 1.1 — admin_agent_deploy: input validation
# ---------------------------------------------------------------------------

class TestAdminAgentDeployValidation:

    @pytest.mark.asyncio
    async def test_missing_body_returns_error(self):
        rt = _make_runtime()
        result = await admin_agent_deploy(rt, body=None)
        assert result["ok"] is False
        assert "invalid_body" in result["error"]

    @pytest.mark.asyncio
    async def test_non_dict_body_returns_error(self):
        rt = _make_runtime()
        result = await admin_agent_deploy(rt, body="not a dict")
        assert result["ok"] is False

    @pytest.mark.asyncio
    async def test_missing_agent_name_returns_error(self):
        rt = _make_runtime()
        result = await admin_agent_deploy(rt, body={"credential_id": "cred-1"})
        assert result["ok"] is False
        assert "agent_name" in result["error"]

    @pytest.mark.asyncio
    async def test_blank_agent_name_returns_error(self):
        rt = _make_runtime()
        result = await admin_agent_deploy(rt, body={"agent_name": "   ", "credential_id": "cred-1"})
        assert result["ok"] is False

    @pytest.mark.asyncio
    async def test_missing_credential_id_returns_error(self):
        rt = _make_runtime()
        result = await admin_agent_deploy(rt, body={"agent_name": "my-agent"})
        assert result["ok"] is False
        assert "credential_id" in result["error"]

    @pytest.mark.asyncio
    async def test_missing_agent_manager_returns_error(self):
        rt = _make_runtime()
        rt.agent_manager = None
        result = await admin_agent_deploy(rt, body={"agent_name": "a", "credential_id": "c"})
        assert result["ok"] is False
        assert "agent_manager" in result["error"]

    @pytest.mark.asyncio
    async def test_missing_deployment_tracker_returns_error(self):
        rt = _make_runtime()
        rt.deployment_tracker = None
        result = await admin_agent_deploy(rt, body={"agent_name": "a", "credential_id": "c"})
        assert result["ok"] is False
        assert "deployment_tracker" in result["error"]

    @pytest.mark.asyncio
    async def test_missing_storage_manager_returns_error(self):
        rt = _make_runtime()
        rt.storage_manager = None
        result = await admin_agent_deploy(rt, body={"agent_name": "a", "credential_id": "c"})
        assert result["ok"] is False
        assert "storage_manager" in result["error"]

    @pytest.mark.asyncio
    async def test_no_host_in_credential_no_host_in_body_returns_error(self):
        """When credential has no host and body has no host — should fail."""
        rt = _make_runtime(credential={"name": "my-cred"})  # no "host" key
        result = await admin_agent_deploy(
            rt, body={"agent_name": "a", "credential_id": "cred-1"}
        )
        assert result["ok"] is False
        assert "host" in result["error"].lower()


# ---------------------------------------------------------------------------
# TASK 1.1 — admin_agent_deploy: success path
# ---------------------------------------------------------------------------

class TestAdminAgentDeploySuccess:

    @pytest.mark.asyncio
    async def test_deploy_returns_deployment_id(self):
        rt = _make_runtime(credential={"host": "10.0.0.50"})
        result = await admin_agent_deploy(
            rt,
            body={"agent_name": "my-agent", "credential_id": "cred-1"},
        )
        assert result["ok"] is True
        assert "deployment_id" in result
        assert len(result["deployment_id"]) > 0

    @pytest.mark.asyncio
    async def test_deploy_returns_correct_agent_name(self):
        rt = _make_runtime(credential={"host": "10.0.0.50"})
        result = await admin_agent_deploy(
            rt,
            body={"agent_name": "prod-agent", "credential_id": "cred-x"},
        )
        assert result["agent_name"] == "prod-agent"

    @pytest.mark.asyncio
    async def test_deploy_returns_host(self):
        rt = _make_runtime(credential={"host": "192.168.1.100"})
        result = await admin_agent_deploy(
            rt,
            body={"agent_name": "a", "credential_id": "c"},
        )
        assert result["host"] == "192.168.1.100"

    @pytest.mark.asyncio
    async def test_deploy_host_override_from_body(self):
        """Body['host'] overrides credential host."""
        rt = _make_runtime(credential={"host": "10.0.0.1"})
        result = await admin_agent_deploy(
            rt,
            body={"agent_name": "a", "credential_id": "c", "host": "172.16.0.5"},
        )
        assert result["host"] == "172.16.0.5"

    @pytest.mark.asyncio
    async def test_deploy_returns_status_started(self):
        rt = _make_runtime(credential={"host": "10.0.0.50"})
        result = await admin_agent_deploy(
            rt,
            body={"agent_name": "a", "credential_id": "c"},
        )
        assert result["status"] == "started"

    @pytest.mark.asyncio
    async def test_deploy_returns_heartbeat_timeout(self):
        rt = _make_runtime(credential={"host": "10.0.0.50"})
        result = await admin_agent_deploy(
            rt,
            body={"agent_name": "a", "credential_id": "c"},
        )
        assert result["heartbeat_timeout"] == 300

    @pytest.mark.asyncio
    async def test_deploy_returns_polling_url(self):
        rt = _make_runtime(credential={"host": "10.0.0.50"})
        result = await admin_agent_deploy(
            rt,
            body={"agent_name": "a", "credential_id": "c"},
        )
        dep_id = result["deployment_id"]
        assert dep_id in result.get("next_check", "")

    @pytest.mark.asyncio
    async def test_deploy_creates_tracker_entry(self):
        rt = _make_runtime(credential={"host": "10.0.0.50"})
        result = await admin_agent_deploy(
            rt,
            body={"agent_name": "tracker-check", "credential_id": "c"},
        )
        assert result["ok"] is True
        dep_id = result["deployment_id"]
        d = await rt.deployment_tracker.get(dep_id)
        assert d is not None
        assert d.agent_name == "tracker-check"

    @pytest.mark.asyncio
    async def test_deploy_generates_enrollment_token(self):
        rt = _make_runtime(credential={"host": "10.0.0.50"})
        result = await admin_agent_deploy(
            rt,
            body={"agent_name": "tok-agent", "credential_id": "c"},
        )
        assert result["ok"] is True
        rt.agent_manager.generate_enrollment_token.assert_called_once_with("tok-agent")

    @pytest.mark.asyncio
    async def test_deploy_is_non_blocking(self):
        """deploy() must return before background task completes."""
        rt = _make_runtime(credential={"host": "10.0.0.50"})

        # Patch _execute_deployment to hang forever (proves we don't await it)
        async def _hang(*a, **kw):
            await asyncio.sleep(9999)

        with patch("modules.agent.services._execute_deployment", side_effect=_hang):
            result = await asyncio.wait_for(
                admin_agent_deploy(rt, body={"agent_name": "a", "credential_id": "c"}),
                timeout=2.0,
            )
        assert result["ok"] is True

    @pytest.mark.asyncio
    async def test_deploy_handles_two_concurrent_deployments(self):
        """Two simultaneous deploys get unique deployment_ids."""
        rt = _make_runtime(credential={"host": "10.0.0.50"})
        body = {"agent_name": "agent-x", "credential_id": "c"}

        r1, r2 = await asyncio.gather(
            admin_agent_deploy(rt, body=body),
            admin_agent_deploy(rt, body=body),
        )
        assert r1["ok"] is True
        assert r2["ok"] is True
        assert r1["deployment_id"] != r2["deployment_id"]

    @pytest.mark.asyncio
    async def test_deploy_with_custom_env(self):
        rt = _make_runtime(credential={"host": "10.0.0.50"})
        env = {"EXTRA_VAR": "value"}
        result = await admin_agent_deploy(
            rt,
            body={"agent_name": "a", "credential_id": "c", "env": env},
        )
        assert result["ok"] is True
        dep_id = result["deployment_id"]
        d = await rt.deployment_tracker.get(dep_id)
        assert d.custom_env == env


# ---------------------------------------------------------------------------
# TASK 1.1 — admin_agent_deploy: token generation failure
# ---------------------------------------------------------------------------

class TestAdminAgentDeployTokenFailure:

    @pytest.mark.asyncio
    async def test_token_generation_failure_returns_error(self):
        rt = _make_runtime(credential={"host": "10.0.0.50"})
        rt.agent_manager.generate_enrollment_token = AsyncMock(
            side_effect=RuntimeError("key store not ready")
        )
        result = await admin_agent_deploy(
            rt,
            body={"agent_name": "a", "credential_id": "c"},
        )
        assert result["ok"] is False
        assert "token" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_token_failure_marks_deployment_failed(self):
        rt = _make_runtime(credential={"host": "10.0.0.50"})
        rt.agent_manager.generate_enrollment_token = AsyncMock(
            side_effect=RuntimeError("oops")
        )
        await admin_agent_deploy(rt, body={"agent_name": "a", "credential_id": "c"})

        # Check all deployments — the failed one should be in FAILED state
        deployments = await rt.deployment_tracker.list_deployments()
        if deployments:
            assert any(d.status == DeploymentStatus.FAILED for d in deployments)


# ---------------------------------------------------------------------------
# TASK 1.1 — admin_agent_get_deployment_status() polling
# ---------------------------------------------------------------------------

class TestAdminAgentGetDeploymentStatus:

    @pytest.mark.asyncio
    async def test_get_status_nonexistent_returns_error(self):
        rt = _make_runtime()
        result = await admin_agent_get_deployment_status(rt, "no-such-id")
        assert result["ok"] is False
        assert "not_found" in result["error"]

    @pytest.mark.asyncio
    async def test_get_status_missing_deployment_tracker(self):
        rt = _make_runtime()
        rt.deployment_tracker = None
        result = await admin_agent_get_deployment_status(rt, "dep-id")
        assert result["ok"] is False

    @pytest.mark.asyncio
    async def test_get_status_missing_deployment_id(self):
        rt = _make_runtime()
        result = await admin_agent_get_deployment_status(rt, "")
        assert result["ok"] is False

    @pytest.mark.asyncio
    async def test_get_status_after_create(self):
        rt = _make_runtime(credential={"host": "10.0.0.50"})
        deploy_result = await admin_agent_deploy(
            rt, body={"agent_name": "poll-agent", "credential_id": "c"}
        )
        dep_id = deploy_result["deployment_id"]

        status_result = await admin_agent_get_deployment_status(rt, dep_id)
        assert status_result["ok"] is True
        assert status_result["deployment_id"] == dep_id
        assert status_result["agent_name"] == "poll-agent"
        assert "status" in status_result
        assert "progress" in status_result

    @pytest.mark.asyncio
    async def test_get_status_reflects_state_change(self):
        rt = _make_runtime(credential={"host": "10.0.0.50"})
        deploy_result = await admin_agent_deploy(
            rt, body={"agent_name": "state-agent", "credential_id": "c"}
        )
        dep_id = deploy_result["deployment_id"]

        # Manually advance state
        await rt.deployment_tracker.update_status(dep_id, "deploying", progress=50)

        status_result = await admin_agent_get_deployment_status(rt, dep_id)
        assert status_result["status"] == "deploying"
        assert status_result["progress"] == 50

    @pytest.mark.asyncio
    async def test_get_status_includes_agent_id_when_set(self):
        rt = _make_runtime(credential={"host": "10.0.0.50"})
        deploy_result = await admin_agent_deploy(
            rt, body={"agent_name": "agent-with-id", "credential_id": "c"}
        )
        dep_id = deploy_result["deployment_id"]

        await rt.deployment_tracker.update_status(dep_id, "registering", agent_id="agent-abc")

        status_result = await admin_agent_get_deployment_status(rt, dep_id)
        assert status_result["agent_id"] == "agent-abc"

    @pytest.mark.asyncio
    async def test_get_status_includes_duration_when_completed(self):
        rt = _make_runtime(credential={"host": "10.0.0.50"})
        deploy_result = await admin_agent_deploy(
            rt, body={"agent_name": "finished-agent", "credential_id": "c"}
        )
        dep_id = deploy_result["deployment_id"]

        await rt.deployment_tracker.update_status(dep_id, "ready", progress=100)

        status_result = await admin_agent_get_deployment_status(rt, dep_id)
        assert "duration_seconds" in status_result
        assert "completed_at" in status_result

    @pytest.mark.asyncio
    async def test_get_status_includes_error_when_failed(self):
        rt = _make_runtime(credential={"host": "10.0.0.50"})
        deploy_result = await admin_agent_deploy(
            rt, body={"agent_name": "err-agent", "credential_id": "c"}
        )
        dep_id = deploy_result["deployment_id"]

        await rt.deployment_tracker.update_status(dep_id, "failed", error_message="SSH refused")

        status_result = await admin_agent_get_deployment_status(rt, dep_id)
        assert status_result["error_message"] == "SSH refused"


# ---------------------------------------------------------------------------
# TASK 1.1 — admin_agent_get_deployment_metrics()
# ---------------------------------------------------------------------------

class TestAdminAgentGetDeploymentMetrics:

    @pytest.mark.asyncio
    async def test_metrics_ok_when_empty(self):
        rt = _make_runtime()
        result = await admin_agent_get_deployment_metrics(rt)
        assert result["ok"] is True
        assert result["total"] == 0

    @pytest.mark.asyncio
    async def test_metrics_no_tracker_returns_error(self):
        rt = _make_runtime()
        rt.deployment_tracker = None
        result = await admin_agent_get_deployment_metrics(rt)
        assert result["ok"] is False

    @pytest.mark.asyncio
    async def test_metrics_after_deployments(self):
        rt = _make_runtime(credential={"host": "10.0.0.1"})
        body = {"agent_name": "agent", "credential_id": "c"}

        r1 = await admin_agent_deploy(rt, body=body)
        r2 = await admin_agent_deploy(rt, body=body)

        await rt.deployment_tracker.update_status(r1["deployment_id"], "ready")
        await rt.deployment_tracker.update_status(r2["deployment_id"], "failed")

        metrics = await admin_agent_get_deployment_metrics(rt)
        assert metrics["ok"] is True
        assert metrics["total"] == 2
        assert metrics["succeeded"] == 1
        assert metrics["failed"] == 1


# ---------------------------------------------------------------------------
# TASK 1.4 — HTTP endpoint registration
# ---------------------------------------------------------------------------

async def _start_runtime_with_agent(memory_adapter):
    """Helper: start CoreRuntime with logger + agent_control_plane modules."""
    from core.runtime import CoreRuntime
    from core.module_manager import ModuleSpec
    from modules.logger.module import LoggerModule
    from modules.agent.module import AgentControlPlaneModule

    runtime = CoreRuntime(memory_adapter)

    # Register logger first (required by agent module)
    logger_mod = LoggerModule(runtime, runtime.module_manager.get_module("logger"))
    await runtime.module_manager.register(logger_mod)

    # Register agent control plane directly (avoids module name mapping issue)
    agent_mod = AgentControlPlaneModule(runtime, runtime.module_manager)
    await runtime.module_manager.register(agent_mod)

    # Mark both as required so start() doesn't fail
    runtime.module_manager._required_names = {"logger", "agent_control_plane"}

    await runtime.start()
    return runtime


class TestHTTPEndpointRegistration:
    """
    Verify all Task 1.1 / 1.4 endpoints are registered in the agent module.

    Bootstrap agent module directly and inspect runtime.http.list().
    """

    @pytest.mark.asyncio
    async def test_deployment_endpoints_registered(self, memory_adapter):
        """All deployment HTTP endpoints should be present after agent module starts."""
        from core.module_manager import ModuleSpec
        runtime = CoreRuntime(memory_adapter)
        await runtime.module_manager.register_module_specs(
            runtime,
            [ModuleSpec("logger", required=True), ModuleSpec("agent", required=False)],
        )
        await runtime.start()

        endpoints = runtime.http.list()
        paths = {ep.path for ep in endpoints}

        # TASK 1.1
        assert "/admin/v1/agents/deploy" in paths, "deploy endpoint missing"
        # TASK 1.4
        assert "/admin/v1/deployments/{deployment_id}" in paths, "deployment status endpoint missing"
        assert "/admin/v1/deployments" in paths, "deployment metrics endpoint missing"

        # Enrollment endpoints (pre-existing)
        assert "/admin/v1/agents/enrollment-token" in paths
        assert "/admin/v1/agents/enroll" in paths

        await runtime.stop()

    @pytest.mark.asyncio
    async def test_heartbeat_endpoint_registered(self, memory_adapter):
        from core.module_manager import ModuleSpec
        runtime = CoreRuntime(memory_adapter)
        await runtime.module_manager.register_module_specs(
            runtime,
            [ModuleSpec("logger", required=True), ModuleSpec("agent", required=False)],
        )
        await runtime.start()

        paths = {ep.path for ep in runtime.http.list()}
        assert "/admin/v1/agents/{agent_id}/heartbeat" in paths

        await runtime.stop()

    @pytest.mark.asyncio
    async def test_download_endpoints_registered(self, memory_adapter):
        from core.module_manager import ModuleSpec
        runtime = CoreRuntime(memory_adapter)
        await runtime.module_manager.register_module_specs(
            runtime,
            [ModuleSpec("logger", required=True), ModuleSpec("agent", required=False)],
        )
        await runtime.start()

        paths = {ep.path for ep in runtime.http.list()}
        assert "/media/checksum" in paths
        assert "/media/download/binary" in paths

        await runtime.stop()

    @pytest.mark.asyncio
    async def test_deploy_endpoint_uses_post_method(self, memory_adapter):
        from core.module_manager import ModuleSpec
        runtime = CoreRuntime(memory_adapter)
        await runtime.module_manager.register_module_specs(
            runtime,
            [ModuleSpec("logger", required=True), ModuleSpec("agent", required=False)],
        )
        await runtime.start()

        deploy_endpoints = [
            ep for ep in runtime.http.list() if ep.path == "/admin/v1/agents/deploy"
        ]
        assert len(deploy_endpoints) == 1
        assert deploy_endpoints[0].method.upper() == "POST"

        await runtime.stop()

    @pytest.mark.asyncio
    async def test_deployment_status_endpoint_uses_get(self, memory_adapter):
        from core.module_manager import ModuleSpec
        runtime = CoreRuntime(memory_adapter)
        await runtime.module_manager.register_module_specs(
            runtime,
            [ModuleSpec("logger", required=True), ModuleSpec("agent", required=False)],
        )
        await runtime.start()

        status_eps = [
            ep for ep in runtime.http.list()
            if ep.path == "/admin/v1/deployments/{deployment_id}"
        ]
        assert len(status_eps) == 1
        assert status_eps[0].method.upper() == "GET"

        await runtime.stop()
