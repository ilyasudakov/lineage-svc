// Shared URN + payload helpers for all k6 scenarios.

const NAMESPACES = Array.from({ length: 20 }, (_, i) => `${i + 1}_ws_${(i + 1) * 7}`);
const SOURCES = [
  "facebook_ads", "google_ads", "tiktok_ads", "linkedin_ads", "snapchat_ads",
  "twitter_ads", "pinterest_ads", "amazon_ads", "criteo", "adroll",
];
const REPORTS = ["campaigns", "adsets", "ads", "creatives", "insights"];

const BACKEND = __ENV.BACKEND || "lineage";
// Match the fixture's dataset pool size: generator uses max(100, edges // 10).
// For 100k edges → 10k datasets. Override via URN_POOL.
const URN_POOL = __ENV.URN_POOL ? parseInt(__ENV.URN_POOL, 10) : 10_000;

function powerLaw(n, alpha = 1.5) {
  return Math.min(n - 1, Math.floor(n * Math.pow(Math.random(), alpha)));
}

export function pickNamespace() {
  return NAMESPACES[powerLaw(NAMESPACES.length)];
}

// Both backends store the same dataset names (loaded from one fixture);
// only the URN separator differs: lineage-svc uses '/', Marquez uses ':'.
export function randomDatasetUrn() {
  const ns = pickNamespace();
  const src = SOURCES[powerLaw(SOURCES.length)];
  const rpt = REPORTS[powerLaw(REPORTS.length)];
  const id = powerLaw(URN_POOL);
  const name = `${src}.api.${rpt}.${id}`; // matches fixture inputs[].name
  const sep = BACKEND === "marquez" ? ":" : "/";
  return `dataset:${ns}${sep}${name}`;
}

export function buildEvent() {
  const ns = pickNamespace();
  const src = SOURCES[powerLaw(SOURCES.length)];
  const rpt = REPORTS[powerLaw(REPORTS.length)];
  const id = Math.floor(Math.random() * 1_000_000);
  return {
    eventType: "COMPLETE",
    eventTime: new Date().toISOString(),
    producer: "k6",
    run: { runId: `k6-run-${id}-${Math.random()}` },
    job: { namespace: ns, name: `extract.${src}.${rpt}.${id}` },
    inputs: [{ namespace: ns, name: `${src}.api.${rpt}.${powerLaw(500_000)}` }],
    outputs: [{ namespace: ns, name: `data_table__${src}__${rpt}__sql_${id}__${id}` }],
  };
}
