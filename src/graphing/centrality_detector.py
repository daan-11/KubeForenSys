import logging
from typing import Dict, Any
try:
    import pandas as pd
except Exception:
    pd = None
try:
    import networkx as nx
except Exception:
    nx = None

from .neo4j_connector import Neo4jConnector
from .neo4j_to_networkx import records_to_networkx


class CentralityDetector:
    def __init__(self, connector: Neo4jConnector = None):
        self.logger = logging.getLogger("CentralityDetector")
        self.connector = connector or Neo4jConnector()
        if pd is not None:
            self.series = pd.Series(dtype=float)
        else:
            self.series = []

    def build_subgraph(self, limit_nodes: int = 1000):
        q = (
            "MATCH (p:Pod) OPTIONAL MATCH (p)-[r]-(n) "
            "RETURN collect(distinct p) as nodes, collect(distinct r) as relationships LIMIT $limit"
        )
        recs = self.connector.run_query(q, {"limit": limit_nodes})
        G = records_to_networkx(recs[0] if recs else {})
        return G

    def compute_betweenness(self, G):
        if nx is None:
            return {}
        if hasattr(G, 'number_of_nodes') and G.number_of_nodes() == 0:
            return {}
        try:
            centrality = nx.betweenness_centrality(G)
            return centrality
        except Exception:
            self.logger.exception("Failed to compute centrality")
            return {}

    def snapshot_and_detect(self, top_n: int = 5, spike_threshold: float = 2.0):
        G = self.build_subgraph()
        cent = self.compute_betweenness(G)
        max_cent = max(cent.values()) if cent else 0.0
        if pd is not None:
            ts = pd.Timestamp.utcnow()
            self.series = self.series.append(pd.Series([max_cent], index=[ts]))
            cutoff = pd.Timestamp.utcnow() - pd.Timedelta(days=1)
            self.series = self.series[self.series.index >= cutoff]
            mean = float(self.series.mean() or 0.0)
            std = float(self.series.std() or 0.0)
        else:
            self.series.append(max_cent)
            vals = self.series[-2880:]
            mean = float(sum(vals) / len(vals)) if vals else 0.0
            import math
            std = float((math.sqrt(sum((x - mean) ** 2 for x in vals) / len(vals))) if vals else 0.0)
        alerts = []
        if std > 0 and (max_cent - mean) > spike_threshold * std:
            alerts.append({"metric": "betweenness_max", "value": max_cent, "mean": mean, "std": std, "z": (max_cent - mean) / std})
        return alerts, cent
