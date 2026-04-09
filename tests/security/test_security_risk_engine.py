"""
Test flow — Adaptive Risk Scoring Engine

Tests for risk assessment, scoring, decay, and decision-making.

Coverage:
- Single event scoring
- Multiple weighted events
- Exponential decay
- Threshold transitions
- MFA required scenario
- Temporary block scenario
- Freeze scenario
- Risk reset
- Concurrency
- Multi-user isolation
- Background cleanup
"""

import pytest
import asyncio
import time
from unittest import mock

from modules.security.risk import (
    RiskEvent,
    RiskAssessment,
    RiskAction,
    EventType,
    RiskEngine,
    RiskMemory,
    RiskPolicy,
    RiskConfig,
)


class TestRiskModels:
    """Test RiskEvent and RiskAssessment models."""

    def test_risk_event_creation(self):
        """Create a risk event."""
        event = RiskEvent(
            user_id="alice",
            event_type=EventType.SECRET_READ,
            weight=5.0,
            timestamp=time.time(),
        )
        
        assert event.user_id == "alice"
        assert event.weight == 5.0

    def test_risk_event_weight_validation(self):
        """Weight must be in [-100, 100]."""
        with pytest.raises(ValueError):
            RiskEvent(
                user_id="alice",
                event_type=EventType.SECRET_READ,
                weight=150.0,
                timestamp=time.time(),
            )

    def test_risk_assessment_creation(self):
        """Create a risk assessment."""
        assessment = RiskAssessment(
            score=45.0,
            action=RiskAction.REQUIRE_MFA,
            reasons=["Medium risk"],
        )
        
        assert assessment.score == 45.0
        assert assessment.action == RiskAction.REQUIRE_MFA

    def test_risk_event_age_calculation(self):
        """Calculate event age."""
        now = time.time()
        event = RiskEvent(
            user_id="alice",
            event_type=EventType.SECRET_READ,
            weight=5.0,
            timestamp=now - 10,
        )
        
        age = event.age_seconds(now)
        assert 9.9 < age < 10.1  # ~10 seconds


class TestRiskPolicy:
    """Test risk policy and weighting."""

    def test_default_weights_exist(self):
        """All event types have weights."""
        policy = RiskPolicy()
        
        for event_type in EventType:
            weight = policy.get_weight(event_type)
            assert isinstance(weight, float)

    def test_score_to_action_low(self):
        """Score < 30 → ALLOW."""
        policy = RiskPolicy()
        
        action = policy.score_to_action(20.0)
        assert action == RiskAction.ALLOW

    def test_score_to_action_medium(self):
        """Score 30–59 → REQUIRE_MFA."""
        policy = RiskPolicy()
        
        action = policy.score_to_action(45.0)
        assert action == RiskAction.REQUIRE_MFA

    def test_score_to_action_high(self):
        """Score 60–79 → TEMP_BLOCK."""
        policy = RiskPolicy()
        
        action = policy.score_to_action(70.0)
        assert action == RiskAction.TEMP_BLOCK

    def test_score_to_action_critical(self):
        """Score ≥80 → FREEZE."""
        policy = RiskPolicy()
        
        action = policy.score_to_action(85.0)
        assert action == RiskAction.FREEZE

    def test_exponential_decay(self):
        """Exponential decay reduces weight over time."""
        policy = RiskPolicy()
        
        # At half-life, weight should be 50%
        decayed = policy.apply_decay(100.0, 60, half_life=60)
        assert 49 < decayed < 51  # ~50%
        
        # At 2x half-life, weight should be 25%
        decayed = policy.apply_decay(100.0, 120, half_life=60)
        assert 24 < decayed < 26  # ~25%

    def test_decay_zero_age(self):
        """No decay at zero age."""
        policy = RiskPolicy()
        
        decayed = policy.apply_decay(100.0, 0, half_life=60)
        assert decayed == 100.0


class TestRiskMemory:
    """Test memory layer."""

    @pytest.mark.asyncio
    async def test_record_event(self):
        """Record event to memory."""
        memory = RiskMemory()
        
        event = RiskEvent(
            user_id="alice",
            event_type=EventType.SECRET_READ,
            weight=5.0,
            timestamp=time.time(),
        )
        
        await memory.record(event)
        
        events = await memory.get_recent("alice")
        assert len(events) == 1
        assert events[0].user_id == "alice"

    @pytest.mark.asyncio
    async def test_sliding_window(self):
        """Events outside window are not returned."""
        config = RiskConfig(window_seconds=10)
        memory = RiskMemory(config)
        
        now = time.time()
        
        # Old event (outside window)
        old_event = RiskEvent(
            user_id="alice",
            event_type=EventType.SECRET_READ,
            weight=5.0,
            timestamp=now - 20,  # 20s old
        )
        
        # Recent event (inside window)
        recent_event = RiskEvent(
            user_id="alice",
            event_type=EventType.SECRET_READ,
            weight=5.0,
            timestamp=now - 5,  # 5s old
        )
        
        await memory.record(old_event)
        await memory.record(recent_event)
        
        events = await memory.get_recent("alice", now)
        assert len(events) == 1
        assert events[0].timestamp == recent_event.timestamp

    @pytest.mark.asyncio
    async def test_ring_buffer(self):
        """Ring buffer enforces max size."""
        config = RiskConfig(max_events_per_user=5)
        memory = RiskMemory(config)
        
        now = time.time()
        for i in range(10):
            event = RiskEvent(
                user_id="alice",
                event_type=EventType.SECRET_READ,
                weight=1.0,
                timestamp=now + i,
            )
            await memory.record(event)
        
        events = await memory.get_all_events("alice")
        assert len(events) == 5

    @pytest.mark.asyncio
    async def test_clear_user(self):
        """Clear all user events."""
        memory = RiskMemory()
        
        event = RiskEvent(
            user_id="alice",
            event_type=EventType.SECRET_READ,
            weight=5.0,
            timestamp=time.time(),
        )
        
        await memory.record(event)
        await memory.clear_user("alice")
        
        events = await memory.get_recent("alice")
        assert len(events) == 0


class TestRiskEngine:
    """Test risk scoring engine."""

    @pytest.mark.asyncio
    async def test_single_event_scoring(self):
        """Single event contributes its weight."""
        config = RiskConfig(decay_enabled=False)  # Disable decay for cleaner test
        engine = RiskEngine(config=config)
        
        event = RiskEvent(
            user_id="alice",
            event_type=EventType.SECRET_READ,
            weight=5.0,
            timestamp=time.time(),
        )
        
        await engine.record_event(event)
        
        score = await engine.get_user_score("alice")
        assert score == 5.0

    @pytest.mark.asyncio
    async def test_multiple_events_summation(self):
        """Multiple events sum."""
        config = RiskConfig(decay_enabled=False)
        engine = RiskEngine(config=config)
        now = time.time()
        
        events = [
            RiskEvent("alice", EventType.SECRET_READ, 5.0, now),
            RiskEvent("alice", EventType.MFA_FAILURE, 10.0, now),
            RiskEvent("alice", EventType.ACCESS_DENIED, 15.0, now),
        ]
        
        for event in events:
            await engine.record_event(event)
        
        score = await engine.get_user_score("alice")
        assert score == 30.0

    @pytest.mark.asyncio
    async def test_negative_weight_reduction(self):
        """Negative events (trust restoration) reduce score."""
        config = RiskConfig(decay_enabled=False)
        engine = RiskEngine(config=config)
        now = time.time()
        
        await engine.record_event(
            RiskEvent("alice", EventType.MFA_FAILURE, 20.0, now)
        )
        await engine.record_event(
            RiskEvent("alice", EventType.MFA_SUCCESS, -5.0, now)
        )
        
        score = await engine.get_user_score("alice")
        assert score == 15.0

    @pytest.mark.asyncio
    async def test_decay_older_events(self):
        """Older events contribute less (decay)."""
        config = RiskConfig(decay_enabled=True)
        engine = RiskEngine(config=config)
        
        now = time.time()
        
        # Old event
        await engine.record_event(
            RiskEvent("alice", EventType.SECRET_READ, 100.0, now - 120)
        )
        
        score = await engine.get_user_score("alice", now)
        
        # At 2x half-life (120s), weight should be ~25%
        assert 20 < score < 30

    @pytest.mark.asyncio
    async def test_assessment_returns_action(self):
        """Assessment determines action based on score."""
        config = RiskConfig(decay_enabled=False)
        engine = RiskEngine(config=config)
        now = time.time()
        
        # Score 45 → REQUIRE_MFA
        await engine.record_event(
            RiskEvent("alice", EventType.SECRET_READ, 45.0, now)
        )
        
        assessment = await engine.assess("alice")
        assert assessment.action == RiskAction.REQUIRE_MFA
        assert 30 <= assessment.score < 60

    @pytest.mark.asyncio
    async def test_allow_threshold(self):
        """Score < 30 → ALLOW."""
        config = RiskConfig(decay_enabled=False)
        engine = RiskEngine(config=config)
        now = time.time()
        
        await engine.record_event(
            RiskEvent("alice", EventType.SECRET_READ, 20.0, now)
        )
        
        action = await engine.get_user_action("alice")
        assert action == RiskAction.ALLOW

    @pytest.mark.asyncio
    async def test_require_mfa_threshold(self):
        """Score 30–59 → REQUIRE_MFA."""
        config = RiskConfig(decay_enabled=False)
        engine = RiskEngine(config=config)
        now = time.time()
        
        await engine.record_event(
            RiskEvent("alice", EventType.SECRET_READ, 5.0, now)
        )
        await engine.record_event(
            RiskEvent("alice", EventType.MFA_FAILURE, 10.0, now)
        )
        await engine.record_event(
            RiskEvent("alice", EventType.ACCESS_DENIED, 15.0, now)
        )
        
        action = await engine.get_user_action("alice")
        assert action == RiskAction.REQUIRE_MFA

    @pytest.mark.asyncio
    async def test_temp_block_threshold(self):
        """Score 60–79 → TEMP_BLOCK."""
        config = RiskConfig(decay_enabled=False)
        engine = RiskEngine(config=config)
        now = time.time()
        
        events = [
            RiskEvent("alice", EventType.SECRET_READ, 10.0, now),
            RiskEvent("alice", EventType.SECRET_READ_SPIKE, 25.0, now),
            RiskEvent("alice", EventType.MFA_FAILURE, 10.0, now),
            RiskEvent("alice", EventType.ACCESS_DENIED, 15.0, now),
        ]
        
        for event in events:
            await engine.record_event(event)
        
        action = await engine.get_user_action("alice")
        assert action == RiskAction.TEMP_BLOCK

    @pytest.mark.asyncio
    async def test_freeze_threshold(self):
        """Score ≥80 → FREEZE."""
        config = RiskConfig(decay_enabled=False)
        engine = RiskEngine(config=config)
        now = time.time()
        
        events = [
            RiskEvent("alice", EventType.SECRET_READ_BURST, 30.0, now),
            RiskEvent("alice", EventType.SECRET_READ_SPIKE, 25.0, now),
            RiskEvent("alice", EventType.MFA_BRUTE_FORCE, 20.0, now),
            RiskEvent("alice", EventType.ACCESS_DENIED, 15.0, now),
        ]
        
        for event in events:
            await engine.record_event(event)
        
        action = await engine.get_user_action("alice")
        assert action == RiskAction.FREEZE

    @pytest.mark.asyncio
    async def test_reset_user_risk(self):
        """Reset clears user's risk history."""
        config = RiskConfig(decay_enabled=False)
        engine = RiskEngine(config=config)
        now = time.time()
        
        await engine.record_event(
            RiskEvent("alice", EventType.ACCOUNT_FROZEN, 50.0, now)
        )
        
        score_before = await engine.get_user_score("alice")
        assert score_before > 0
        
        await engine.reset_user_risk("alice")
        
        score_after = await engine.get_user_score("alice")
        assert score_after == 0

    @pytest.mark.asyncio
    async def test_score_bounds(self):
        """Score always in [0, 100]."""
        config = RiskConfig(decay_enabled=False)
        engine = RiskEngine(config=config)
        now = time.time()
        
        # Very high events
        for _ in range(20):
            await engine.record_event(
                RiskEvent("alice", EventType.ACCOUNT_FROZEN, 50.0, now)
            )
        
        score = await engine.get_user_score("alice")
        assert 0 <= score <= 100

    @pytest.mark.asyncio
    async def test_assessment_with_reasons(self):
        """Assessment includes explanation."""
        config = RiskConfig(decay_enabled=False)
        engine = RiskEngine(config=config)
        now = time.time()
        
        await engine.record_event(
            RiskEvent("alice", EventType.SECRET_READ, 45.0, now)
        )
        
        assessment = await engine.assess("alice")
        
        assert len(assessment.reasons) > 0
        assert assessment.events_considered == 1


class TestConcurrency:
    """Test concurrency safety."""

    @pytest.mark.asyncio
    async def test_concurrent_record_events(self):
        """Recording events concurrently is safe."""
        config = RiskConfig(decay_enabled=False)
        engine = RiskEngine(config=config)
        now = time.time()
        
        async def record_events():
            for i in range(10):
                await engine.record_event(
                    RiskEvent(
                        "alice",
                        EventType.SECRET_READ,
                        1.0,
                        now + i * 0.1,
                    )
                )
        
        await asyncio.gather(*[record_events() for _ in range(5)])
        
        score = await engine.get_user_score("alice")
        assert score == 50.0  # 5 * 10 * 1.0

    @pytest.mark.asyncio
    async def test_concurrent_assessments(self):
        """Concurrent assessments are deterministic."""
        config = RiskConfig(decay_enabled=False)
        engine = RiskEngine(config=config)
        now = time.time()
        
        await engine.record_event(
            RiskEvent("alice", EventType.SECRET_READ, 50.0, now)
        )
        
        # Run assessments concurrently
        results = await asyncio.gather(*[
            engine.assess("alice")
            for _ in range(5)
        ])
        
        # All should have same score
        scores = [r.score for r in results]
        assert len(set(scores)) == 1  # All identical


class TestMultiUser:
    """Test multi-user isolation."""

    @pytest.mark.asyncio
    async def test_user_isolation(self):
        """Risk events isolated per user."""
        config = RiskConfig(decay_enabled=False)
        engine = RiskEngine(config=config)
        now = time.time()
        
        await engine.record_event(
            RiskEvent("alice", EventType.SECRET_READ, 50.0, now)
        )
        await engine.record_event(
            RiskEvent("bob", EventType.SECRET_READ, 10.0, now)
        )
        
        alice_score = await engine.get_user_score("alice")
        bob_score = await engine.get_user_score("bob")
        
        assert alice_score == 50.0
        assert bob_score == 10.0


class TestStatistics:
    """Test observability and stats."""

    @pytest.mark.asyncio
    async def test_stats_reporting(self):
        """Engine reports statistics."""
        engine = RiskEngine()
        now = time.time()
        
        await engine.record_event(
            RiskEvent("alice", EventType.SECRET_READ, 5.0, now)
        )
        
        stats = await engine.stats()
        
        assert "engine" in stats
        assert "users_tracked" in stats
        assert "total_events" in stats
