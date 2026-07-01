const state = {
  datasetId: null,
  cy: null,
  graph: null,
};

const palette = [
  "#2563eb",
  "#dc2626",
  "#16a34a",
  "#9333ea",
  "#ea580c",
  "#0891b2",
  "#be123c",
  "#4f46e5",
  "#65a30d",
  "#ca8a04",
];

const $ = (id) => document.getElementById(id);

function communityColor(community) {
  if (community < 0) return "#6b7280";
  return palette[community % palette.length];
}

function setText(id, value) {
  $(id).textContent = value;
}

function setBusy(message) {
  $("apply-status").textContent = message;
}

function params() {
  return {
    dataset_id: state.datasetId,
    method: $("method").value,
    epsilon: Number($("epsilon").value),
    k: Number($("k").value),
  };
}

function updateMethodControls() {
  const method = $("method").value;
  $("epsilon-control").classList.toggle("hidden", method !== "epsilon");
  $("k-control").classList.toggle("hidden", method !== "knn");
}

function enableExports(enabled) {
  $("export-csv").disabled = !enabled;
  $("export-json").disabled = !enabled;
  $("export-xlsx").disabled = !enabled;
}

async function uploadDataset(file) {
  const form = new FormData();
  form.append("file", file);
  $("apply").disabled = true;
  enableExports(false);
  setBusy("Lendo RIS e gerando embeddings...");
  $("dataset-status").textContent = file.name;

  const response = await fetch("/api/datasets", { method: "POST", body: form });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || "Falha ao carregar arquivo.");
  }

  const data = await response.json();
  state.datasetId = data.dataset_id;
  $("dataset-status").textContent = `${data.filename} - ${data.articles_count} artigos carregados`;
  $("apply").disabled = false;
  setBusy("Parametros prontos. Clique em APLICAR para construir o grafo.");
}

async function applyGraph() {
  if (!state.datasetId) return;
  $("apply").disabled = true;
  setBusy("Construindo grafo e detectando comunidades...");

  const response = await fetch("/api/graph", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params()),
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || "Falha ao construir grafo.");
  }

  const graph = await response.json();
  state.graph = graph;
  renderGraph(graph);
  renderStats(graph.stats);
  renderTimeline(graph.timeline || []);
  renderCommunities(graph.communities || [], graph.nodes);
  renderCommunityInsight(null);
  enableExports(true);
  setBusy("Grafo atualizado.");
  $("apply").disabled = false;
}

function cytoscapeElements(graph) {
  const nodes = graph.nodes.map((node) => ({
    group: "nodes",
    data: {
      ...node,
      label: "",
      color: communityColor(node.community),
      size: 14 + Math.min(node.degree, 30),
    },
    position: { x: node.x, y: node.y },
  }));

  const edges = graph.edges.map((edge) => ({
    group: "edges",
    data: {
      ...edge,
      width: 0.8 + Math.max(edge.weight, 0.01) * 3.2,
    },
  }));

  return [...nodes, ...edges];
}

function renderGraph(graph) {
  if (state.cy) {
    state.cy.destroy();
  }

  state.cy = cytoscape({
    container: $("cy"),
    elements: cytoscapeElements(graph),
    wheelSensitivity: 0.18,
    minZoom: 0.06,
    maxZoom: 5,
    layout: { name: "preset", fit: true, padding: 42 },
    style: [
      {
        selector: "node",
        style: {
          "background-color": "data(color)",
          "border-width": 1,
          "border-color": "#ffffff",
          label: "data(label)",
          "font-size": 10,
          color: "#111827",
          "text-outline-color": "#ffffff",
          "text-outline-width": 2,
          "text-valign": "center",
          "text-halign": "center",
          width: "data(size)",
          height: "data(size)",
          "overlay-opacity": 0,
        },
      },
      {
        selector: "edge",
        style: {
          width: "data(width)",
          "line-color": "#9ca3af",
          opacity: 0.38,
          "curve-style": "haystack",
          "haystack-radius": 0,
        },
      },
      {
        selector: "node:selected",
        style: {
          "border-color": "#111827",
          "border-width": 3,
        },
      },
      {
        selector: ".faded",
        style: {
          opacity: 0.1,
          "text-opacity": 0,
        },
      },
      {
        selector: ".highlighted",
        style: {
          opacity: 1,
          "z-index": 20,
        },
      },
      {
        selector: "node.community-focus",
        style: {
          "border-color": "#0f766e",
          "border-width": 4,
        },
      },
      {
        selector: "node.year-focus",
        style: {
          "border-color": "#2563eb",
          "border-width": 4,
        },
      },
      {
        selector: "edge.highlighted",
        style: {
          "line-color": "#111827",
          opacity: 0.78,
          "z-index": 20,
        },
      },
      {
        selector: ".hidden-by-search",
        style: {
          display: "none",
        },
      },
    ],
  });

  state.cy.on("tap", (event) => {
    if (event.target === state.cy) {
      clearSelection();
    }
  });

  state.cy.on("tap", "node", (event) => {
    const node = event.target;
    const neighborhood = node.closedNeighborhood();
    clearGraphHighlight();
    state.cy.elements().addClass("faded");
    neighborhood.removeClass("faded").addClass("highlighted");
    renderSelected(node.data());
  });

  state.cy.on("drag", "node", () => {
    $("graph-status").textContent = "moldando";
  });

  $("graph-status").textContent = "editavel";
  state.cy.fit(undefined, 42);
}

function runLayout() {
  if (!state.cy) return;
  $("graph-status").textContent = "organizando";
  const layout = state.cy.layout({
    name: "cose",
    animate: false,
    randomize: false,
    fit: true,
    padding: 44,
    numIter: 140,
    idealEdgeLength: 110,
    nodeRepulsion: 5800,
    edgeElasticity: 80,
    nestingFactor: 1.15,
    gravity: 0.28,
    componentSpacing: 90,
  });
  layout.on("layoutstop", () => {
    $("graph-status").textContent = "editavel";
  });
  layout.run();
}

function renderStats(stats) {
  setText("m-nodes", stats.nodes);
  setText("m-edges", stats.edges);
  setText("m-communities", stats.communities);
  setText("m-density", Number(stats.density).toFixed(3));
  setText("m-degree", Number(stats.average_degree).toFixed(2));
  setText("m-isolates", stats.isolated_nodes);
}

function renderTimeline(timeline) {
  if (!timeline.length) {
    $("timeline").classList.add("empty");
    $("timeline").textContent = "Sem anos validos nos metadados.";
    return;
  }

  const maxCount = Math.max(...timeline.map((row) => row.count));
  $("timeline").classList.remove("empty");
  $("timeline").innerHTML = timeline
    .map((row) => {
      const width = Math.max(6, (row.count / maxCount) * 100);
      return `
        <div class="timeline-row" data-year="${row.year}">
          <span>${row.year}</span>
          <div class="timeline-track"><div class="timeline-fill" style="width: ${width}%"></div></div>
          <strong>${row.count}</strong>
        </div>
      `;
    })
    .join("");

  document.querySelectorAll(".timeline-row").forEach((row) => {
    row.addEventListener("click", () => highlightYear(row.dataset.year));
  });
}

function renderCommunities(communities, nodes) {
  if (!communities.length) {
    $("communities").classList.add("empty");
    $("communities").textContent = "Nenhuma comunidade calculada.";
    return;
  }

  const maxCount = Math.max(...communities.map((community) => community.size));
  $("communities").classList.remove("empty");
  $("communities").innerHTML = communities
    .map((community) => {
      const width = Math.max(6, (community.size / maxCount) * 100);
      return `
      <div class="community-item" data-community="${community.id}">
        <span>Comunidade ${community.id}</span>
        <strong>${community.size}</strong>
        <div class="community-bar">
          <div class="community-fill" style="width: ${width}%; background: ${communityColor(community.id)}"></div>
        </div>
      </div>
    `;
    })
    .join("");

  document.querySelectorAll(".community-item").forEach((row) => {
    row.addEventListener("click", () => {
      const communityId = Number(row.dataset.community);
      const summary = communities.find((community) => community.id === communityId);
      highlightCommunity(communityId);
      renderCommunityInsight(summary);
    });
  });
}

function renderSelected(node) {
  $("selected-node").classList.remove("empty");
  $("selected-node").innerHTML = `
    <h3>${escapeHtml(node.title || `Artigo ${node.id}`)}</h3>
    <p><strong>ID:</strong> ${escapeHtml(node.id)}</p>
    <p><strong>Ano:</strong> ${escapeHtml(node.year || "N/A")}</p>
    <p><strong>Autores:</strong> ${escapeHtml(node.authors || "N/A")}</p>
    <p><strong>DOI:</strong> ${escapeHtml(node.doi || "N/A")}</p>
    <p><strong>Comunidade:</strong> ${escapeHtml(String(node.community))}</p>
    <p><strong>Grau:</strong> ${escapeHtml(String(node.degree))}</p>
    ${node.keywords ? `<p><strong>Palavras-chave:</strong> ${escapeHtml(node.keywords)}</p>` : ""}
    ${node.abstract ? `<div class="abstract"><p>${escapeHtml(node.abstract)}</p></div>` : ""}
  `;
}

function renderCommunityInsight(summary) {
  const target = $("community-insight");
  if (!summary) {
    target.classList.add("empty");
    target.textContent = "Clique em uma comunidade.";
    return;
  }

  target.classList.remove("empty");
  const terms = summary.terms && summary.terms.length
    ? summary.terms
        .map((term) => `<span class="term-chip">${escapeHtml(term.term)}</span>`)
        .join("")
    : `<span class="muted">Sem termos suficientes.</span>`;

  const period = summary.year_min && summary.year_max
    ? `${summary.year_min} - ${summary.year_max}`
    : "N/A";

  target.innerHTML = `
    <div class="insight-metrics">
      <div><span>${summary.size}</span><small>artigos</small></div>
      <div><span>${escapeHtml(period)}</span><small>periodo</small></div>
    </div>
    <strong>Termos representativos</strong>
    <div class="term-cloud">${terms}</div>
    <div class="representative">
      <strong>Representante da comunidade</strong>
      <h3>${escapeHtml(summary.representative.title || `Artigo ${summary.representative.id}`)}</h3>
      <p><strong>Ano:</strong> ${escapeHtml(summary.representative.year || "N/A")}</p>
      <p><strong>Autores:</strong> ${escapeHtml(summary.representative.authors || "N/A")}</p>
      <p><strong>Forca interna:</strong> ${Number(summary.representative.strength).toFixed(3)}</p>
    </div>
  `;
}

function clearGraphHighlight() {
  if (!state.cy) return;
  state.cy.elements().removeClass("faded highlighted community-focus year-focus");
}

function clearSelection() {
  if (!state.cy) return;
  clearGraphHighlight();
  $("selected-node").classList.add("empty");
  $("selected-node").textContent = "Clique em um no do grafo.";
}

function highlightCommunity(communityId) {
  if (!state.cy) return;
  clearGraphHighlight();
  const nodes = state.cy.nodes().filter((node) => Number(node.data("community")) === communityId);
  const internalEdges = state.cy.edges().filter((edge) => (
    Number(edge.source().data("community")) === communityId
    && Number(edge.target().data("community")) === communityId
  ));
  const focus = nodes.union(internalEdges);
  state.cy.elements().addClass("faded");
  focus.removeClass("faded").addClass("highlighted community-focus");
  if (nodes.length > 0) {
    state.cy.fit(nodes, 54);
  }
  $("graph-status").textContent = `comunidade ${communityId}`;
}

function highlightYear(year) {
  if (!state.cy) return;
  clearGraphHighlight();
  const nodes = state.cy.nodes().filter((node) => String(node.data("year")) === String(year));
  const yearEdges = state.cy.edges().filter((edge) => (
    String(edge.source().data("year")) === String(year)
    && String(edge.target().data("year")) === String(year)
  ));
  const focus = nodes.union(yearEdges);
  state.cy.elements().addClass("faded");
  focus.removeClass("faded").addClass("highlighted year-focus");
  if (nodes.length > 0) {
    state.cy.fit(nodes, 54);
  }
  $("graph-status").textContent = `ano ${year}`;
}

function applySearch() {
  if (!state.cy) return;
  const needle = $("search").value.trim().toLowerCase();
  state.cy.elements().removeClass("hidden-by-search");
  if (!needle) {
    state.cy.fit(undefined, 42);
    return;
  }

  const matched = state.cy.nodes().filter((node) => {
    const data = node.data();
    return [data.title, data.authors, data.doi]
      .join(" ")
      .toLowerCase()
      .includes(needle);
  });

  const visible = matched.closedNeighborhood();
  state.cy.elements().difference(visible).addClass("hidden-by-search");
  if (visible.length > 0) {
    state.cy.fit(visible, 42);
  }
}

function exportUrl(kind) {
  if (!state.datasetId) return;
  window.location.href = `/api/export/${state.datasetId}/${kind}`;
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

$("method").addEventListener("change", updateMethodControls);
$("epsilon").addEventListener("input", () => {
  $("epsilon-value").textContent = Number($("epsilon").value).toFixed(2);
  setBusy("Parametros alterados. Clique em APLICAR para atualizar.");
});
$("k").addEventListener("input", () => {
  $("k-value").textContent = $("k").value;
  setBusy("Parametros alterados. Clique em APLICAR para atualizar.");
});
$("file-input").addEventListener("change", async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  try {
    await uploadDataset(file);
  } catch (error) {
    setBusy(error.message);
    $("dataset-status").textContent = "Falha no carregamento.";
  }
});
$("apply").addEventListener("click", async () => {
  try {
    await applyGraph();
  } catch (error) {
    setBusy(error.message);
    $("apply").disabled = false;
  }
});
$("search").addEventListener("input", applySearch);
$("layout").addEventListener("click", runLayout);
$("lock").addEventListener("click", () => {
  if (!state.cy) return;
  state.cy.nodes().ungrabify();
  $("graph-status").textContent = "travado";
});
$("unlock").addEventListener("click", () => {
  if (!state.cy) return;
  state.cy.nodes().grabify();
  $("graph-status").textContent = "editavel";
});
$("fit").addEventListener("click", () => {
  if (!state.cy) return;
  state.cy.fit(undefined, 42);
  $("graph-status").textContent = "centralizado";
});
$("export-csv").addEventListener("click", () => exportUrl("csv"));
$("export-json").addEventListener("click", () => exportUrl("json"));
$("export-xlsx").addEventListener("click", () => exportUrl("xlsx"));

updateMethodControls();
