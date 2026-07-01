from __future__ import annotations

from io import StringIO
from typing import Any
from functools import lru_cache

import networkx as nx
import numpy as np
import pandas as pd
import rispy
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity


def _join_values(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return "; ".join(str(item) for item in value if item)
    return str(value)


def parse_ris(raw_text: str) -> pd.DataFrame:
    records = rispy.load(StringIO(raw_text))
    rows: list[dict[str, Any]] = []

    for index, record in enumerate(records):
        title = _join_values(record.get("title") or record.get("primary_title"))
        abstract = _join_values(record.get("abstract"))
        keywords = _join_values(record.get("keywords"))
        authors = _join_values(record.get("authors"))
        year = _join_values(record.get("year") or record.get("publication_year"))
        doi = _join_values(record.get("doi"))

        text_representation = " ".join(
            part for part in [title, abstract, keywords] if part
        ).strip()

        if not text_representation:
            continue

        rows.append(
            {
                "id": index,
                "title": title or f"Artigo {index + 1}",
                "abstract": abstract,
                "keywords": keywords,
                "authors": authors,
                "year": year,
                "doi": doi,
                "text_representation": text_representation,
            }
        )

    return pd.DataFrame(rows)


@lru_cache(maxsize=1)
def _load_model() -> SentenceTransformer:
    return SentenceTransformer("all-MiniLM-L6-v2")


def compute_embeddings(texts: list[str]) -> np.ndarray:
    model = _load_model()
    return model.encode(texts, normalize_embeddings=True, show_progress_bar=False)


def build_similarity_graph(
    articles: pd.DataFrame,
    embeddings: np.ndarray,
    method: str,
    epsilon: float,
    k: int,
) -> tuple[nx.Graph, pd.DataFrame]:
    similarities = cosine_similarity(embeddings)
    graph = nx.Graph()

    for row in articles.itertuples(index=False):
        graph.add_node(
            int(row.id),
            title=row.title,
            year=row.year,
            doi=row.doi,
        )

    edge_rows: list[dict[str, Any]] = []
    node_ids = articles["id"].astype(int).tolist()

    if method == "epsilon":
        for i, source in enumerate(node_ids):
            for j in range(i + 1, len(node_ids)):
                target = node_ids[j]
                similarity = float(similarities[i, j])
                if similarity >= epsilon:
                    graph.add_edge(source, target, weight=similarity)
                    edge_rows.append(
                        {"source": source, "target": target, "weight": similarity}
                    )
    elif method == "knn":
        max_neighbors = min(k, len(node_ids) - 1)
        for i, source in enumerate(node_ids):
            nearest = np.argsort(similarities[i])[::-1]
            for j in nearest:
                if i == j:
                    continue
                target = node_ids[j]
                similarity = float(similarities[i, j])
                if similarity <= 0:
                    continue
                graph.add_edge(source, target, weight=similarity)
                if graph.degree[source] >= max_neighbors:
                    break
        edge_rows = [
            {"source": int(source), "target": int(target), "weight": float(data["weight"])}
            for source, target, data in graph.edges(data=True)
        ]
    else:
        raise ValueError(f"Metodo desconhecido: {method}")

    edges = pd.DataFrame(edge_rows, columns=["source", "target", "weight"]).drop_duplicates(
        subset=["source", "target"], keep="first"
    )
    return graph, edges


def detect_communities(graph: nx.Graph) -> dict[int, int]:
    if graph.number_of_nodes() == 0:
        return {}
    if graph.number_of_edges() == 0:
        return {node: index for index, node in enumerate(graph.nodes)}
    total_weight = graph.size(weight="weight")
    if total_weight <= 0:
        return {node: index for index, node in enumerate(graph.nodes)}

    communities = nx.community.louvain_communities(graph, weight="weight", seed=42)
    mapping: dict[int, int] = {}
    for community_id, nodes in enumerate(communities):
        for node in nodes:
            mapping[int(node)] = community_id
    return mapping


def graph_statistics(graph: nx.Graph, articles: pd.DataFrame) -> dict[str, Any]:
    community_count = int(articles["community"].nunique()) if "community" in articles else 0
    degrees = dict(graph.degree())
    average_degree = float(np.mean(list(degrees.values()))) if degrees else 0.0

    return {
        "nodes": graph.number_of_nodes(),
        "edges": graph.number_of_edges(),
        "communities": community_count,
        "density": nx.density(graph) if graph.number_of_nodes() > 1 else 0.0,
        "average_degree": average_degree,
        "isolated_nodes": nx.number_of_isolates(graph),
    }
