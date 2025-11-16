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
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple
import math

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
    except Exception as e1:
        try:
            return nx.eigenvector_centrality_numpy(G, weight=weight)
        except Exception as e2:
            # Don't crash the entire analysis when optional numeric backends
            # (scipy/numpy) are missing or power iteration doesn't converge.
            # Fall back to a weaker but safe centrality measure (degree centrality)
            # and log the reason so operators can install the missing deps.
            try:
                import logging

                logging.getLogger(__name__).warning(
                    "Eigenvector centrality fallback: power-iteration failed (%s) and numpy/scipy solver failed (%s); using degree centrality as fallback",
                    e1,
                    e2,
                )
            except Exception:
                pass
            # Return degree centrality as a conservative fallback mapping
            try:
                return nx.degree_centrality(G)
            except Exception:
                # As a last resort return zeros for all nodes
                return {n: 0.0 for n in G.nodes()}


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


def _resolve_display_name(G: nx.Graph, n: Any) -> str:
    """Best-effort human-readable identifier for a node id in G."""
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


# Simple ANSI color helpers for terminal output
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
    """Run the focused, security-relevant analyses on the Kubernetes graph.

    Algorithms implemented (on targeted subgraphs):
      1) Betweenness centrality for pivoting (Pod/SA/Namespace/RBAC/KubeNode over AUTHENTICATED_AS, GRANTED, RUNS_ON)
      2) Community detection (Pods/Services/Namespaces/NetworkPolicies over IN_NAMESPACE, SELECTS, ALLOWS)
      3) Temporal edge anomalies (new relationship ids since last run; burst by neo4j_type)
      4) Closeness centrality (Pod/SA/KubeNode over AUTHENTICATED_AS, RUNS_ON, GRANTED)
      5) PageRank (RBAC influence: SA/RoleBinding/ClusterRoleBinding/Namespace over GRANTED, IN_NAMESPACE)

    Returns a dict with results and an `updated_state` for persistence between runs.
    """
    results: Dict[str, Any] = {}
    prev_state = previous_state or {}

    # 1) Betweenness centrality (pivoting)
    bet_sub = _build_subgraph_by_labels_and_edge_types(
        G,
        node_labels=["Pod", "ServiceAccount", "Namespace", "RoleBinding", "ClusterRoleBinding", "KubeNode"],
        # include IN_NAMESPACE so Pod<->Namespace connectivity is represented in betweenness
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

    # 2) Community detection (modularity-based)
    comm_sub = _build_subgraph_by_labels_and_edge_types(
        G,
        node_labels=["Pod", "Service", "Namespace", "NetworkPolicy"],
        edge_types=["IN_NAMESPACE", "SELECTS", "ALLOWS"],
    )
    # Convert to simple Graph for modularity algorithms if needed
    undirected = nx.Graph(comm_sub) if comm_sub.is_directed() else comm_sub.copy()
    communities = community_detection(undirected, method="greedy")
    # Build membership map for delta detection
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
    # Build string-keyed membership for persistence and NMI
    membership_str: Dict[str, int] = {str(n): cid for n, cid in membership.items()}
    if print_results:
        print("[communities] modularity groups:")
        print(f"  nodes={comm_sub.number_of_nodes()} edges={comm_sub.number_of_edges()} groups={len(communities)}")

    # Detect community changes vs previous state
    prev_membership: Dict[str, int] = prev_state.get("community_membership", {})
    community_jumps = []
    for n, cid in membership.items():
        key = str(n)
        if key in prev_membership:
            if prev_membership[key] != cid:
                community_jumps.append((_resolve_display_name(comm_sub, n), prev_membership[key], cid))
        else:
            # newly-seen node: report as None -> cid so analysts can see nodes that
            # appeared and which community they joined
            community_jumps.append((_resolve_display_name(comm_sub, n), None, cid))
    results["community_jumps"] = community_jumps
    if print_results and community_jumps:
        print("  community changes detected (node, from, to):")
        for name, c0, c1 in community_jumps[:top_k]:
            print(f"    {name}: {c0} -> {c1}")

    # Compute NMI between previous and current community assignments (if possible)
    def _compute_nmi(prev_map: Dict[str, int], cur_map: Dict[str, int]) -> float:
        inter_keys = [k for k in cur_map.keys() if k in prev_map]
        n = len(inter_keys)
        if n == 0:
            return 0.0
        # Map cluster ids to compact indices
        prev_ids = {prev_map[k] for k in inter_keys}
        curr_ids = {cur_map[k] for k in inter_keys}
        prev_index = {cid: i for i, cid in enumerate(sorted(prev_ids))}
        curr_index = {cid: j for j, cid in enumerate(sorted(curr_ids))}
        r = len(prev_index)
        c = len(curr_index)
        # Contingency table
        N = [[0 for _ in range(c)] for __ in range(r)]
        for k in inter_keys:
            i = prev_index[prev_map[k]]
            j = curr_index[cur_map[k]]
            N[i][j] += 1
        # Row/col sums
        row = [sum(N[i][j] for j in range(c)) for i in range(r)]
        col = [sum(N[i][j] for i in range(r)) for j in range(c)]
        # Mutual information
        MI = 0.0
        for i in range(r):
            for j in range(c):
                if N[i][j] == 0:
                    continue
                MI += (N[i][j] / n) * math.log((n * N[i][j]) / (row[i] * col[j]))
        # Entropies
        def H(vals: List[int]) -> float:
            h = 0.0
            for v in vals:
                if v == 0:
                    continue
                p = v / n
                h -= p * math.log(p)
            return h
        H_prev = H(row)
        H_curr = H(col)
        denom = math.sqrt(H_prev * H_curr)
        if denom == 0:
            # If both entropies zero and assignments match perfectly, define NMI=1 else 0
            return 1.0 if all(prev_map[k] == cur_map[k] for k in inter_keys) else 0.0
        return MI / denom

    nmi = _compute_nmi(prev_membership, membership_str) if prev_membership else None
    results["community_nmi"] = nmi
    if print_results and nmi is not None:
        print(f"  NMI(previous,current)={nmi:.3f}")

    # 3) Temporal edge anomalies: new edges since last run
    # We rely on the NetworkX conversion report (edge ids) being persisted by caller.
    # Here, just compute per-type counts for newly seen relationships.
    # Note: Node identifiers (u,v) are elementIds; k is relationship elementId.
    # We'll classify by neo4j_type from the graph.
    prev_rel_ids = set()
    try:
        prev_rel_ids = set(tuple(t) for t in prev_state.get("rel_ids", []))
    except Exception:
        prev_rel_ids = set()
    current_rel_ids = set((u, v, k) for u, v, k in G.edges(keys=True))
    new_rel_ids = current_rel_ids - prev_rel_ids
    new_by_type: Dict[str, int] = {}
    samples: List[tuple] = []
    for u, v, k in list(new_rel_ids)[:1000]:  # limit scan for printing
        data = G.get_edge_data(u, v, key=k) or {}
        etype = data.get("neo4j_type", "UNKNOWN")
        new_by_type[etype] = new_by_type.get(etype, 0) + 1
        if len(samples) < top_k:
            src = _resolve_display_name(G, u)
            dst = _resolve_display_name(G, v)
            samples.append((etype, src, dst))
    results["temporal_new_edges"] = {
        "total_new": len(new_rel_ids),
        "by_type": new_by_type,
        "samples": samples,
    }
    # Sliding-window spike detection: compare current window to previous window
    prev_window = prev_state.get("temporal_last_window", {"total_new": 0, "by_type": {}})
    spike = len(new_rel_ids) > 2 * int(prev_window.get("total_new", 0))
    type_spikes = {t: cnt for t, cnt in new_by_type.items() if cnt > 2 * int(prev_window.get("by_type", {}).get(t, 0))}
    results["temporal_spike"] = {"spike": spike, "type_spikes": type_spikes}
    if print_results:
        print("[temporal] new relationships since last run:")
        print(f"  total_new={len(new_rel_ids)} by_type={new_by_type}")
        for et, s, d in samples:
            print(f"  + {et}: {s} -> {d}")
        if spike or type_spikes:
            print(f"  spike_detected={spike} type_spikes={type_spikes}")

    # 4) Closeness centrality (influence expansion)
    close_sub = _build_subgraph_by_labels_and_edge_types(
        G,
        # include IN_NAMESPACE so closeness reflects namespace placement of pods
        node_labels=["Pod", "ServiceAccount", "KubeNode"],
        edge_types=["AUTHENTICATED_AS", "RUNS_ON", "GRANTED", "IN_NAMESPACE"],
    )
    # Use undirected closeness for connectivity intuition
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

    # 5) PageRank (privilege-based influence)
    # PageRank should reflect RBAC authority (GRANTED) but also visibility of
    # which namespaces/service reach an SA via Pods. Include Pod and AUTHENTICATED_AS
    # so a ServiceAccount that has pods in multiple namespaces will be visible in
    # the RBAC influence graph.
    pr_sub = _build_subgraph_by_labels_and_edge_types(
        G,
        node_labels=["Pod", "ServiceAccount", "RoleBinding", "ClusterRoleBinding", "Namespace"],
        edge_types=["GRANTED", "IN_NAMESPACE", "AUTHENTICATED_AS"],
    )
    # Convert to DiGraph to run PageRank; collapse multiedges
    pr_graph = nx.DiGraph(pr_sub)
    try:
        pr_values = nx.pagerank(pr_graph)
    except Exception:
        # Fall back to eigenvector centrality on undirected if pagerank fails (e.g., disconnected tiny graph)
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

    # Anomaly flags vs baselines (thresholds per request)
    base_bc: Dict[str, float] = prev_state.get("betweenness", {})
    base_cc: Dict[str, float] = prev_state.get("closeness", {})
    base_pr: Dict[str, float] = prev_state.get("pagerank", {})

    def _flag_increases(cur: Dict[Any, float], base: Dict[str, float], factor: float, subG: nx.Graph) -> List[Tuple[str, float, float]]:
        flags = []
        # absolute threshold for newly-seen nodes (no baseline) to avoid noise
        ABS_NEW_THRESHOLD = 1e-6
        for n, v in cur.items():
            b = float(base.get(str(n), 0.0))
            if b == 0.0:
                # if there's no baseline but the current value is meaningfully large,
                # record it so newly-created pivot nodes / SAs are not silently ignored
                if v > ABS_NEW_THRESHOLD:
                    flags.append((_resolve_display_name(subG, n), b, v))
                continue
            if v > factor * b:
                flags.append((_resolve_display_name(subG, n), b, v))
        # sort by ratio descending (handle zero baseline already filtered)
        flags.sort(key=lambda t: (t[2] / max(1e-12, t[1])), reverse=True)
        return flags[:top_k]

    bc_flags = _flag_increases(bet, base_bc, 2.0, bet_sub)
    cc_flags = _flag_increases(clo, base_cc, 1.5, close_graph)
    pr_flags = _flag_increases(pr_values, base_pr, 2.0, pr_graph)
    results["anomalies"] = {
        "betweenness_x2": bc_flags,
        "closeness_x1_5": cc_flags,
        "pagerank_x2": pr_flags,
        "community_nmi_below_threshold": (nmi is not None and nmi < 0.8),
    }
    if print_results:
        # Detection summary for the 5 algorithms (colored 'DETECTION')
        print("\n=== Detection Summary ===")
        # 1) Betweenness
        found_bet = len(bc_flags) > 0
        print(f"- {_det_prefix(found_bet)} betweenness pivoting: {'issues found' if found_bet else 'none'}")
        if found_bet:
            for name, b, v in bc_flags:
                print(f"    {name}: {b:.6f} -> {v:.6f}")
        # 2) Communities (jumps or low NMI)
        found_comm = (len(community_jumps) > 0) or (nmi is not None and nmi < 0.8)
        print(f"- {_det_prefix(found_comm)} community changes: {'issues found' if found_comm else 'none'}")
        if len(community_jumps) > 0:
            for name, c0, c1 in community_jumps[:top_k]:
                print(f"    {name}: {c0} -> {c1}")
        if nmi is not None:
            print(f"    NMI={nmi:.3f} (threshold 0.8)")
        # 3) Temporal spikes
        found_temp = spike or (len(type_spikes) > 0)
        print(f"- {_det_prefix(found_temp)} temporal spikes: {'issues found' if found_temp else 'none'}")
        if found_temp:
            print(f"    total_new={len(new_rel_ids)} spike={spike} type_spikes={type_spikes}")
        # 4) Closeness
        found_close = len(cc_flags) > 0
        print(f"- {_det_prefix(found_close)} closeness influence: {'issues found' if found_close else 'none'}")
        if found_close:
            for name, b, v in cc_flags:
                print(f"    {name}: {b:.6f} -> {v:.6f}")
        # 5) PageRank
        found_pr = len(pr_flags) > 0
        print(f"- {_det_prefix(found_pr)} RBAC PageRank: {'issues found' if found_pr else 'none'}")
        if found_pr:
            for name, b, v in pr_flags:
                print(f"    {name}: {b:.6f} -> {v:.6f}")

    # Build updated state for persistence (for next run deltas)
    updated_state = {
        "rel_ids": [list(t) for t in current_rel_ids],
        "community_membership": membership_str,
        "betweenness": {str(n): float(v) for n, v in bet.items()},
        "closeness": {str(n): float(v) for n, v in clo.items()},
        "pagerank": {str(n): float(v) for n, v in pr_values.items()},
        "temporal_last_window": {"total_new": len(new_rel_ids), "by_type": new_by_type},
    }
    results["updated_state"] = updated_state
    return results

