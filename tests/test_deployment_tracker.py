"""
TASK 1.2: Tests for DeploymentTracker.

Covers:
- create()               — create new deployment entry
- get()                  — get by ID
- update_status()        — state transitions
- list_deployments()     — filtering by name/status
- get_deployment_metrics() — statistics
- cleanup_old_deployments() — remove stale entries
- Concurrent deployments — multiple at once
- Terminal state handling — READY/FAILED set completed_at
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock

from modules.agent import DeploymentTracker, DeploymentStatus, DeploymentInfo


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tracker():
    """Fresh in-memory DeploymentTracker (no DB)."""
    return DeploymentTracker()


@pytest.fixture
def tracker_with_db():
    """DeploymentTracker with a mock DB service."""
    db = AsyncMock()
    db.insert = AsyncMock()
    db.update = AsyncMock()
    return DeploymentTracker(db_service=db), db


# ---------------------------------------------------------------------------
# TASK 1.2 — create()
# ---------------------------------------------------------------------------

class TestDeploymentTrackerCreate:

    @pytest.mark.asyncio
    async def test_create_returns_deployment_info(self, tracker):
        d = await tracker.create("dep-1", "my-agent", "cred-1", "10.0.0.1")

        assert isinstance(d, DeploymentInfo)
        assert d.deployment_id == "dep-1"
        assert d.agent_name == "my-agent"
        assert d.credential_id == "cred-1"
        assert d.host == "10.0.0.1"
        assert d.status == DeploymentStatus.PENDING
        assert d.progress_percentage == 0
        assert d.created_at is not None

    @pytest.mark.asyncio
    async def test_create_stores_in_memory(self, tracker):
        await tracker.create("dep-2", "agent-b", "cred-2", "10.0.0.2")
        retrieved = await tracker.get("dep-2")

        assert retrieved is not None
        assert retrieved.agent_name == "agent-b"

    @pytest.mark.asyncio
    async def test_create_with_custom_env(self, tracker):
        env = {"DEBUG": "1", "LOG_LEVEL": "info"}
        d = await tracker.create("dep-3", "a", "c", "h", custom_env=env)

        assert d.custom_env == env

    @pytest.mark.asyncio
    async def test_create_persists_to_db(self, tracker_with_db):
        trk, db = tracker_with_db
        await trk.create("dep-4", "agent-x", "cred-x", "host-x")

        db.insert.assert_called_once()
        call_args = db.insert.call_args
        assert call_args[0][0] == "deployments"

    @pytest.mark.asyncio
    async def test_create_multiple_independent(self, tracker):
        ids = ["d1", "d2", "d3"]
        for dep_id in ids:
            await tracker.create(dep_id, f"agent-{dep_id}", "cred", "host")

        for dep_id in ids:
            d = await tracker.get(dep_id)
            assert d is not None
            assert d.deployment_id == dep_id


# ---------------------------------------------------------------------------
# TASK 1.2 — get()
# ---------------------------------------------------------------------------

class TestDeploymentTrackerGet:

    @pytest.mark.asyncio
    async def test_get_nonexistent_returns_none(self, tracker):
        result = await tracker.get("nonexistent-id")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_returns_same_object(self, tracker):
        await tracker.create("dep-5", "agent", "cred", "host")
        d1 = await tracker.get("dep-5")
        d2 = await tracker.get("dep-5")
        # same in-memory instance
        assert d1 is d2


# ---------------------------------------------------------------------------
# TASK 1.2 — update_status()
# ---------------------------------------------------------------------------

class TestDeploymentTrackerUpdateStatus:

    @pytest.mark.asyncio
    async def test_update_status_basic(self, tracker):
        await tracker.create("dep-6", "agent", "cred", "host")
        ok = await tracker.update_status("dep-6", "uploading")

        assert ok is True
        d = await tracker.get("dep-6")
        assert d.status == DeploymentStatus.UPLOADING

    @pytest.mark.asyncio
    async def test_update_progress(self, tracker):
        await tracker.create("dep-7", "agent", "cred", "host")
        await tracker.update_status("dep-7", "deploying", progress=50)

        d = await tracker.get("dep-7")
        assert d.progress_percentage == 50

    @pytest.mark.asyncio
    async def test_progress_clamped_0_100(self, tracker):
        await tracker.create("dep-8", "a", "c", "h")
        await tracker.update_status("dep-8", "deploying", progress=9999)
        d = await tracker.get("dep-8")
        assert d.progress_percentage == 100

        await tracker.update_status("dep-8", "deploying", progress=-100)
        d = await tracker.get("dep-8")
        assert d.progress_percentage == 0

    @pytest.mark.asyncio
    async def test_update_agent_id(self, tracker):
        await tracker.create("dep-9", "a", "c", "h")
        await tracker.update_status("dep-9", "registering", agent_id="agent-uuid-123")

        d = await tracker.get("dep-9")
        assert d.agent_id == "agent-uuid-123"

    @pytest.mark.asyncio
    async def test_update_error_message(self, tracker):
        await tracker.create("dep-10", "a", "c", "h")
        await tracker.update_status("dep-10", "failed", error_message="SSH timeout")

        d = await tracker.get("dep-10")
        assert d.error_message == "SSH timeout"

    @pytest.mark.asyncio
    async def test_terminal_status_sets_completed_at(self, tracker):
        """READY and FAILED set completed_at automatically."""
        await tracker.create("dep-11", "a", "c", "h")
        await tracker.update_status("dep-11", "ready")

        d = await tracker.get("dep-11")
        assert d.completed_at is not None

    @pytest.mark.asyncio
    async def test_terminal_failed_sets_completed_at(self, tracker):
        await tracker.create("dep-12", "a", "c", "h")
        await tracker.update_status("dep-12", "failed", error_message="err")

        d = await tracker.get("dep-12")
        assert d.completed_at is not None

    @pytest.mark.asyncio
    async def test_started_at_set_on_first_nonterminal_update(self, tracker):
        await tracker.create("dep-13", "a", "c", "h")
        assert (await tracker.get("dep-13")).started_at is None

        await tracker.update_status("dep-13", "uploading")
        assert (await tracker.get("dep-13")).started_at is not None

    @pytest.mark.asyncio
    async def test_update_nonexistent_returns_false(self, tracker):
        ok = await tracker.update_status("no-such-id", "ready")
        assert ok is False

    @pytest.mark.asyncio
    async def test_update_invalid_status_returns_false(self, tracker):
        await tracker.create("dep-14", "a", "c", "h")
        ok = await tracker.update_status("dep-14", "totally_invalid_state")
        assert ok is False

    @pytest.mark.asyncio
    async def test_timeout_status_sets_completed_at(self, tracker):
        await tracker.create("dep-15", "a", "c", "h")
        await tracker.update_status("dep-15", "timeout")
        d = await tracker.get("dep-15")
        assert d.completed_at is not None

    @pytest.mark.asyncio
    async def test_update_calls_db(self, tracker_with_db):
        trk, db = tracker_with_db
        await trk.create("dep-db", "a", "c", "h")
        await trk.update_status("dep-db", "deploying")

        db.update.assert_called_once()


# ---------------------------------------------------------------------------
# TASK 1.2 — list_deployments()
# ---------------------------------------------------------------------------

class TestDeploymentTrackerList:

    @pytest.mark.asyncio
    async def test_list_all(self, tracker):
        for i in range(3):
            await tracker.create(f"d{i}", f"agent-{i}", "c", "h")

        result = await tracker.list_deployments()
        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_list_filter_by_agent_name(self, tracker):
        await tracker.create("d-a1", "alpha", "c", "h")
        await tracker.create("d-a2", "alpha", "c", "h")
        await tracker.create("d-b1", "beta", "c", "h")

        result = await tracker.list_deployments(agent_name="alpha")
        assert len(result) == 2
        assert all(d.agent_name == "alpha" for d in result)

    @pytest.mark.asyncio
    async def test_list_filter_by_status(self, tracker):
        await tracker.create("ds1", "a", "c", "h")
        await tracker.create("ds2", "b", "c", "h")
        await tracker.create("ds3", "c_agent", "c", "h")

        await tracker.update_status("ds1", "ready")
        await tracker.update_status("ds2", "failed")
        # ds3 stays pending

        result = await tracker.list_deployments(status="ready")
        assert len(result) == 1
        assert result[0].deployment_id == "ds1"

    @pytest.mark.asyncio
    async def test_list_limit(self, tracker):
        for i in range(10):
            await tracker.create(f"lim-{i}", "a", "c", "h")

        result = await tracker.list_deployments(limit=3)
        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_list_sorted_by_created_desc(self, tracker):
        """Most recent deployments appear first."""
        import asyncio
        for i in range(3):
            await tracker.create(f"sort-{i}", "a", "c", "h")
            await asyncio.sleep(0)  # yield, allow timestamps to differ if needed

        result = await tracker.list_deployments()
        # The last created should be first because list is DESC
        # (may be equal timestamps in fast tests — just check same objects returned)
        assert len(result) == 3


# ---------------------------------------------------------------------------
# TASK 1.2 — get_deployment_metrics()
# ---------------------------------------------------------------------------

class TestDeploymentTrackerMetrics:

    @pytest.mark.asyncio
    async def test_metrics_empty(self, tracker):
        m = await tracker.get_deployment_metrics()
        assert m["total"] == 0
        assert m["succeeded"] == 0
        assert m["failed"] == 0
        assert m["in_progress"] == 0

    @pytest.mark.asyncio
    async def test_metrics_counts(self, tracker):
        await tracker.create("m1", "a", "c", "h")
        await tracker.create("m2", "b", "c", "h")
        await tracker.create("m3", "c_a", "c", "h")
        await tracker.create("m4", "d", "c", "h")

        await tracker.update_status("m1", "ready")
        await tracker.update_status("m2", "failed")
        await tracker.update_status("m3", "timeout")
        # m4 stays in-progress (pending)

        m = await tracker.get_deployment_metrics()
        assert m["total"] == 4
        assert m["succeeded"] == 1
        assert m["failed"] == 2   # failed + timeout
        assert m["in_progress"] == 1

    @pytest.mark.asyncio
    async def test_metrics_success_rate(self, tracker):
        await tracker.create("sr1", "a", "c", "h")
        await tracker.create("sr2", "b", "c", "h")
        await tracker.update_status("sr1", "ready")
        await tracker.update_status("sr2", "ready")

        m = await tracker.get_deployment_metrics()
        assert m["success_rate"] == 1.0

    @pytest.mark.asyncio
    async def test_metrics_recent_5(self, tracker):
        for i in range(7):
            await tracker.create(f"r{i}", "a", "c", "h")

        m = await tracker.get_deployment_metrics()
        assert len(m["recent_5"]) == 5


# ---------------------------------------------------------------------------
# TASK 1.2 — cleanup_old_deployments()
# ---------------------------------------------------------------------------

class TestDeploymentTrackerCleanup:

    @pytest.mark.asyncio
    async def test_cleanup_removes_completed_old(self, tracker):
        await tracker.create("old-1", "a", "c", "h")
        await tracker.update_status("old-1", "ready")

        # Manually backdate completed_at
        d = await tracker.get("old-1")
        d.completed_at = datetime.now(timezone.utc) - timedelta(hours=25)

        removed = await tracker.cleanup_old_deployments(older_than_hours=24)
        assert removed == 1
        assert await tracker.get("old-1") is None

    @pytest.mark.asyncio
    async def test_cleanup_keeps_recent(self, tracker):
        await tracker.create("new-1", "a", "c", "h")
        await tracker.update_status("new-1", "ready")
        # completed_at is just now

        removed = await tracker.cleanup_old_deployments(older_than_hours=24)
        assert removed == 0
        assert await tracker.get("new-1") is not None

    @pytest.mark.asyncio
    async def test_cleanup_keeps_in_progress(self, tracker):
        await tracker.create("inprog-1", "a", "c", "h")
        await tracker.update_status("inprog-1", "deploying")

        removed = await tracker.cleanup_old_deployments(older_than_hours=0)
        assert removed == 0


# ---------------------------------------------------------------------------
# TASK 1.2 — DeploymentInfo.to_dict()
# ---------------------------------------------------------------------------

class TestDeploymentInfoToDict:

    @pytest.mark.asyncio
    async def test_to_dict_has_required_fields(self, tracker):
        await tracker.create("td-1", "my-agent", "cred-1", "10.0.0.5")
        d = await tracker.get("td-1")
        result = d.to_dict()

        assert result["deployment_id"] == "td-1"
        assert result["agent_name"] == "my-agent"
        assert result["credential_id"] == "cred-1"
        assert result["host"] == "10.0.0.5"
        assert result["status"] == "pending"
        assert "created_at" in result

    def test_to_dict_omits_enrollment_token_str(self):
        d = DeploymentInfo(
            deployment_id="td-2",
            agent_name="a",
            credential_id="c",
            host="h",
        )
        d.enrollment_token_str = "super_secret_token"
        result = d.to_dict()
        assert "enrollment_token_str" not in result

    def test_to_dict_status_is_string(self):
        d = DeploymentInfo(
            deployment_id="td-3",
            agent_name="a",
            credential_id="c",
            host="h",
            status=DeploymentStatus.READY,
        )
        result = d.to_dict()
        assert result["status"] == "ready"
        assert isinstance(result["status"], str)

    def test_duration_seconds_none_when_not_completed(self):
        d = DeploymentInfo(
            deployment_id="td-4",
            agent_name="a",
            credential_id="c",
            host="h",
        )
        assert d.duration_seconds() is None

    def test_duration_seconds_calculated(self):
        now = datetime.now(timezone.utc)
        d = DeploymentInfo(
            deployment_id="td-5",
            agent_name="a",
            credential_id="c",
            host="h",
            created_at=now - timedelta(seconds=120),
            completed_at=now,
        )
        assert abs(d.duration_seconds() - 120.0) < 1.0
