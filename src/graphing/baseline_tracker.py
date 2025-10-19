import time
import threading
import logging
from typing import Dict, Any
import pickle
from datetime import datetime, timedelta
try:
    import pandas as pd
except Exception:  # pragma: no cover - fallback for environments without pandas
    pd = None

from .neo4j_connector import Neo4jConnector


class BaselineTracker:
    """Collects baseline metrics from Neo4j and stores a rolling DataFrame.

    Metrics collected:
    - pod_degree: degree (in+out) per pod aggregated (mean, max)
    - cross_namespace_edges: count of edges crossing namespaces
    - sa_usage: count of authentication edges to serviceaccounts
    - new_edges_rate: number of new edges created since last snapshot
    """

    def __init__(self, connector: Neo4jConnector = None, persist_path: str = "./baseline.pkl", window_days: int = 7):
        self.logger = logging.getLogger("BaselineTracker")
        self.connector = connector or Neo4jConnector()
        self.persist_path = persist_path
        self.window_days = window_days
        # DataFrame indexed by timestamp with metric columns (or fallback list)
        if pd is not None:
            self.df = pd.DataFrame()
        else:
            # fallback storage: list of (timestamp, metrics dict)
            self.df = []
        self._last_edge_count = None
        # Try load persisted
        try:
            self._load()
        except Exception:
            self.logger.debug("No existing baseline file loaded")

    def _load(self):
        with open(self.persist_path, "rb") as f:
            self.df = pickle.load(f)

    def _save(self):
        try:
            with open(self.persist_path, "wb") as f:
                pickle.dump(self.df, f)
        except Exception as e:
            self.logger.exception(f"Failed to persist baseline to {self.persist_path}: {e}")

    def collect_metrics(self) -> Dict[str, Any]:
        """Collect a snapshot of metrics from Neo4j."""
        metrics = {}
        ts = datetime.utcnow()
        # Pod degree: average degree for Pod nodes
        try:
            q = "MATCH (p:Pod) OPTIONAL MATCH (p)-[r]-() RETURN avg(size((p)--())) as avg_deg, max(size((p)--())) as max_deg"
            # Neo4j doesn't support size((p)--()) in aggregate easily; use simpler counts via query per pod
            q = "MATCH (p:Pod) OPTIONAL MATCH (p)-[r]-() WITH p, count(r) as deg RETURN avg(deg) as avg_deg, max(deg) as max_deg"
            res = self.connector.run_query(q, fetch_one=True)
            if res:
                metrics["pod_degree_avg"] = float(res.get("avg_deg") or 0)
                metrics["pod_degree_max"] = int(res.get("max_deg") or 0)
        except Exception:
            self.logger.exception("Failed to collect pod degree")
            metrics["pod_degree_avg"] = 0
            metrics["pod_degree_max"] = 0

        # Cross-namespace edges
        try:
            q = ("MATCH (a)-[r]->(b) WHERE exists(a.namespace) AND exists(b.namespace) AND a.namespace <> b.namespace "
                 "RETURN count(r) as cross_ns")
            res = self.connector.run_query(q, fetch_one=True)
            metrics["cross_namespace_edges"] = int(res.get("cross_ns") or 0)
        except Exception:
            self.logger.exception("Failed to collect cross-namespace edges")
            metrics["cross_namespace_edges"] = 0

        # ServiceAccount usage
        try:
            q = "MATCH (:Pod)-[r:AUTHENTICATED_AS]->(sa:ServiceAccount) RETURN count(r) as sa_usage"
            res = self.connector.run_query(q, fetch_one=True)
            metrics["sa_usage"] = int(res.get("sa_usage") or 0)
        except Exception:
            self.logger.exception("Failed to collect SA usage")
            metrics["sa_usage"] = 0

        # Edge count and new_edges_rate
        try:
            q = "MATCH ()-[r]->() RETURN count(r) as edges"
            res = self.connector.run_query(q, fetch_one=True)
            total_edges = int(res.get("edges") or 0)
            if self._last_edge_count is None:
                new_rate = 0
            else:
                new_rate = max(0, total_edges - self._last_edge_count)
            self._last_edge_count = total_edges
            metrics["total_edges"] = total_edges
            metrics["new_edges_rate"] = new_rate
        except Exception:
            self.logger.exception("Failed to collect edge counts")
            metrics["total_edges"] = 0
            metrics["new_edges_rate"] = 0

        # Store snapshot
        if pd is not None:
            self.df = pd.concat([self.df, pd.DataFrame([metrics], index=[ts])]) if not self.df.empty else pd.DataFrame([metrics], index=[ts])
            # Trim to window
            cutoff = datetime.utcnow() - pd.Timedelta(days=self.window_days)
            self.df = self.df[self.df.index >= cutoff]
        else:
            # fallback append and prune by timestamp
            self.df.append((ts, metrics))
            cutoff = datetime.utcnow() - timedelta(days=self.window_days) if hasattr(datetime, 'timedelta') else None
            # simple prune by keeping last N items (approximate)
            if len(self.df) > 24 * 60 * self.window_days:
                self.df = self.df[-(24 * 60 * self.window_days):]
        # Persist
        self._save()
        return metrics

    def detect_anomalies(self, latest_metrics: Dict[str, Any], z_threshold: float = 3.0):
        """Detect statistical anomalies comparing latest_metrics to baseline (self.df).

        Returns list of alert dicts.
        """
        alerts = []
        if pd is not None:
            if self.df.empty:
                return alerts
            means = self.df.mean()
            stds = self.df.std().replace({0: 1e-9})
        else:
            # fallback: compute mean/std from list
            import statistics
            if not self.df:
                return alerts
            # build per-metric lists
            metric_lists = {}
            for _ts, m in self.df:
                for k, v in m.items():
                    metric_lists.setdefault(k, []).append(float(v or 0))
            means = {k: statistics.mean(v) for k, v in metric_lists.items()}
            stds = {k: (statistics.pstdev(v) if len(v) > 1 else 1e-9) for k, v in metric_lists.items()}
        for metric, value in latest_metrics.items():
            if pd is not None:
                if metric not in means.index:
                    continue
                z = (value - means[metric]) / stds[metric]
            else:
                if metric not in means:
                    continue
                z = (value - means[metric]) / stds[metric]
            if abs(z) > z_threshold:
                alerts.append({
                    "metric": metric,
                    "value": value,
                    "z_score": float(z),
                    "mean": float(means[metric]),
                    "std": float(stds[metric])
                })
        return alerts


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    bt = BaselineTracker()
    print(bt.collect_metrics())