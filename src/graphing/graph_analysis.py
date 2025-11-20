from typing import Any, Dict, Iterable, List, Optional, Set, Tuple, Mapping
import math
import logging

import networkx as nx
from networkx.algorithms import community as nx_community


def degree_centrality(G: nx.Graph, normalized: bool = True) -> Dict[Any, float]:
    if normalized:
        return nx.degree_centrality(G)
    return {n: d for n, d in G.degree()}


def closeness_centrality(G: nx.Graph, u: Optional[Any] = None, distance: Optional[str] = None) -> Dict[Any, float]:
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
    if k is not None:
        return nx.betweenness_centrality(G, k=k, normalized=normalized, weight=weight, endpoints=endpoints, seed=seed)
    return nx.betweenness_centrality(G, normalized=normalized, weight=weight, endpoints=endpoints)


def eigenvector_centrality(
    G: nx.Graph,
    max_iter: int = 100,
    tol: float = 1.0e-6,
    weight: Optional[str] = None,
) -> Dict[Any, float]:
    try:
        return nx.eigenvector_centrality(G, max_iter=max_iter, tol=tol, weight=weight)
    except Exception as e1:
        try:
            return nx.eigenvector_centrality_numpy(G, weight=weight)
        except Exception as e2:
            try:
                logging.getLogger(__name__).warning(
                    "Eigenvector centrality fallback: power-iteration failed (%s) and numpy/scipy solver failed (%s); using degree centrality as fallback",
                    e1,
                    e2,
                )
            except Exception:
                pass
            try:
                return nx.degree_centrality(G)
            except Exception:
                return {n: 0.0 for n in G.nodes()}


def community_detection(G: nx.Graph, method: str = "greedy", **kwargs) -> List[Set[Any]]:
    method = method.lower()
    if method in ("greedy", "modularity", "greedy_modularity"):
        communities = nx_community.greedy_modularity_communities(G, **kwargs)
        return [set(c) for c in communities]
    if method in ("lpa", "asyn_lpa", "label_propagation", "asynchronous_label_propagation"):
        communities = nx_community.asyn_lpa_communities(G, **kwargs)
        return [set(c) for c in communities]
    if method in ("girvan_newman", "girvan"):
        comp_gen = nx_community.girvan_newman(G)
        try:
            first_level = next(comp_gen)
            return [set(c) for c in first_level]
        except StopIteration:
            return []

    raise ValueError(f"Unknown community detection method: {method}")


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

    if node_labels:
        label_set = set(node_labels)
        selected_nodes = [n for n, d in G.nodes(data=True) if any(l in label_set for l in d.get("neo4j_labels", []))]
    else:
        selected_nodes = list(G.nodes())

    sub = G.subgraph(selected_nodes).copy()

    if edge_types:
        edge_type_set = set(edge_types)
        to_remove = []
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


def _resolve_display_name(G: nx.Graph, n: Any) -> str:
    try:
        data = G.nodes[n]
        return data.get("composite_key") or data.get("name") or str(n)
    except Exception:
        return str(n)


def _sort_top(d: Dict[Any, float], k: int = 10) -> list:
    items = list(d.items())
    try:
        items.sort(key=lambda x: x[1], reverse=True)
    except Exception:
        items.sort(key=lambda x: str(x[0]))
    return items[:k]


def compute_entropy(vals: List[int], n: int) -> float:
    h = 0.0
    for v in vals:
        if v == 0:
            continue
        p = v / n
        h -= p * math.log(p)
    return h


def compute_nmi(prev_map: Dict[str, int], cur_map: Dict[str, int]) -> float:
    inter_keys = [k for k in cur_map.keys() if k in prev_map]
    n = len(inter_keys)
    if n == 0:
        return 0.0
    prev_ids = {prev_map[k] for k in inter_keys}
    curr_ids = {cur_map[k] for k in inter_keys}
    prev_index = {cid: i for i, cid in enumerate(sorted(prev_ids))}
    curr_index = {cid: j for j, cid in enumerate(sorted(curr_ids))}
    r = len(prev_index)
    c = len(curr_index)
    N = [[0 for _ in range(c)] for __ in range(r)]
    for k in inter_keys:
        i = prev_index[prev_map[k]]
        j = curr_index[cur_map[k]]
        N[i][j] += 1
    row = [sum(N[i][j] for j in range(c)) for i in range(r)]
    col = [sum(N[i][j] for i in range(r)) for j in range(c)]
    MI = 0.0
    for i in range(r):
        for j in range(c):
            if N[i][j] == 0:
                continue
            MI += (N[i][j] / n) * math.log((n * N[i][j]) / (row[i] * col[j]))
    H_prev = compute_entropy(row, n)
    H_curr = compute_entropy(col, n)
    denom = math.sqrt(H_prev * H_curr)
    if denom == 0:
        return 1.0 if all(prev_map[k] == cur_map[k] for k in inter_keys) else 0.0
    return MI / denom


def flag_increases(cur: Dict[Any, float], base: Dict[str, float], factor: float, subG: nx.Graph, top_k: int = 10) -> List[Tuple[str, float, float]]:
    flags: List[Tuple[str, float, float]] = []
    ABS_NEW_THRESHOLD = 1e-6
    for n, v in cur.items():
        b = float(base.get(str(n), 0.0))
        if b == 0.0:
            if v > ABS_NEW_THRESHOLD:
                flags.append((_resolve_display_name(subG, n), b, v))
            continue
        if v > factor * b:
            flags.append((_resolve_display_name(subG, n), b, v))
    flags.sort(key=lambda t: (t[2] / max(1e-12, t[1])), reverse=True)
    return flags[:top_k]


RESET = "\033[0m"
BOLD = "\033[1m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
CYAN = "\033[36m"

def _det_prefix(found: bool) -> str:
    color = RED if found else GREEN
    return f"{color}{BOLD}DETECTION{RESET}"


def run_live_security_analyses(
    G: nx.Graph,
    *,
    previous_state: Optional[dict] = None,
    print_results: bool = True,
    top_k: int = 10,
) -> dict:
    results: Dict[str, Any] = {}
    prev_state = previous_state or {}

    bet_sub = _build_subgraph_by_labels_and_edge_types(
        G,
        node_labels=["Pod", "ServiceAccount", "Namespace", "RoleBinding", "ClusterRoleBinding", "KubeNode"],
        edge_types=["AUTHENTICATED_AS", "GRANTED", "RUNS_ON", "IN_NAMESPACE"],
    )
    bet = betweenness_centrality(bet_sub)
    results["betweenness_pivoting"] = {
        "nodes": bet_sub.number_of_nodes(),
        "edges": bet_sub.number_of_edges(),
        "values": bet,
        "top": _sort_top(bet, top_k),
    }
    if print_results:
        print("[betweenness] pivoting subgraph:")
        print(f"  nodes={bet_sub.number_of_nodes()} edges={bet_sub.number_of_edges()}")
        for n, v in results["betweenness_pivoting"]["top"]:
            print(f"  {_resolve_display_name(bet_sub, n)} -> {v}")

    comm_sub = _build_subgraph_by_labels_and_edge_types(
        G,
        node_labels=["Pod", "Service", "Namespace", "NetworkPolicy"],
        edge_types=["IN_NAMESPACE", "SELECTS", "ALLOWS"],
    )
    undirected = nx.Graph(comm_sub) if comm_sub.is_directed() else comm_sub.copy()
    communities = community_detection(undirected, method="greedy")
    membership: Dict[Any, int] = {}
    for idx, comm in enumerate(communities):
        for n in comm:
            membership[n] = idx
    results["communities"] = {
        "nodes": comm_sub.number_of_nodes(),
        "edges": comm_sub.number_of_edges(),
        "count": len(communities),
        "membership": membership,
    }
    membership_str: Dict[str, int] = {str(n): cid for n, cid in membership.items()}
    if print_results:
        print("[communities] modularity groups:")
        print(f"  nodes={comm_sub.number_of_nodes()} edges={comm_sub.number_of_edges()} groups={len(communities)}")

    prev_membership: Dict[str, int] = prev_state.get("community_membership", {})
    community_jumps = []
    for n, cid in membership.items():
        key = str(n)
        if key in prev_membership:
            if prev_membership[key] != cid:
                community_jumps.append((_resolve_display_name(comm_sub, n), prev_membership[key], cid))
        else:
            community_jumps.append((_resolve_display_name(comm_sub, n), None, cid))
    results["community_jumps"] = community_jumps
    if print_results and community_jumps:
        print("  community changes detected (node, from, to):")
        for name, c0, c1 in community_jumps[:top_k]:
            print(f"    {name}: {c0} -> {c1}")

    nmi = compute_nmi(prev_membership, membership_str) if prev_membership else None
    results["community_nmi"] = nmi
    if print_results and nmi is not None:
        print(f"  NMI(previous,current)={nmi:.3f}")


    close_sub = _build_subgraph_by_labels_and_edge_types(
        G,
        node_labels=["Pod", "ServiceAccount", "KubeNode"],
        edge_types=["AUTHENTICATED_AS", "RUNS_ON", "GRANTED", "IN_NAMESPACE"],
    )
    close_graph = nx.Graph(close_sub) if close_sub.is_directed() else close_sub
    clo = closeness_centrality(close_graph)
    results["closeness_influence"] = {
        "nodes": close_graph.number_of_nodes(),
        "edges": close_graph.number_of_edges(),
        "values": clo,
        "top": _sort_top(clo, top_k),
    }
    if print_results:
        print("[closeness] influence subgraph:")
        print(f"  nodes={close_graph.number_of_nodes()} edges={close_graph.number_of_edges()}")
        for n, v in results["closeness_influence"]["top"]:
            print(f"  {_resolve_display_name(close_graph, n)} -> {v}")

    pr_sub = _build_subgraph_by_labels_and_edge_types(
        G,
        node_labels=["Pod", "ServiceAccount", "RoleBinding", "ClusterRoleBinding", "Namespace"],
        edge_types=["GRANTED", "IN_NAMESPACE", "AUTHENTICATED_AS"],
    )
    pr_graph = nx.DiGraph(pr_sub)
    CLUSTER_RB_WEIGHT = 5.0
    DEFAULT_EDGE_WEIGHT = 1.0
    for u, v, d in list(pr_graph.edges(data=True)):
        try:
            neo4j_type = d.get("neo4j_type")
            u_labels = pr_graph.nodes[u].get("neo4j_labels", []) or []
            if neo4j_type == "GRANTED" and "ClusterRoleBinding" in u_labels:
                pr_graph.edges[u, v]["weight"] = CLUSTER_RB_WEIGHT
            else:
                pr_graph.edges[u, v]["weight"] = DEFAULT_EDGE_WEIGHT
        except Exception:
            try:
                pr_graph.edges[u, v]["weight"] = DEFAULT_EDGE_WEIGHT
            except Exception:
                pass
    try:
        pr_values = nx.pagerank(pr_graph, weight="weight")
    except Exception:
        pr_values = eigenvector_centrality(nx.Graph(pr_graph))
    results["pagerank_rbac"] = {
        "nodes": pr_graph.number_of_nodes(),
        "edges": pr_graph.number_of_edges(),
        "values": pr_values,
        "top": _sort_top(pr_values, top_k),
    }
    if print_results:
        print("[pagerank] RBAC influence subgraph:")
        print(f"  nodes={pr_graph.number_of_nodes()} edges={pr_graph.number_of_edges()}")
        for n, v in results["pagerank_rbac"]["top"]:
            print(f"  {_resolve_display_name(pr_graph, n)} -> {v}")

    base_bc: Dict[str, float] = prev_state.get("betweenness", {})
    base_cc: Dict[str, float] = prev_state.get("closeness", {})
    base_pr: Dict[str, float] = prev_state.get("pagerank", {})
    bc_flags = flag_increases(bet, base_bc, 2.0, bet_sub, top_k)
    cc_flags = flag_increases(clo, base_cc, 1.5, close_graph, top_k)
    pr_flags = flag_increases(pr_values, base_pr, 2.0, pr_graph, top_k)
    results["anomalies"] = {
        "betweenness_x2": bc_flags,
        "closeness_x1_5": cc_flags,
        "pagerank_x2": pr_flags,
        "community_nmi_below_threshold": (nmi is not None and nmi < 0.8),
    }
    if print_results:
        print("\n=== Detection Summary ===")
        found_bet = len(bc_flags) > 0
        print(f"- {_det_prefix(found_bet)} betweenness pivoting: {'issues found' if found_bet else 'none'}")
        if found_bet:
            for name, b, v in bc_flags:
                print(f"    {name}: {b:.6f} -> {v:.6f}")
        found_comm = (len(community_jumps) > 0) or (nmi is not None and nmi < 0.8)
        print(f"- {_det_prefix(found_comm)} community changes: {'issues found' if found_comm else 'none'}")
        if len(community_jumps) > 0:
            for name, c0, c1 in community_jumps[:top_k]:
                print(f"    {name}: {c0} -> {c1}")
        if nmi is not None:
            print(f"    NMI={nmi:.3f} (threshold 0.8)")
        found_close = len(cc_flags) > 0
        print(f"- {_det_prefix(found_close)} closeness influence: {'issues found' if found_close else 'none'}")
        if found_close:
            for name, b, v in cc_flags:
                print(f"    {name}: {b:.6f} -> {v:.6f}")
        found_pr = len(pr_flags) > 0
        print(f"- {_det_prefix(found_pr)} RBAC PageRank: {'issues found' if found_pr else 'none'}")
        if found_pr:
            for name, b, v in pr_flags:
                print(f"    {name}: {b:.6f} -> {v:.6f}")

    updated_state = {
        "community_membership": membership_str,
        "betweenness": {str(n): float(v) for n, v in bet.items()},
        "closeness": {str(n): float(v) for n, v in clo.items()},
        "pagerank": {str(n): float(v) for n, v in pr_values.items()},
    }
    results["updated_state"] = updated_state
    return results

