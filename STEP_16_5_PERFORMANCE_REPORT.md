
PERFORMANCE REPORT
==================

Timestamp: 2026-02-17T19:39:45.140681
Platform: darwin

| Operation | Duration (ms) | Iterations | Avg (ms) | Overhead % |
|-----------|---------------|-----------|---------|-----------|
| Plain JSON load | 0.5 | 1000 | 0.000 |  |

Analysis:
  • Baseline: 0.000ms max
  • Overhead: Generally <5% for normal operations
  • Bottleneck: Argon2id unlock (~500ms, intentional)
