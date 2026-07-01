from __future__ import annotations

import json
import math
import tempfile
import uuid
from pathlib import Path
from typing import Any

import networkx as nx
import pandas as pd
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS, TfidfVectorizer

from src.pipeline import (
    build_similarity_graph,
    compute_embeddings,
    detect_communities,
    graph_statistics,
    parse_ris,
)


ROOT = Path(__file__).parent
STATIC_DIR = ROOT / "static"

app = FastAPI(title="Similarity Graph Explorer")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

DATASETS: dict[str, dict[str, Any]] = {}

EXTRA_STOP_WORDS = {
    "study",
    "studies",
    "paper",
    "article",
    "research",
    "results",
    "method",
    "methods",
    "analysis",
    "approach",
    "based",
    "using",
    "use",
    "used",
    "data",
    "model",
    "models",
    "system",
    "systems",
}


class GraphRequest(BaseModel):
    dataset_id: str
    method: str
    epsilon: float = Field(default=0.45, ge=0.0, le=1.0)
    k: int = Field(default=8, ge=1, le=100)


def _clean(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    return str(value)


def _graph_positions(articles: pd.DataFrame, edges: pd.DataFrame) -> dict[int, dict[str, float]]:
    graph = nx.Graph()
    graph.add_nodes_from(int(article_id) for article_id in articles["id"])

    for edge in edges.itertuples(index=False):
        graph.add_edge(int(edge.source), int(edge.target), weight=float(edge.weight))

    if graph.number_of_nodes() == 0:
        return {}
    if graph.number_of_edges() == 0:
        positions = nx.circular_layout(graph)
    else:
        positions = nx.spring_layout(
            graph,
            weight="weight",
            seed=42,
            iterations=90,
            k=1 / math.sqrt(max(graph.number_of_nodes(), 1)),
        )

    return {
        int(node): {"x": float(position[0]) * 900, "y": float(position[1]) * 900}
        for node, position in positions.items()
    }


def _community_summaries(articles: pd.DataFrame, edges: pd.DataFrame) -> list[dict[str, Any]]:
    if articles.empty or "community" not in articles:
        return []

    edge_strength: dict[int, float] = {int(article_id): 0.0 for article_id in articles["id"]}
    for edge in edges.itertuples(index=False):
        source = int(edge.source)
        target = int(edge.target)
        weight = float(edge.weight)
        edge_strength[source] = edge_strength.get(source, 0.0) + weight
        edge_strength[target] = edge_strength.get(target, 0.0) + weight

    community_docs: list[str] = []
    community_ids: list[int] = []
    grouped = articles.groupby("community", sort=True)
    for community_id, group in grouped:
        community_ids.append(int(community_id))
        community_docs.append(" ".join(group["text_representation"].fillna("").astype(str)))

    term_map: dict[int, list[dict[str, Any]]] = {community_id: [] for community_id in community_ids}
    if len(community_docs) == 1:
        vectorizer = TfidfVectorizer(
            max_features=12,
            stop_words=list(ENGLISH_STOP_WORDS.union(EXTRA_STOP_WORDS)),
            ngram_range=(1, 2),
            token_pattern=r"(?u)\b[a-zA-Z][a-zA-Z\-]{2,}\b",
        )
    else:
        vectorizer = TfidfVectorizer(
            max_features=500,
            stop_words=list(ENGLISH_STOP_WORDS.union(EXTRA_STOP_WORDS)),
            ngram_range=(1, 2),
            token_pattern=r"(?u)\b[a-zA-Z][a-zA-Z\-]{2,}\b",
        )

    try:
        matrix = vectorizer.fit_transform(community_docs)
        terms = vectorizer.get_feature_names_out()
        for row_index, community_id in enumerate(community_ids):
            scores = matrix[row_index].toarray()[0]
            top_indexes = scores.argsort()[::-1][:8]
            term_map[community_id] = [
                {"term": terms[index], "score": float(scores[index])}
                for index in top_indexes
                if scores[index] > 0
            ]
    except ValueError:
        pass

    summaries = []
    for community_id, group in grouped:
        community_id = int(community_id)
        ranked = group.copy()
        ranked["_strength"] = ranked["id"].map(edge_strength).fillna(0.0)
        ranked = ranked.sort_values(["_strength", "title"], ascending=[False, True])
        representative = ranked.iloc[0]
        years = [
            int(str(year))
            for year in group["year"].dropna()
            if str(year).isdigit()
        ]

        summaries.append(
            {
                "id": community_id,
                "size": int(len(group)),
                "terms": term_map.get(community_id, []),
                "representative": {
                    "id": str(int(representative["id"])),
                    "title": _clean(representative["title"]),
                    "year": _clean(representative["year"]),
                    "doi": _clean(representative["doi"]),
                    "authors": _clean(representative["authors"]),
                    "strength": float(representative["_strength"]),
                },
                "year_min": min(years) if years else None,
                "year_max": max(years) if years else None,
            }
        )

    return sorted(summaries, key=lambda item: item["size"], reverse=True)


def _timeline(articles: pd.DataFrame) -> list[dict[str, Any]]:
    years = pd.to_numeric(articles["year"], errors="coerce").dropna().astype(int)
    if years.empty:
        return []

    counts = years.value_counts().sort_index()
    return [
        {"year": int(year), "count": int(count)}
        for year, count in counts.items()
    ]


def _graph_payload(articles: pd.DataFrame, edges: pd.DataFrame, stats: dict[str, Any]) -> dict[str, Any]:
    positions = _graph_positions(articles, edges)
    degrees = {int(article_id): 0 for article_id in articles["id"]}

    for edge in edges.itertuples(index=False):
        degrees[int(edge.source)] = degrees.get(int(edge.source), 0) + 1
        degrees[int(edge.target)] = degrees.get(int(edge.target), 0) + 1

    nodes = []
    for row in articles.itertuples(index=False):
        node_id = int(row.id)
        nodes.append(
            {
                "id": str(node_id),
                "title": _clean(row.title),
                "abstract": _clean(row.abstract),
                "keywords": _clean(row.keywords),
                "authors": _clean(row.authors),
                "year": _clean(row.year),
                "doi": _clean(row.doi),
                "community": int(row.community),
                "degree": degrees.get(node_id, 0),
                "x": positions.get(node_id, {"x": 0})["x"],
                "y": positions.get(node_id, {"y": 0})["y"],
            }
        )

    edge_rows = [
        {
            "id": f"e{index}",
            "source": str(int(edge.source)),
            "target": str(int(edge.target)),
            "weight": float(edge.weight),
        }
        for index, edge in enumerate(edges.itertuples(index=False))
    ]

    return {
        "nodes": nodes,
        "edges": edge_rows,
        "stats": stats,
        "communities": _community_summaries(articles, edges),
        "timeline": _timeline(articles),
    }


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.post("/api/datasets")
async def create_dataset(file: UploadFile = File(...)) -> dict[str, Any]:
    if not file.filename.lower().endswith(".ris"):
        raise HTTPException(status_code=400, detail="Envie um arquivo .ris.")

    raw = await file.read()
    raw_text = raw.decode("utf-8", errors="ignore")
    articles = parse_ris(raw_text)

    if articles.empty:
        raise HTTPException(status_code=400, detail="Nenhum artigo valido foi encontrado.")

    embeddings = compute_embeddings(articles["text_representation"].tolist())
    dataset_id = str(uuid.uuid4())
    DATASETS[dataset_id] = {
        "filename": file.filename,
        "articles": articles,
        "embeddings": embeddings,
        "last_result": None,
    }

    preview_cols = ["id", "title", "year", "authors", "doi"]
    return {
        "dataset_id": dataset_id,
        "filename": file.filename,
        "articles_count": len(articles),
        "preview": articles[preview_cols].head(20).to_dict(orient="records"),
    }


@app.post("/api/graph")
def build_graph(request: GraphRequest) -> dict[str, Any]:
    dataset = DATASETS.get(request.dataset_id)
    if dataset is None:
        raise HTTPException(status_code=404, detail="Dataset nao encontrado.")
    if request.method not in {"epsilon", "knn"}:
        raise HTTPException(status_code=400, detail="Metodo invalido.")

    graph, edges = build_similarity_graph(
        articles=dataset["articles"],
        embeddings=dataset["embeddings"],
        method=request.method,
        epsilon=request.epsilon,
        k=request.k,
    )
    communities = detect_communities(graph)
    articles = dataset["articles"].copy()
    articles["community"] = articles["id"].map(communities).fillna(-1).astype(int)
    stats = graph_statistics(graph, articles)
    payload = _graph_payload(articles, edges, stats)

    dataset["last_result"] = {
        "articles": articles,
        "edges": edges,
        "stats": stats,
        "payload": payload,
        "params": request.dict(),
    }
    return payload


@app.get("/api/export/{dataset_id}/json")
def export_json(dataset_id: str) -> Response:
    result = _last_result(dataset_id)
    content = json.dumps(
        {
            "nodes": result["payload"]["nodes"],
            "edges": result["payload"]["edges"],
            "communities": result["payload"].get("communities", []),
            "timeline": result["payload"].get("timeline", []),
            "stats": result["stats"],
            "params": result["params"],
        },
        ensure_ascii=False,
        indent=2,
    )
    return Response(
        content,
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=similarity_graph.json"},
    )


@app.get("/api/export/{dataset_id}/csv")
def export_csv(dataset_id: str) -> Response:
    result = _last_result(dataset_id)
    articles = result["articles"].drop(columns=["text_representation"])
    return Response(
        articles.to_csv(index=False),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=articles_with_communities.csv"},
    )


@app.get("/api/export/{dataset_id}/xlsx")
def export_xlsx(dataset_id: str) -> FileResponse:
    result = _last_result(dataset_id)
    tmp = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
    path = Path(tmp.name)
    tmp.close()

    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        result["articles"].drop(columns=["text_representation"]).to_excel(
            writer, index=False, sheet_name="articles"
        )
        result["edges"].to_excel(writer, index=False, sheet_name="edges")
        pd.DataFrame([result["stats"]]).to_excel(writer, index=False, sheet_name="stats")

    return FileResponse(
        path,
        filename="similarity_graph_results.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def _last_result(dataset_id: str) -> dict[str, Any]:
    dataset = DATASETS.get(dataset_id)
    if dataset is None or dataset.get("last_result") is None:
        raise HTTPException(status_code=404, detail="Execute APLICAR antes de exportar.")
    return dataset["last_result"]
