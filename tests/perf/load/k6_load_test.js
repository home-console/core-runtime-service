/**
 * K6 Load Test — HomeConsole Core Runtime Service
 * Day 5 Performance Benchmarks
 *
 * Usage:
 *   k6 run tests/performance/k6_load_test.js
 *   BASE_URL=http://localhost:8000 k6 run tests/performance/k6_load_test.js
 *   DURATION=60s VUS=50 k6 run tests/performance/k6_load_test.js
 *
 * Requires k6: https://k6.io/docs/getting-started/installation/
 */

import { check, sleep } from "k6";
import http from "k6/http";
import { Counter, Rate, Trend } from "k6/metrics";

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

const BASE_URL = __ENV.BASE_URL || "http://localhost:8000";
const DURATION = __ENV.DURATION || "30s";
const VUS = parseInt(__ENV.VUS) || 10;
const RAMP_UP = __ENV.RAMP_UP || "5s";

// Token can be set via environment or will use test value
const ADMIN_TOKEN = __ENV.ADMIN_TOKEN || "test-admin-token";

// ---------------------------------------------------------------------------
// Custom metrics
// ---------------------------------------------------------------------------

const errorRate = new Rate("error_rate");
const deployLatency = new Trend("deploy_latency_ms", true);
const heartbeatLatency = new Trend("heartbeat_latency_ms", true);
const statusPollLatency = new Trend("status_poll_latency_ms", true);
const healthCheckLatency = new Trend("health_check_latency_ms", true);
const totalRequests = new Counter("total_requests");

// ---------------------------------------------------------------------------
// K6 scenarios
// ---------------------------------------------------------------------------

export const options = {
  scenarios: {
    /**
     * Scenario 1: Smoke test
     * Quick sanity check — just 1 VU, 10 iterations
     */
    smoke: {
      executor: "per-vu-iterations",
      vus: 1,
      iterations: 10,
      maxDuration: "30s",
      tags: { scenario: "smoke" },
      exec: "smokeTest",
      startTime: "0s",
    },

    /**
     * Scenario 2: Heartbeat flood
     * Simulate many agents sending heartbeats simultaneously
     */
    heartbeat_flood: {
      executor: "ramping-vus",
      startVUs: 0,
      stages: [
        { duration: RAMP_UP, target: VUS },
        { duration: DURATION, target: VUS },
        { duration: "5s", target: 0 },
      ],
      tags: { scenario: "heartbeat_flood" },
      exec: "heartbeatFlood",
      startTime: "15s",
    },

    /**
     * Scenario 3: Deploy endpoint stress
     * POST /admin/v1/agents/deploy under concurrent load
     */
    deploy_stress: {
      executor: "constant-arrival-rate",
      rate: 5,           // 5 deploys/second
      timeUnit: "1s",
      duration: DURATION,
      preAllocatedVUs: 10,
      maxVUs: 30,
      tags: { scenario: "deploy_stress" },
      exec: "deployStress",
      startTime: "60s",
    },

    /**
     * Scenario 4: Health check polling
     * Continuous polling of agent health endpoints
     */
    health_polling: {
      executor: "constant-vus",
      vus: 5,
      duration: DURATION,
      tags: { scenario: "health_polling" },
      exec: "healthPolling",
      startTime: "30s",
    },
  },

  thresholds: {
    // Overall error rate < 5%
    error_rate: ["rate<0.05"],

    // HTTP failures < 1%
    http_req_failed: ["rate<0.01"],

    // P95 response times
    "deploy_latency_ms{scenario:deploy_stress}": ["p(95)<2000"],
    "heartbeat_latency_ms{scenario:heartbeat_flood}": ["p(95)<500"],
    "health_check_latency_ms{scenario:health_polling}": ["p(95)<300"],

    // Overall request latency
    http_req_duration: ["p(95)<3000", "p(99)<5000"],
  },
};

// ---------------------------------------------------------------------------
// Request helpers
// ---------------------------------------------------------------------------

const headers = {
  "Content-Type": "application/json",
  Authorization: `Bearer ${ADMIN_TOKEN}`,
};

function agentHeaders(agentId) {
  return {
    "Content-Type": "application/json",
    "X-Agent-ID": agentId,
    Authorization: `Bearer agent-token-${agentId}`,
  };
}

// ---------------------------------------------------------------------------
// Scenario: Smoke Test
// ---------------------------------------------------------------------------

export function smokeTest() {
  totalRequests.add(1);

  // 1. Health check
  const healthRes = http.get(`${BASE_URL}/health`, { headers });
  check(healthRes, {
    "health returns 200": (r) => r.status === 200,
  });
  errorRate.add(healthRes.status !== 200);

  // 2. List agents
  const listRes = http.get(`${BASE_URL}/admin/v1/agents`, { headers });
  check(listRes, {
    "list agents returns 200 or 204": (r) =>
      r.status === 200 || r.status === 204,
  });
  errorRate.add(listRes.status >= 400);

  sleep(0.1);
}

// ---------------------------------------------------------------------------
// Scenario: Heartbeat Flood
// ---------------------------------------------------------------------------

export function heartbeatFlood() {
  const agentId = `k6-agent-${__VU}-${__ITER % 100}`;
  const payload = JSON.stringify({
    status: "ok",
    uptime_seconds: Math.floor(Math.random() * 86400),
    cpu_percent: Math.random() * 100,
    memory_mb: 128 + Math.floor(Math.random() * 256),
    version: "1.0.0",
  });

  const start = Date.now();
  const res = http.post(
    `${BASE_URL}/admin/v1/agents/${agentId}/heartbeat`,
    payload,
    { headers: agentHeaders(agentId), tags: { scenario: "heartbeat_flood" } }
  );
  heartbeatLatency.add(Date.now() - start);
  totalRequests.add(1);

  const ok = check(res, {
    "heartbeat accepted": (r) => r.status === 200 || r.status === 201,
    "heartbeat has ack": (r) => {
      try {
        const body = JSON.parse(r.body);
        return body.ack === true;
      } catch {
        return false;
      }
    },
  });
  errorRate.add(!ok);

  sleep(0.05 + Math.random() * 0.1);
}

// ---------------------------------------------------------------------------
// Scenario: Deploy Stress
// ---------------------------------------------------------------------------

export function deployStress() {
  const agentName = `k6-deploy-${__VU}-${__ITER}`;
  const payload = JSON.stringify({
    agent_name: agentName,
    credential_id: `cred-${(__VU % 5) + 1}`,
  });

  const start = Date.now();
  const deployRes = http.post(
    `${BASE_URL}/admin/v1/agents/deploy`,
    payload,
    { headers, tags: { scenario: "deploy_stress" } }
  );
  deployLatency.add(Date.now() - start);
  totalRequests.add(1);

  const deployed = check(deployRes, {
    "deploy returns 200/202": (r) => r.status === 200 || r.status === 202,
    "deploy returns deployment_id": (r) => {
      try {
        const b = JSON.parse(r.body);
        return Boolean(b.deployment_id);
      } catch {
        return false;
      }
    },
  });
  errorRate.add(!deployed);

  if (deployed && deployRes.body) {
    try {
      const body = JSON.parse(deployRes.body);
      const depId = body.deployment_id;

      if (depId) {
        // Poll status once
        const pollStart = Date.now();
        const statusRes = http.get(
          `${BASE_URL}/admin/v1/agents/deployments/${depId}`,
          { headers, tags: { scenario: "deploy_stress" } }
        );
        statusPollLatency.add(Date.now() - pollStart);
        totalRequests.add(1);

        check(statusRes, {
          "poll returns 200": (r) => r.status === 200,
          "poll has status field": (r) => {
            try {
              return Boolean(JSON.parse(r.body).status);
            } catch {
              return false;
            }
          },
        });
      }
    } catch {
      // ignore parse errors
    }
  }

  sleep(0.2);
}

// ---------------------------------------------------------------------------
// Scenario: Health Polling
// ---------------------------------------------------------------------------

export function healthPolling() {
  const endpoints = [
    `${BASE_URL}/admin/v1/agents/health/check`,
    `${BASE_URL}/admin/v1/agents`,
    `${BASE_URL}/admin/v1/agents/deployments/metrics`,
  ];

  for (const url of endpoints) {
    const start = Date.now();
    const res = http.get(url, {
      headers,
      tags: { scenario: "health_polling" },
    });
    healthCheckLatency.add(Date.now() - start);
    totalRequests.add(1);

    check(res, {
      "health endpoint OK": (r) => r.status < 400,
    });
    errorRate.add(res.status >= 400);

    sleep(0.05);
  }

  sleep(0.5);
}

// ---------------------------------------------------------------------------
// Summary output
// ---------------------------------------------------------------------------

export function handleSummary(data) {
  const thresholdsPassed = Object.entries(data.metrics)
    .filter(([, m]) => m.thresholds)
    .every(([, m]) => Object.values(m.thresholds).every((t) => !t.ok === false));

  return {
    stdout: textSummary(data, {
      indent: "  ",
      enableColors: true,
    }),
    "tests/performance/k6_results.json": JSON.stringify(data, null, 2),
  };
}

// Minimal textSummary if k6 doesn't have it built-in
function textSummary(data) {
  const lines = ["", "=== K6 Load Test Summary ===", ""];

  for (const [name, metric] of Object.entries(data.metrics)) {
    if (metric.type === "trend" && metric.values) {
      const v = metric.values;
      lines.push(
        `  ${name}: avg=${v.avg?.toFixed(2)}ms p95=${v["p(95)"]?.toFixed(2)}ms p99=${v["p(99)"]?.toFixed(2)}ms`
      );
    } else if (metric.type === "rate" && metric.values) {
      lines.push(
        `  ${name}: ${(metric.values.rate * 100).toFixed(2)}%`
      );
    } else if (metric.type === "counter" && metric.values) {
      lines.push(`  ${name}: ${metric.values.count}`);
    }
  }

  lines.push("");
  return lines.join("\n");
}
