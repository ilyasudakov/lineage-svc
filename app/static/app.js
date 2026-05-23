// Lineage UI — pure vanilla JS, no build step.
// Talks to: /api/v1/namespaces, /api/v1/search, /api/v1/lineage/direct, /api/v1/lineage

const $ = (sel) => document.querySelector(sel);
const status = $("#status");
let cy = null;
let searchTimer = null;
let currentNode = null;

function setStatus(text, kind = "") {
  status.textContent = text;
  status.className = kind;
}

async function api(path) {
  setStatus("loading…", "busy");
  try {
    const r = await fetch(path);
    if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
    const data = await r.json();
    setStatus("ready");
    return data;
  } catch (e) {
    setStatus(`error: ${e.message}`, "error");
    throw e;
  }
}

// ---------- Namespace dropdown ----------
async function loadNamespaces() {
  const data = await api("/api/v1/namespaces?limit=500");
  const sel = $("#namespace");
  for (const ns of data.namespaces) {
    const opt = document.createElement("option");
    opt.value = ns;
    opt.textContent = ns;
    sel.appendChild(opt);
  }
}

// ---------- Search ----------
function debounce(fn, ms) {
  return (...args) => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => fn(...args), ms);
  };
}

async function runSearch() {
  const q = $("#query").value.trim();
  const ns = $("#namespace").value;
  const list = $("#results");
  list.innerHTML = "";
  if (!q) return;
  const params = new URLSearchParams({ q, limit: "50" });
  if (ns) params.set("namespace", ns);
  const data = await api(`/api/v1/search?${params}`);
  for (const node of data.results) {
    const li = document.createElement("li");
    li.className = node.kind;
    li.textContent = node.urn;
    li.title = node.urn;
    li.addEventListener("click", () => {
      currentNode = node.urn;
      renderGraph();
    });
    list.appendChild(li);
  }
  if (data.results.length === 0) {
    const li = document.createElement("li");
    li.textContent = "(no matches)";
    li.style.color = "var(--muted)";
    list.appendChild(li);
  }
}

// ---------- Graph rendering ----------
function nodeKind(urn) {
  return urn.startsWith("job:") ? "job" : "dataset";
}

function shortLabel(urn) {
  // dataset:1_ws_7/foo.bar → foo.bar
  const sep = urn.includes("/") ? "/" : ":";
  const parts = urn.split(sep);
  return parts.length > 1 ? parts.slice(-1)[0] : urn;
}

async function renderGraph() {
  if (!currentNode) return;
  const depth = parseInt($("#depth").value || "2", 10);
  const direction = $("#direction").value;

  let edges;
  if (depth === 1) {
    const data = await api(`/api/v1/lineage/direct?node=${encodeURIComponent(currentNode)}`);
    edges = [...(data.upstream || []), ...(data.downstream || [])];
    $("#stat-in").textContent = `↑ ${(data.upstream || []).length}`;
    $("#stat-out").textContent = `↓ ${(data.downstream || []).length}`;
  } else {
    const params = new URLSearchParams({ node: currentNode, depth, direction });
    const data = await api(`/api/v1/lineage?${params}`);
    edges = data.edges || [];
    const ups = edges.filter((e) => e.dst_urn === currentNode).length;
    const downs = edges.filter((e) => e.src_urn === currentNode).length;
    $("#stat-in").textContent = `↑ ${ups}`;
    $("#stat-out").textContent = `↓ ${downs}`;
  }

  $("#selected-urn").textContent = currentNode;
  $("#selected-box").hidden = false;

  const nodeSet = new Set();
  const elements = [];
  for (const e of edges) {
    for (const urn of [e.src_urn, e.dst_urn]) {
      if (!nodeSet.has(urn)) {
        nodeSet.add(urn);
        elements.push({
          data: {
            id: urn,
            label: shortLabel(urn),
            kind: nodeKind(urn),
            current: urn === currentNode ? "yes" : "no",
          },
        });
      }
    }
    elements.push({
      data: {
        id: `${e.src_urn}|${e.dst_urn}|${e.edge_type}`,
        source: e.src_urn,
        target: e.dst_urn,
        edgeType: e.edge_type,
      },
    });
  }

  if (cy) cy.destroy();
  document.body.classList.add("has-graph");
  cy = cytoscape({
    container: $("#cy"),
    elements,
    style: [
      {
        selector: "node",
        style: {
          label: "data(label)",
          "background-color": "data(kind)",
          color: "#e6e8ef",
          "font-size": 10,
          "text-valign": "bottom",
          "text-margin-y": 6,
          "border-width": 0,
          width: 18,
          height: 18,
        },
      },
      { selector: 'node[kind = "dataset"]', style: { "background-color": "#4f8cff" } },
      { selector: 'node[kind = "job"]',     style: { "background-color": "#ff9f43", shape: "round-rectangle" } },
      {
        selector: 'node[current = "yes"]',
        style: { "border-width": 3, "border-color": "#ffffff", width: 24, height: 24 },
      },
      {
        selector: "edge",
        style: {
          "curve-style": "bezier",
          "target-arrow-shape": "triangle",
          width: 1.5,
          "line-color": "#4a5363",
          "target-arrow-color": "#4a5363",
          opacity: 0.85,
        },
      },
      { selector: 'edge[edgeType = "produces"]',     style: { "line-color": "#2ecc71", "target-arrow-color": "#2ecc71" } },
      { selector: 'edge[edgeType = "consumes"]',     style: { "line-color": "#ff7675", "target-arrow-color": "#ff7675" } },
      { selector: 'edge[edgeType = "derives_from"]', style: { "line-color": "#b39ddb", "target-arrow-color": "#b39ddb", "line-style": "dashed" } },
    ],
    layout: { name: "cose", animate: false, idealEdgeLength: 90, nodeRepulsion: 6000, padding: 24 },
    wheelSensitivity: 0.2,
  });

  cy.on("tap", "node", (evt) => {
    const newUrn = evt.target.id();
    if (newUrn !== currentNode) {
      currentNode = newUrn;
      renderGraph();
    }
  });
}

// ---------- Wire up ----------
$("#query").addEventListener("input", debounce(runSearch, 250));
$("#namespace").addEventListener("change", runSearch);
$("#reload").addEventListener("click", renderGraph);
$("#depth").addEventListener("change", () => currentNode && renderGraph());
$("#direction").addEventListener("change", () => currentNode && renderGraph());

loadNamespaces().catch(() => {});
