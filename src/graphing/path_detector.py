import logging
from typing import List, Dict, Any

from .neo4j_connector import Neo4jConnector


class PathDetector:
	def __init__(self, connector: Neo4jConnector = None, max_length: int = 4):
		self.logger = logging.getLogger("PathDetector")
		self.connector = connector or Neo4jConnector()
		self.max_length = max_length

	def find_cross_namespace_paths(self, max_paths: int = 100) -> List[Dict[str, Any]]:
		q = (
			f"MATCH path = (source:Pod)-[*1..{self.max_length}]-(target:Pod) "
			"WHERE exists(source.namespace) AND exists(target.namespace) AND source.namespace <> target.namespace AND source <> target "
			"RETURN path, source.namespace as src_ns, target.namespace as tgt_ns LIMIT $limit"
		)
		rows = self.connector.run_query(q, {"limit": max_paths})
		results = []
		for r in rows:
			results.append({
				"path": r.get("path"),
				"src_ns": r.get("src_ns"),
				"tgt_ns": r.get("tgt_ns")
			})
		return results

	def score_path(self, path_record: Dict[str, Any]) -> Dict[str, Any]:
		"""Simple scoring: +2 for namespace crossing, +3 for presence of RoleBinding/ClusterRoleBinding nodes (priv escalation)"""
		score = 0
		evidence = []
		# namespace crossing
		if path_record.get("src_ns") and path_record.get("tgt_ns") and path_record["src_ns"] != path_record["tgt_ns"]:
			score += 2
			evidence.append("cross_namespace")
		# inspect nodes in path for RBAC bindings
		path = path_record.get("path")
		try:
			# path is a Neo4j path object represented as dict by connector; fallback to string
			nodes = path.nodes if hasattr(path, "nodes") else []
			for n in nodes:
				labels = n.get("labels") if isinstance(n, dict) else getattr(n, "labels", [])
				if labels and ("RoleBinding" in labels or "ClusterRoleBinding" in labels):
					score += 3
					evidence.append("privilege_escalation")
					break
		except Exception:
			# best-effort
			pass
		return {"score": score, "evidence": evidence, "src_ns": path_record.get("src_ns"), "tgt_ns": path_record.get("tgt_ns"), "path": path_record.get("path")}

import logging
from typing import List, Dict, Any

from .neo4j_connector import Neo4jConnector


class PathDetector:
	def __init__(self, connector: Neo4jConnector = None, max_length: int = 4):
		self.logger = logging.getLogger("PathDetector")
		self.connector = connector or Neo4jConnector()
		self.max_length = max_length

	def find_cross_namespace_paths(self, max_paths: int = 100) -> List[Dict[str, Any]]:
		q = (
			f"MATCH path = (source:Pod)-[*1..{self.max_length}]-(target:Pod) "
			"WHERE exists(source.namespace) AND exists(target.namespace) AND source.namespace <> target.namespace AND source <> target "
			"RETURN path, source.namespace as src_ns, target.namespace as tgt_ns LIMIT $limit"
		)
		rows = self.connector.run_query(q, {"limit": max_paths})
		results = []
		for r in rows:
			results.append({
				"path": r.get("path"),
				"src_ns": r.get("src_ns"),
				"tgt_ns": r.get("tgt_ns")
			})
		return results

	def score_path(self, path_record: Dict[str, Any]) -> Dict[str, Any]:
		"""Simple scoring: +2 for namespace crossing, +3 for presence of RoleBinding/ClusterRoleBinding nodes (priv escalation)"""
		score = 0
		evidence = []
		# namespace crossing
		if path_record.get("src_ns") and path_record.get("tgt_ns") and path_record["src_ns"] != path_record["tgt_ns"]:
			score += 2
			evidence.append("cross_namespace")
		# inspect nodes in path for RBAC bindings
		path = path_record.get("path")
		try:
			# path is a Neo4j path object represented as dict by connector; fallback to string
			nodes = path.nodes if hasattr(path, "nodes") else []
			for n in nodes:
				labels = n.get("labels") if isinstance(n, dict) else getattr(n, "labels", [])
				if labels and ("RoleBinding" in labels or "ClusterRoleBinding" in labels):
					score += 3
					evidence.append("privilege_escalation")
					break
		except Exception:
			# best-effort
			pass
		return {"score": score, "evidence": evidence, "src_ns": path_record.get("src_ns"), "tgt_ns": path_record.get("tgt_ns"), "path": path_record.get("path")}

