"""Graph analysis helpers using NetworkX.

This module provides functions to compute common centrality measures and
community detection algorithms. These functions accept a NetworkX graph and
return results but do not mutate or apply them to any stored graphs.

Functions:
- degree_centrality
- closeness_centrality
- betweenness_centrality
- eigenvector_centrality
- community_detection

These are thin wrappers over NetworkX implementations and intended to be
called by other components when analysis is desired.
"""
from typing import Any, Dict, Iterable, List, Optional, Set

import networkx as nx
from networkx.algorithms import community as nx_community
from typing import Mapping


def degree_centrality(G: nx.Graph, normalized: bool = True) -> Dict[Any, float]:
    """Return degree centrality for graph G.

    If normalized=True (default) returns values in [0, 1] following
    NetworkX's degree_centrality definition. If normalized=False returns
    raw degree counts for each node.
    """
    if normalized:
        return nx.degree_centrality(G)
    # raw degree counts
    return {n: d for n, d in G.degree()}


def closeness_centrality(G: nx.Graph, u: Optional[Any] = None, distance: Optional[str] = None) -> Dict[Any, float]:
    """Compute closeness centrality for G.

    If `u` is provided, compute for a single node (returns a dict with that node).
    `distance` can be the edge attribute used as distance/weight.
    """
    if u is not None:
        return {u: nx.closeness_centrality(G, u=u, distance=distance)}
    return nx.closeness_centrality(G, distance=distance)


def betweenness_centrality(
    G: nx.Graph,
    k: Optional[int] = None,
    normalized: bool = True,
    weight: Optional[str] = None,
    endpoints: bool = False,
    seed: Optional[int] = None,
) -> Dict[Any, float]:
    """Compute betweenness centrality for G.

    - k: if set, uses approximate algorithm with k node samples (faster)
    - normalized, weight, endpoints, seed: forwarded to NetworkX
    """
    if k is not None:
        # approximate algorithm
        return nx.betweenness_centrality(G, k=k, normalized=normalized, weight=weight, endpoints=endpoints, seed=seed)
    return nx.betweenness_centrality(G, normalized=normalized, weight=weight, endpoints=endpoints)


def eigenvector_centrality(
    G: nx.Graph,
    max_iter: int = 100,
    tol: float = 1.0e-6,
    weight: Optional[str] = None,
) -> Dict[Any, float]:
    """Compute eigenvector centrality for G.

    Falls back to the numpy-based solver if the power-iteration method fails.
    """
    try:
        return nx.eigenvector_centrality(G, max_iter=max_iter, tol=tol, weight=weight)
    except Exception:
        try:
            return nx.eigenvector_centrality_numpy(G, weight=weight)
        except Exception as e:
            raise RuntimeError(f"Eigenvector centrality failed: {e}")


def community_detection(G: nx.Graph, method: str = "greedy", **kwargs) -> List[Set[Any]]:
    """Run community detection on G and return a list of node-sets (communities).

    Supported methods:
    - 'greedy': greedy_modularity_communities (default)
    - 'lpa': asynchronous label propagation (asyn_lpa_communities)
    - 'girvan_newman': returns the first partition level from Girvan-Newman

    Additional kwargs are forwarded to the underlying NetworkX functions where applicable.
    """
    method = method.lower()
    if method in ("greedy", "modularity", "greedy_modularity"):
        communities = nx_community.greedy_modularity_communities(G, **kwargs)
        return [set(c) for c in communities]
    if method in ("lpa", "asyn_lpa", "label_propagation", "asynchronous_label_propagation"):
        communities = nx_community.asyn_lpa_communities(G, **kwargs)
        return [set(c) for c in communities]
    if method in ("girvan_newman", "girvan"):
        comp_gen = nx_community.girvan_newman(G)
        # Return the first level partition (split into two communities) by default
        try:
            first_level = next(comp_gen)
            return [set(c) for c in first_level]
        except StopIteration:
            return []

    raise ValueError(f"Unknown community detection method: {method}")


# Mapping of algorithm short names to functions in this module
ALGORITHM_MAP: Mapping[str, Any] = {
    "degree": degree_centrality,
    "closeness": closeness_centrality,
    "betweenness": betweenness_centrality,
    "eigenvector": eigenvector_centrality,
    "community": community_detection,
}


def _build_subgraph_by_labels_and_edge_types(
    G: nx.Graph, *, node_labels: Optional[Iterable[str]] = None, edge_types: Optional[Iterable[str]] = None
) -> nx.Graph:
    """Return a subgraph containing nodes that match any of `node_labels` and
    only edges whose ``neo4j_type`` attribute is in `edge_types` (if provided).

    - `node_labels` filters nodes by presence in their `neo4j_labels` node attribute
      (which is expected to be a list of strings produced by the Neo4j exporter).
    - `edge_types` filters edges by the relationship type stored in edge attr
      `neo4j_type`.
    The returned graph is an induced subgraph on the selected nodes with filtered edges.
    """
    # If no node label filter is provided, start with all nodes
    if node_labels:
        label_set = set(node_labels)
        selected_nodes = [n for n, d in G.nodes(data=True) if any(l in label_set for l in d.get("neo4j_labels", []))]
    else:
        selected_nodes = list(G.nodes())

    # Create an induced subgraph on those nodes
    sub = G.subgraph(selected_nodes).copy()

    # If edge_types provided, remove edges that do not match
    if edge_types:
        edge_type_set = set(edge_types)
        to_remove = []
        # For MultiGraph, iterate keys
        if sub.is_multigraph():
            for u, v, k, d in list(sub.edges(keys=True, data=True)):
                if d.get("neo4j_type") not in edge_type_set:
                    to_remove.append((u, v, k))
            for u, v, k in to_remove:
                try:
                    sub.remove_edge(u, v, key=k)
                except Exception:
                    pass
        else:
            for u, v, d in list(sub.edges(data=True)):
                if d.get("neo4j_type") not in edge_type_set:
                    to_remove.append((u, v))
            for u, v in to_remove:
                try:
                    sub.remove_edge(u, v)
                except Exception:
                    pass

    return sub


def run_algorithms_on_subgraphs(G: nx.Graph, specs: Iterable[dict], *, print_results: bool = True) -> dict:
    """Run specified algorithms on subgraphs derived from G.

    `specs` is an iterable of dictionaries with the following keys:
      - name: str, human name for this subgraph/analysis
      - node_labels: Optional[list[str]] - node labels to include (e.g., ["Pod","KubeNode"])
      - edge_types: Optional[list[str]] - relationship types to keep (e.g., ["RUNS_ON"]) 
      - algorithm: str - one of 'degree','closeness','betweenness','eigenvector','community'
      - algorithm_kwargs: Optional[dict] forwarded to the algorithm function

    The function returns a dict mapping spec name -> algorithm result. It also prints
    concise results when `print_results` is True in the format requested:

      resources (nodes=X edges=Y) in <name> + <algorithm> -> <value(s)>

    Note: algorithms are run on the constructed subgraph, not on the full graph.
    """
    results = {}
    for spec in specs:
        name = spec.get("name") or "unnamed"
        node_labels = spec.get("node_labels")
        edge_types = spec.get("edge_types")
        algorithm = spec.get("algorithm")
        algo_kwargs = spec.get("algorithm_kwargs") or {}

        if algorithm not in ALGORITHM_MAP:
            raise ValueError(f"Unknown algorithm '{algorithm}'. Supported: {list(ALGORITHM_MAP.keys())}")
        print(f"Running '{algorithm}' on subgraph '{name}'...")
        sub = _build_subgraph_by_labels_and_edge_types(G, node_labels=node_labels, edge_types=edge_types)
        print(f"Subgraph '{name}' has {sub.number_of_nodes()} nodes and {sub.number_of_edges()} edges.")
        # Run the algorithm
        func = ALGORITHM_MAP[algorithm]
        # Special handling: ensure betweenness sample size 'k' is valid
        if algorithm == "betweenness":
            k = algo_kwargs.get("k")
            n_nodes = max(0, sub.number_of_nodes())
            if k is not None:
                try:
                    k_int = int(k)
                except Exception:
                    k_int = None
                # If requested sample is >= population, fall back to exact algorithm (k=None)
                if k_int is not None and k_int >= n_nodes:
                    algo_kwargs = {**algo_kwargs}
                    algo_kwargs.pop("k", None)

        try:
            value = func(sub, **algo_kwargs)
        except Exception as e:
            value = {"error": str(e)}

        results[name] = {"algorithm": algorithm, "nodes": sub.number_of_nodes(), "edges": sub.number_of_edges(), "result": value}

        if print_results:
            header = f"resources (nodes={sub.number_of_nodes()} edges={sub.number_of_edges()}) in '{name}' + {algorithm} ->"
            print(header)
            # Pretty-print based on result type
            if isinstance(value, dict):
                # centrality dict: print one line per node
                # Optionally support top_k in spec to limit output
                top_k = spec.get("top_k")
                items = list(value.items())
                # Sort by value descending for centrality-like measures
                try:
                    items.sort(key=lambda x: x[1], reverse=True)
                except Exception:
                    items.sort(key=lambda x: str(x[0]))

                if top_k is not None:
                    try:
                        top_k_i = int(top_k)
                        items = items[:top_k_i]
                    except Exception:
                        pass

                for n, v in items:
                    # Resolve a readable id: prefer node attr 'composite_key' then 'neo4j_labels' etc.
                    label = None
                    try:
                        data = sub.nodes[n]
                        label = data.get("composite_key") or data.get("name")
                    except Exception:
                        label = None
                    display_n = label if label is not None else n
                    print(f"  {display_n} -> {v}")
            elif isinstance(value, list):
                # community list of sets
                for i, comm in enumerate(value, start=1):
                    print(f"  community {i} (size={len(comm)}): {sorted(list(comm))}")
            else:
                print(f"  {value}")

    return results

