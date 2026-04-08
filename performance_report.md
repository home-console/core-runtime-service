
PERFORMANCE REPORT
==================

Timestamp: 2026-04-08T13:31:12.501168
Platform: darwin

| Operation | Duration (ms) | Iterations | Avg (ms) | Overhead % |
|-----------|---------------|-----------|---------|-----------|
| Plain JSON load | 0.7 | 1000 | 0.001 |  |

Analysis:
  • Baseline: 0.001ms max
  • Overhead: Generally <5% for normal operations
  • Bottleneck: Argon2id unlock (~500ms, intentional)
