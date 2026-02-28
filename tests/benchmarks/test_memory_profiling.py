"""
Memory Profiling Benchmarks — Day 5
Uses tracemalloc to detect memory leaks and measure allocation patterns
during bulk Agent operations.
"""

import tracemalloc
import gc
import asyncio
import pytest
from datetime import datetime, timezone
from types import SimpleNamespace

from core.agents.deployment_tracker import DeploymentTracker
from core.agent.registry import AgentRegistry


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class _FakeSS:
    def __init__(self):
        self._d = {}
    async def put(self, k, v): self._d[k] = v
    async def get(self, k): return self._d.get(k)
    async def delete(self, k): self._d.pop(k, None)
    async def exists(self, k): return k in self._d
    async def list_secrets(self): return list(self._d.keys())
    async def get_metadata(self, k): return None


def _kb(bytes_val: int) -> float:
    return bytes_val / 1024


# ---------------------------------------------------------------------------
# DeploymentTracker memory profiling
# ---------------------------------------------------------------------------

class TestDeploymentTrackerMemory:

    @pytest.mark.asyncio
    async def test_100_deployments_memory_under_5mb(self):
        """
        Creating 100 deployments should consume < 5 MB.
        """
        tracker = DeploymentTracker()
        gc.collect()
        tracemalloc.start()
        snapshot_before = tracemalloc.take_snapshot()

        for i in range(100):
            dep_id = f"mem-dep-{i:04d}"
            await tracker.create(dep_id, f"agent-{i}", f"cred-{i}", f"10.0.0.{i % 254}")
            await tracker.update_status(dep_id, "deploying", progress=50)

        snapshot_after = tracemalloc.take_snapshot()
        tracemalloc.stop()

        top_stats = snapshot_after.compare_to(snapshot_before, "lineno")
        total_kb = sum(stat.size_diff for stat in top_stats if stat.size_diff > 0) / 1024
        print(f"\n[MEM] 100 deployments: +{total_kb:.1f} KB")
        assert total_kb < 5 * 1024, f"Memory too high: {total_kb:.1f} KB (limit 5120 KB)"

    @pytest.mark.asyncio
    async def test_deployment_cleanup_releases_memory(self):
        """cleanup_old_deployments() should free memory."""
        tracker = DeploymentTracker()

        # Fill with terminal-state deployments
        for i in range(50):
            dep_id = f"cleanup-dep-{i:04d}"
            await tracker.create(dep_id, f"agent-{i}", "c", "h")
            await tracker.update_status(dep_id, "ready")

        gc.collect()
        tracemalloc.start()
        snapshot_before = tracemalloc.take_snapshot()

        await tracker.cleanup_old_deployments(older_than_hours=0)

        gc.collect()
        snapshot_after = tracemalloc.take_snapshot()
        tracemalloc.stop()

        # After cleanup, the store should be empty
        deps = await tracker.list_deployments()
        assert len(deps) == 0, "All deployments should be removed by cleanup"

        top_stats = snapshot_after.compare_to(snapshot_before, "lineno")
        net_kb = sum(stat.size_diff for stat in top_stats) / 1024
        print(f"\n[MEM] After cleanup net: {net_kb:.1f} KB")
        # Net allocation should be very small (near zero or negative)
        assert net_kb < 100, f"Cleanup leaked memory: {net_kb:.1f} KB"

    @pytest.mark.asyncio
    async def test_status_update_chain_memory_stable(self):
        """
        Repeatedly cycling through status updates should not leak.
        """
        tracker = DeploymentTracker()
        dep_id = "cycling-dep"
        await tracker.create(dep_id, "cycle-agent", "c", "h")

        gc.collect()
        tracemalloc.start()

        statuses = ["deploying", "registering", "ready"]
        # Run 500 status updates cycling through states
        for i in range(500):
            st = statuses[i % len(statuses)]
            await tracker.update_status(dep_id, st, progress=i % 100)

        peak = tracemalloc.get_traced_memory()[1]
        tracemalloc.stop()

        print(f"\n[MEM] 500 update_status() peak: {_kb(peak):.1f} KB")
        assert _kb(peak) < 2048, f"Status update loop used too much memory: {_kb(peak):.1f} KB"


# ---------------------------------------------------------------------------
# AgentRegistry memory profiling
# ---------------------------------------------------------------------------

class TestAgentRegistryMemory:

    @pytest.mark.asyncio
    async def test_1000_agents_registration_memory(self):
        """
        Registering 1000 agents should stay under 10 MB.
        """
        registry = AgentRegistry()
        gc.collect()
        tracemalloc.start()
        snapshot_before = tracemalloc.take_snapshot()

        for i in range(1000):
            await registry.register_agent_online(
                agent_id=f"agent-{i:06d}",
                agent_name=f"test-agent-{i}",
                version="1.0.0",
                address=f"10.{i // 256 % 256}.{i % 256}.1:8080",
                capabilities=["sensor.read", "actuator.write"],
                now=_now(),
            )

        snapshot_after = tracemalloc.take_snapshot()
        tracemalloc.stop()

        top_stats = snapshot_after.compare_to(snapshot_before, "lineno")
        total_kb = sum(s.size_diff for s in top_stats if s.size_diff > 0) / 1024
        print(f"\n[MEM] 1000 agent registrations: +{total_kb:.1f} KB")
        assert total_kb < 10 * 1024, f"Too much memory: {total_kb:.1f} KB"

    @pytest.mark.asyncio
    async def test_heartbeat_storm_no_leak(self):
        """
        1000 heartbeat updates on a single agent shouldn't grow memory unbounded.
        """
        registry = AgentRegistry()
        await registry.register_agent_online(
            "storm-agent", "storm", "1.0", "h", [], _now()
        )

        gc.collect()
        tracemalloc.start()
        for _ in range(1000):
            await registry.update_agent_heartbeat("storm-agent", _now())

        peak_bytes, _ = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        print(f"\n[MEM] 1000 heartbeat updates peak alloc: {_kb(peak_bytes):.1f} KB")
        # Peak in-use at any point should be very small
        assert _kb(peak_bytes) < 256, f"Heartbeat storm leaked: {_kb(peak_bytes):.1f} KB"

    @pytest.mark.asyncio
    async def test_list_agents_does_not_copy_unnecessarily(self):
        """
        list_agents() should return lightweight data, not deep copies of all metadata.
        """
        registry = AgentRegistry()
        for i in range(200):
            await registry.register_agent_online(
                f"list-agent-{i}", f"agent-{i}", "1.0", "h", [], _now()
            )

        gc.collect()
        tracemalloc.start()
        for _ in range(50):
            agents = await registry.list_agents()
            _ = [a.agent_id for a in agents]

        peak_bytes, _ = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        print(f"\n[MEM] 50x list_agents(200) peak: {_kb(peak_bytes):.1f} KB")
        assert _kb(peak_bytes) < 2048, f"list_agents uses too much memory: {_kb(peak_bytes):.1f} KB"


# ---------------------------------------------------------------------------
# Combined full-flow memory profile
# ---------------------------------------------------------------------------

class TestFullFlowMemoryProfile:

    @pytest.mark.asyncio
    async def test_combined_deploy_enroll_heartbeat_memory(self):
        """
        Simulate a realistic workload: 50 deployments, each enrolling and hearbeat-ing.
        Total memory delta should stay under 20 MB.
        """
        tracker = DeploymentTracker()
        registry = AgentRegistry()

        gc.collect()
        tracemalloc.start()
        snapshot_before = tracemalloc.take_snapshot()

        n = 50
        for i in range(n):
            dep_id = f"full-dep-{i:04d}"
            agent_id = f"full-agent-{i:04d}"
            now = _now()

            await tracker.create(dep_id, f"agent-{i}", "cred", f"10.0.0.{i % 254}")
            await tracker.update_status(dep_id, "deploying", progress=50)
            await registry.register_agent_online(
                agent_id, f"agent-{i}", "1.0", f"10.0.0.{i % 254}:80",
                ["device.sensor"], now
            )
            await registry.update_agent_heartbeat(agent_id, now)
            await tracker.update_status(dep_id, "registering", agent_id=agent_id, progress=75)
            await tracker.update_status(dep_id, "ready", progress=100)

        snapshot_after = tracemalloc.take_snapshot()
        tracemalloc.stop()

        top_stats = snapshot_after.compare_to(snapshot_before, "lineno")
        total_kb = sum(s.size_diff for s in top_stats if s.size_diff > 0) / 1024
        print(f"\n[MEM] 50-agent full flow memory delta: +{total_kb:.1f} KB")
        assert total_kb < 20 * 1024, f"Full flow memory too high: {total_kb:.1f} KB"

    @pytest.mark.asyncio
    async def test_cleanup_after_full_flow_restores_baseline(self):
        """After cleanup, memory use should return close to baseline."""
        tracker = DeploymentTracker()

        for i in range(30):
            dep_id = f"clean-dep-{i:04d}"
            await tracker.create(dep_id, f"a-{i}", "c", "h")
            await tracker.update_status(dep_id, "ready")

        # Clean up all
        await tracker.cleanup_old_deployments(older_than_hours=0)

        gc.collect()
        tracemalloc.start()
        snapshot_clean = tracemalloc.take_snapshot()

        # Do another 30 (should allocate similar amount as before cleanup)
        for i in range(30, 60):
            dep_id = f"clean-dep-{i:04d}"
            await tracker.create(dep_id, f"a-{i}", "c", "h")
            await tracker.update_status(dep_id, "ready")

        snapshot_after = tracemalloc.take_snapshot()
        tracemalloc.stop()

        top_stats = snapshot_after.compare_to(snapshot_clean, "lineno")
        total_kb = sum(s.size_diff for s in top_stats if s.size_diff > 0) / 1024
        print(f"\n[MEM] Post-cleanup second batch delta: +{total_kb:.1f} KB")
        # Should be roughly proportional to first batch (not growing unboundedly)
        assert total_kb < 5 * 1024, f"Memory grew too much after cleanup: {total_kb:.1f} KB"
