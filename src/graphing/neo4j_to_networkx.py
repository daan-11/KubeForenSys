import logging
from typing import Any

try:
    import networkx as nx
except Exception:
    nx = None


def records_to_networkx(records: Any):
    """Convert neo4j records containing 'nodes' and 'relationships' into a NetworkX DiGraph.

    If networkx is not installed, returns a minimal fallback object with a compatible subset of methods.
    """
    if nx is None:
        class _G:
            def __init__(self):
                self._nodes = set()
            def add_node(self, n, **kwargs):
                self._nodes.add(n)
            def add_edge(self, a, b, **kwargs):
                pass
            def number_of_nodes(self):
                return len(self._nodes)
        G = _G()
    else:
        G = nx.DiGraph()

    if not records:
        return G
    if isinstance(records, dict):
        records = [records]
    for rec in records:
        nodes = rec.get("nodes") or []
        rels = rec.get("relationships") or []
        for n in nodes:
            nid = n.get("id") or n.get("identity") or str((n.get("properties") or {}).get("composite_key") or (n.get("properties") or {}).get("name") or '')
            try:
                G.add_node(nid, labels=n.get("labels"), **(n.get("properties") or {}))
            except Exception:
                try:
                    G.add_node(nid)
                except Exception:
                    pass
        for r in rels:
            start = r.get("start")
            end = r.get("end")
            rtype = r.get("type")
            props = r.get("properties") or {}
            try:
                if start and end:
                    G.add_edge(start, end, type=rtype, **props)
            except Exception:
                pass
    return G
