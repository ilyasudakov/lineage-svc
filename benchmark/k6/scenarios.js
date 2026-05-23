// All six benchmark scenarios in one file. Pick one with SCENARIO env var.
// Usage:
//   SCENARIO=steady_write TARGET=http://localhost:8000 k6 run scenarios.js
//
// Available SCENARIO values:
//   steady_write | burst_write | steady_read | read_only_baseline | cold_read | deep_read
//
// All scenarios export Prometheus-compatible metrics via k6's
// `experimental-prometheus-rw` output; set K6_PROMETHEUS_RW_SERVER_URL.

import http from "k6/http";
import { check, sleep } from "k6";
import { Trend, Counter } from "k6/metrics";
import { buildEvent, randomDatasetUrn } from "./lib/urn.js";

const TARGET = __ENV.TARGET || "http://localhost:8000";
const SCENARIO = __ENV.SCENARIO || "steady_write";

const writeLatency = new Trend("write_latency_ms", true);
const readDirectLatency = new Trend("read_direct_latency_ms", true);
const readDepth3Latency = new Trend("read_depth3_latency_ms", true);
const readDepth10Latency = new Trend("read_depth10_latency_ms", true);
const errors = new Counter("errors");

// -------- Scenario definitions --------

const SCENARIOS = {
  steady_write: {
    executor: "constant-arrival-rate",
    rate: 300,
    timeUnit: "1s",
    duration: "30m",
    preAllocatedVUs: 100,
    maxVUs: 500,
    exec: "write",
  },
  burst_write: {
    executor: "ramping-arrival-rate",
    startRate: 0,
    timeUnit: "1s",
    preAllocatedVUs: 100,
    maxVUs: 1500,
    stages: [
      { target: 1000, duration: "2m" },
      { target: 1000, duration: "5m" },
      { target: 0, duration: "3m" },
    ],
    exec: "write",
  },
  steady_read: {
    executor: "constant-arrival-rate",
    rate: 100,
    timeUnit: "1s",
    duration: "30m",
    preAllocatedVUs: 50,
    maxVUs: 300,
    exec: "readMixed",
  },
  read_only_baseline: {
    executor: "constant-arrival-rate",
    rate: 100,
    timeUnit: "1s",
    duration: "10m",
    preAllocatedVUs: 50,
    maxVUs: 300,
    exec: "readMixed",
  },
  cold_read: {
    executor: "constant-arrival-rate",
    rate: 1,
    timeUnit: "1s",
    duration: "2m",
    preAllocatedVUs: 1,
    maxVUs: 5,
    exec: "readMixed",
  },
  deep_read: {
    executor: "constant-arrival-rate",
    rate: 5,
    timeUnit: "1s",
    duration: "10m",
    preAllocatedVUs: 10,
    maxVUs: 50,
    exec: "readDeep",
  },
};

if (!SCENARIOS[SCENARIO]) {
  throw new Error(`unknown SCENARIO=${SCENARIO}; choose one of ${Object.keys(SCENARIOS).join(", ")}`);
}

export const options = {
  scenarios: { [SCENARIO]: SCENARIOS[SCENARIO] },
  thresholds: {
    write_latency_ms: ["p(95)<50"],
    read_direct_latency_ms: ["p(95)<50"],
    read_depth3_latency_ms: ["p(95)<100"],
    read_depth10_latency_ms: ["p(95)<500", "p(99)<2000"],
    errors: ["count<10000"],
  },
};

// -------- Executable functions referenced by scenarios --------

export function write() {
  const payload = JSON.stringify(buildEvent());
  const t0 = Date.now();
  const r = http.post(`${TARGET}/api/v1/lineage`, payload, {
    headers: { "content-type": "application/json" },
  });
  writeLatency.add(Date.now() - t0);
  if (!check(r, { "write 2xx": (resp) => resp.status >= 200 && resp.status < 300 })) {
    errors.add(1);
  }
}

export function readMixed() {
  const roll = Math.random();
  if (roll < 0.7) readDirect();
  else if (roll < 0.9) readDepth(3);
  else readDepth(10);
}

function readDirect() {
  const node = randomDatasetUrn();
  const t0 = Date.now();
  const r = http.get(`${TARGET}/api/v1/lineage/direct?node=${encodeURIComponent(node)}`);
  readDirectLatency.add(Date.now() - t0);
  if (!check(r, { "direct 2xx": (resp) => resp.status >= 200 && resp.status < 300 })) {
    errors.add(1);
  }
}

function readDepth(depth) {
  const node = randomDatasetUrn();
  const t0 = Date.now();
  const r = http.get(
    `${TARGET}/api/v1/lineage?node=${encodeURIComponent(node)}&depth=${depth}&direction=downstream`,
  );
  const latency = Date.now() - t0;
  if (depth === 3) readDepth3Latency.add(latency);
  else readDepth10Latency.add(latency);
  if (!check(r, { [`depth${depth} 2xx`]: (resp) => resp.status >= 200 && resp.status < 300 })) {
    errors.add(1);
  }
}

export function readDeep() {
  const depth = 10 + Math.floor(Math.random() * 41); // 10–50
  const node = randomDatasetUrn();
  const t0 = Date.now();
  const r = http.get(
    `${TARGET}/api/v1/lineage?node=${encodeURIComponent(node)}&depth=${depth}&direction=both`,
  );
  readDepth10Latency.add(Date.now() - t0);
  if (!check(r, { "deep 2xx": (resp) => resp.status >= 200 && resp.status < 300 })) {
    errors.add(1);
  }
}

// k6 picks the function named by `exec` in each scenario above.
// `default` is unused but required when no scenario is selected.
export default function () {
  sleep(1);
}
