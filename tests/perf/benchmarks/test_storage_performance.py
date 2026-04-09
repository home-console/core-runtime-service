"""
Storage Performance Benchmarks — Day 5
Measures throughput, latency distributions, and scalability of
DeploymentTracker + AgentRegistry (in-memory storage adapters).
"""

import time
import asyncio
import statistics
import gc
import pytest
from datetime import datetime, timezone
from typing import List

from modules.agent import DeploymentTracker, AgentRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _fill_tracker(tracker: DeploymentTracker, n: int) -> List[str]:
    ids = []
    for i in range(n):
        dep_id = f"bench-dep-{i:06d}"
        await tracker.create(dep_id, f"agent-{i}", f"cred-{i}", f"10.0.{i // 256 % 256}.{i % 256}")
        ids.append(dep_id)
    return ids


async def _fill_registry(registry: AgentRegistry, n: int) -> List[str]:
    ids = []
    for i in range(n):
        agent_id = f"bench-agent-{i:06d}"
        await registry.register_agent_online(
            agent_id, f"agent-{i}", "1.0.0",
            f"10.{i // 65536 % 256}.{i // 256 % 256}.{i % 256}:8080",
            ["sensor.read"],
            _now(),
        )
        ids.append(agent_id)
    return ids


def _percentile(data: list, p: float) -> float:
    if not data:
        return 0.0
    sorted_data = sorted(data)
    idx = int(len(sorted_data) * p / 100)
    return sorted_data[min(idx, len(sorted_data) - 1)]


# ---------------------------------------------------------------------------
# DeploymentTracker throughput
# ---------------------------------------------------------------------------

class TestDeploymentTrackerThroughput:

    @pytest.mark.asyncio
    async def test_create_1000_deployments_throughput(self):
        """1000 deployment creates should complete in < 2s (>=500 ops/sec)."""
        tracker = DeploymentTracker()
        gc.collect()

        n = 1000
        start = time.perf_counter()

        for i in range(n):
            await tracker.create(
                f"tput-dep-{i:06d}", f"a-{i}", f"c-{i}", f"h-{i}"
            )

        elapsed = time.perf_counter() - start
        ops_per_sec = n / elapsed

        print(f"\n[TPUT] create() x{n}: {elapsed:.3f}s ({ops_per_sec:.0f} ops/s)")
        assert ops_per_sec >= 500, f"Too slow: {ops_per_sec:.0f} ops/s (need ≥500)"

    @pytest.mark.asyncio
    async def test_update_status_1000_throughput(self):
        """1000 update_status() calls should complete in < 1s."""
        tracker = DeploymentTracker()
        ids = await _fill_tracker(tracker, 1000)
        gc.collect()

        start = time.perf_counter()
        for dep_id in ids:
            await tracker.update_status(dep_id, "deploying", progress=50)
        elapsed = time.perf_counter() - start

        ops_per_sec = len(ids) / elapsed
        print(f"\n[TPUT] update_status() x{len(ids)}: {elapsed:.3f}s ({ops_per_sec:.0f} ops/s)")
        assert ops_per_sec >= 1000, f"update_status too slow: {ops_per_sec:.0f} ops/s"

    @pytest.mark.asyncio
    async def test_list_deployments_latency(self):
        """list_deployments() should return in < 10ms even with 500 entries."""
        tracker = DeploymentTracker()
        await _fill_tracker(tracker, 500)
        gc.collect()

        latencies = []
        for _ in range(50):
            t0 = time.perf_counter()
            result = await tracker.list_deployments()
            latencies.append((time.perf_counter() - t0) * 1000)

        p50 = _percentile(latencies, 50)
        p99 = _percentile(latencies, 99)
        print(f"\n[LAT] list_deployments(500 items) p50={p50:.2f}ms p99={p99:.2f}ms")
        assert p50 < 10, f"p50 too slow: {p50:.2f}ms"
        assert p99 < 50, f"p99 too slow: {p99:.2f}ms"

    @pytest.mark.asyncio
    async def test_get_deployment_latency_p99(self):
        """get() on a single deployment should be < 1ms p99."""
        tracker = DeploymentTracker()
        ids = await _fill_tracker(tracker, 200)
        gc.collect()

        target = ids[100]
        latencies = []
        for _ in range(200):
            t0 = time.perf_counter()
            await tracker.get(target)
            latencies.append((time.perf_counter() - t0) * 1000)

        p99 = _percentile(latencies, 99)
        print(f"\n[LAT] get() p99={p99:.3f}ms")
        assert p99 < 1.0, f"get() p99 too slow: {p99:.3f}ms"

    @pytest.mark.asyncio
    async def test_concurrent_creates_throughput(self):
        """500 concurrent creates should complete within 2s."""
        tracker = DeploymentTracker()
        gc.collect()

        tasks = [
            tracker.create(f"conc-dep-{i:05d}", f"a-{i}", "c", "h")
            for i in range(500)
        ]

        start = time.perf_counter()
        await asyncio.gather(*tasks)
        elapsed = time.perf_counter() - start

        print(f"\n[TPUT] 500 concurrent creates: {elapsed:.3f}s")
        assert elapsed < 2.0, f"Concurrent creates took too long: {elapsed:.3f}s"

    @pytest.mark.asyncio
    async def test_metrics_computation_latency(self):
        """get_deployment_metrics() should be O(n) and complete < 20ms for 1000 items."""
        tracker = DeploymentTracker()
        ids = await _fill_tracker(tracker, 1000)

        # Mix of statuses
        for i, dep_id in enumerate(ids):
            st = ["ready", "failed", "timeout", "deploying"][i % 4]
            await tracker.update_status(dep_id, st)

        gc.collect()
        latencies = []
        for _ in range(20):
            t0 = time.perf_counter()
            await tracker.get_deployment_metrics()
            latencies.append((time.perf_counter() - t0) * 1000)

        p99 = _percentile(latencies, 99)
        avg = statistics.mean(latencies)
        print(f"\n[LAT] get_deployment_metrics(1000) avg={avg:.2f}ms p99={p99:.2f}ms")
        assert p99 < 20, f"metrics p99 too slow: {p99:.2f}ms"


# ---------------------------------------------------------------------------
# AgentRegistry throughput
# ---------------------------------------------------------------------------

class TestAgentRegistryThroughput:

    @pytest.mark.asyncio
    async def test_register_500_agents_throughput(self):
        """500 register calls should complete in < 2s."""
        registry = AgentRegistry()
        gc.collect()

        start = time.perf_counter()
        for i in range(500):
            await registry.register_agent_online(
                f"speed-agent-{i:05d}", f"agent-{i}", "1.0",
                f"10.0.{i // 256}.{i % 256}:80", ["s"], _now()
            )
        elapsed = time.perf_counter() - start

        ops_per_sec = 500 / elapsed
        print(f"\n[TPUT] register_agent_online() x500: {elapsed:.3f}s ({ops_per_sec:.0f} ops/s)")
        assert ops_per_sec >= 250, f"Too slow: {ops_per_sec:.0f} ops/s"

    @pytest.mark.asyncio
    async def test_heartbeat_update_2000_throughput(self):
        """2000 heartbeat updates on 100 agents should complete in < 2s."""
        registry = AgentRegistry()
        agent_ids = await _fill_registry(registry, 100)
        gc.collect()

        start = time.perf_counter()
        for i in range(2000):
            agent_id = agent_ids[i % len(agent_ids)]
            await registry.update_agent_heartbeat(agent_id, _now())
        elapsed = time.perf_counter() - start

        ops_per_sec = 2000 / elapsed
        print(f"\n[TPUT] update_agent_heartbeat() x2000: {elapsed:.3f}s ({ops_per_sec:.0f} ops/s)")
        assert ops_per_sec >= 1000, f"Too slow: {ops_per_sec:.0f} ops/s"

    @pytest.mark.asyncio
    async def test_list_agents_throughput(self):
        """list_agents() on 1000-agent registry: >= 100 calls/sec."""
        registry = AgentRegistry()
        await _fill_registry(registry, 1000)
        gc.collect()

        n = 100
        start = time.perf_counter()
        for _ in range(n):
            result = await registry.list_agents()
        elapsed = time.perf_counter() - start

        calls_per_sec = n / elapsed
        print(f"\n[TPUT] list_agents(1000) x{n}: {elapsed:.3f}s ({calls_per_sec:.0f} calls/s)")
        assert calls_per_sec >= 100, f"list_agents too slow: {calls_per_sec:.0f} calls/s"

    @pytest.mark.asyncio
    async def test_get_agent_latency_p99(self):
        """get_agent() single lookup should be < 0.5ms p99."""
        registry = AgentRegistry()
        agent_ids = await _fill_registry(registry, 500)
        gc.collect()

        target = agent_ids[250]
        latencies = []
        for _ in range(300):
            t0 = time.perf_counter()
            await registry.get_agent(target)
            latencies.append((time.perf_counter() - t0) * 1000)

        p99 = _percentile(latencies, 99)
        print(f"\n[LAT] get_agent() p99={p99:.3f}ms")
        assert p99 < 0.5, f"get_agent p99 too slow: {p99:.3f}ms"

    @pytest.mark.asyncio
    async def test_concurrent_heartbeat_storm(self):
        """100 concurrent heartbeat updates should complete in < 500ms."""
        registry = AgentRegistry()
        agent_ids = await _fill_registry(registry, 100)
        gc.collect()

        start = time.perf_counter()
        tasks = [
            registry.update_agent_heartbeat(aid, _now())
            for aid in agent_ids
        ]
        await asyncio.gather(*tasks)
        elapsed = time.perf_counter() - start

        print(f"\n[TPUT] 100 concurrent heartbeat updates: {elapsed:.3f}s")
        assert elapsed < 0.5, f"Concurrent heartbeats took: {elapsed:.3f}s"


# ---------------------------------------------------------------------------
# Scalability benchmarks
# ---------------------------------------------------------------------------

class TestScalabilityBenchmarks:

    @pytest.mark.asyncio
    async def test_deployment_tracker_scales_linearly(self):
        """
        Verify that list_deployments() time does not grow super-linearly.
        Ratio of (time for 1000) / (time for 100) should be < 20x.
        """
        t100 = DeploymentTracker()
        await _fill_tracker(t100, 100)
        gc.collect()

        t0 = time.perf_counter()
        for _ in range(100):
            await t100.list_deployments()
        time_100 = (time.perf_counter() - t0) / 100

        t1000 = DeploymentTracker()
        await _fill_tracker(t1000, 1000)
        gc.collect()

        t0 = time.perf_counter()
        for _ in range(100):
            await t1000.list_deployments()
        time_1000 = (time.perf_counter() - t0) / 100

        ratio = time_1000 / max(time_100, 0.00001)
        print(f"\n[SCALE] list_deployments: 100→1000 time ratio={ratio:.1f}x")
        assert ratio < 20, f"Non-linear scaling: {ratio:.1f}x"

    @pytest.mark.asyncio
    async def test_registry_scales_with_agent_count(self):
        """
        list_agents() on 2000 agents should be < 5x slower than on 200 agents.
        """
        r200 = AgentRegistry()
        await _fill_registry(r200, 200)
        t0 = time.perf_counter()
        for _ in range(100): await r200.list_agents()
        time_200 = (time.perf_counter() - t0) / 100

        r2000 = AgentRegistry()
        await _fill_registry(r2000, 2000)
        t0 = time.perf_counter()
        for _ in range(100): await r2000.list_agents()
        time_2000 = (time.perf_counter() - t0) / 100

        ratio = time_2000 / max(time_200, 0.00001)
        print(f"\n[SCALE] list_agents: 200→2000 time ratio={ratio:.1f}x")
        assert ratio < 15, f"Registry scaling too poor: {ratio:.1f}x"

    @pytest.mark.asyncio
    async def test_mixed_read_write_workload(self):
        """
        Mixed workload (70% reads, 30% writes) should sustain > 200 ops/sec.
        """
        tracker = DeploymentTracker()
        ids = await _fill_tracker(tracker, 200)
        gc.collect()

        operations = 1000
        start = time.perf_counter()

        for i in range(operations):
            if i % 10 < 3:  # 30% writes
                dep_id = ids[i % len(ids)]
                await tracker.update_status(dep_id, "deploying", progress=i % 100)
            else:           # 70% reads
                if i % 10 == 3:
                    await tracker.list_deployments()
                else:
                    await tracker.get(ids[i % len(ids)])

        elapsed = time.perf_counter() - start
        ops_per_sec = operations / elapsed
        print(f"\n[TPUT] Mixed 70/30 workload x{operations}: {elapsed:.3f}s ({ops_per_sec:.0f} ops/s)")
        assert ops_per_sec >= 200, f"Mixed workload too slow: {ops_per_sec:.0f} ops/s"
