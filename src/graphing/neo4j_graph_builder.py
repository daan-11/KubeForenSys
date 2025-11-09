
import json
import logging
import os
from .neo4j_connector import Neo4jConnector

# Optional heavy dependency used only by the conversion function
import networkx as nx

class Neo4jGraphBuilder:
    def list_nodes(self, label):
        """
        Return a set of composite keys for all nodes of a given label.
        """
        composite_key_labels = {
            "ServiceAccount": ("namespace", "name"),
            "Service": ("namespace", "name"),
            "Endpoint": ("namespace", "name"),
            "Namespace": ("name",),
            "NetworkPolicy": ("namespace", "name"),
            "RoleBinding": ("namespace", "binding_name"),
            "ClusterRoleBinding": ("binding_name",),
            "ReplicaSet": ("namespace", "name"),
            "Deployment": ("namespace", "name"),
            "StatefulSet": ("namespace", "name"),
            "Pod": ("namespace", "name"),
            "Role": ("namespace", "name"),
            "ClusterRole": ("name",)
        }
        allowed_labels = {
            "KubeNode": "name",
            "Service": None,
            "Endpoint": None,
            "Deployment": None,
            "ReplicaSet": None,
            "StatefulSet": None,
            "Namespace": None,
            "ServiceAccount": None,
            "NetworkPolicy": None,
            "RoleBinding": None,
            "ClusterRoleBinding": None,
            "Pod": None,
            "Role": None,
            "ClusterRole": None
        }
        key_field = None
        if label in composite_key_labels:
            key_field = 'composite_key'
        elif label in allowed_labels:
            key_field = allowed_labels[label]
        else:
            return set()
        query = f"MATCH (n:{label}) RETURN n.{key_field} as key"
        result = self.connector.run_query(query)
        return set([str(record["key"]) for record in result if record.get("key")])

    def list_edges(self, from_label, rel_type, to_label):
        """
        Return a set of (from_key, to_key) for all edges of a given type.
        """
        query = (
            f"MATCH (a:{from_label})-[r:{rel_type}]->(b:{to_label}) "
            f"RETURN a.composite_key as from_key, b.composite_key as to_key"
        )
        result = self.connector.run_query(query)
        return set([(record["from_key"], record["to_key"]) for record in result if record.get("from_key") and record.get("to_key")])

    def delete_nodes_and_edges_not_in(self, label, current_keys, edge_types=None, key_name="composite_key"):
        """
        Delete all nodes of a given label and their edges not present in current_keys.
        edge_types: list of (from_label, rel_type, to_label) to check for edge deletion.
        """
        existing_keys = self.list_nodes(label)
        to_delete = existing_keys - set(current_keys)
        for key in to_delete:
            self.logger.info(f"Deleting obsolete {label} node: {key}")
            self.delete_node(label, key, key_name=key_name)
        # Delete edges for these nodes
        if edge_types:
            for from_label, rel_type, to_label in edge_types:
                existing_edges = self.list_edges(from_label, rel_type, to_label)
                for from_key, to_key in existing_edges:
                    if (from_label == label and from_key in to_delete) or (to_label == label and to_key in to_delete):
                        self.logger.info(f"Deleting obsolete edge: ({from_label}:{from_key})-[:{rel_type}]->({to_label}:{to_key})")
                        self.delete_edge(from_label, from_key, rel_type, to_label, to_key)

    def delete_edge(self, from_label, from_key, rel_type, to_label, to_key, from_key_name="composite_key", to_key_name="composite_key"):
        query = (
            f"MATCH (a:{from_label} {{{from_key_name}: $from_key}})-[r:{rel_type}]->(b:{to_label} {{{to_key_name}: $to_key}}) "
            f"DELETE r"
        )
        self.connector.run_query(query, {"from_key": from_key, "to_key": to_key})

    def __init__(self, credentials_path="/home/derksen/Documents/KubeForenSys/neo4j-credentials.json"):
        # Use Neo4jConnector wrapper for all DB interactions
        self.connector = Neo4jConnector(credentials_path=credentials_path)
        self.logger = logging.getLogger("Neo4jGraphBuilder")

    def close(self):
        try:
            self.connector.close()
        except Exception:
            pass

    def upsert_node(self, label, properties):
        """
        Only create/update nodes for allowed types with correct key fields.
        """
        # Composite key logic for resources with namespace
        composite_key_labels = {
            "ServiceAccount": ("namespace", "name"),
            "Service": ("namespace", "name"),
            "Endpoint": ("namespace", "name"),
            "Namespace": ("name",),
            "NetworkPolicy": ("namespace", "name"),
            "RoleBinding": ("namespace", "binding_name"),
            "ClusterRoleBinding": ("binding_name",),
            "ReplicaSet": ("namespace", "name"),
            "Deployment": ("namespace", "name"),
            "StatefulSet": ("namespace", "name"),
            "Pod": ("namespace", "name"),
            "Role": ("namespace", "name"),
            "ClusterRole": ("name",)
        }
        allowed_labels = {
            "KubeNode": "uid",
            "Service": None,
            "Endpoint": None,
            "Deployment": None,
            "ReplicaSet": None,
            "StatefulSet": None,
            "Namespace": None,
            "ServiceAccount": None,
            "NetworkPolicy": None,
            "RoleBinding": None,
            "ClusterRoleBinding": None,
            "Pod": None,
            "Role": None,
            "ClusterRole": None
        }
        if label not in allowed_labels:
            return  # Ignore all other types
        # Determine key
        if label in composite_key_labels:
            key_fields = composite_key_labels[label]
            try:
                key = ':'.join([str(properties[k]) for k in key_fields if properties.get(k) is not None])
                key_field = 'composite_key'
            except Exception:
                self.logger.warning(f"No composite key found for node {label}: {properties}")
                return
        else:
            key_field = allowed_labels[label]
            key = properties.get(key_field)
        if not key_field or not key:
            self.logger.warning(f"No key found for node {label}: {properties}")
            return
        # Serialize dict/list property values
        safe_props = {}
        for k, v in properties.items():
            if isinstance(v, (dict, list)):
                safe_props[k] = json.dumps(v)
            else:
                safe_props[k] = v
        safe_props[key_field] = key  # Ensure key is present
        prop_keys = ", ".join([f"n.{k} = ${k}" for k in safe_props.keys()])
        query = (
            f"MERGE (n:{label} {{{key_field}: ${key_field}}}) "
            f"SET {prop_keys} "
        )
        # Run query via connector
        self.connector.run_query(query, safe_props)

    def delete_node(self, label, key, key_name="composite_key"):
        query = f"MATCH (n:{label} {{{key_name}: $key}}) DETACH DELETE n"
        self.connector.run_query(query, {"key": key})

    def upsert_edge(self, from_label, from_key, to_label, to_key, rel_type, properties=None, from_key_name="composite_key", to_key_name="composite_key"):
        if properties is None:
            properties = {}
        prop_keys = ", ".join([f"r.{k} = ${k}" for k in properties.keys()])
        set_clause = f"SET {prop_keys}" if prop_keys else ""
        query = (
            f"MATCH (a:{from_label} {{{from_key_name}: $from_key}}) "
            f"MATCH (b:{to_label} {{{to_key_name}: $to_key}}) "
            f"MERGE (a)-[r:{rel_type}]->(b) "
            f"{set_clause}"
        )
        params = {"from_key": from_key, "to_key": to_key, **properties}
        self.connector.run_query(query, params)

    # Helper for composite keys
    def get_composite_key(self, label, properties):
        composite_key_labels = {
            "ServiceAccount": ("namespace", "name"),
            "Service": ("namespace", "name"),
            "Endpoint": ("namespace", "name"),
            "Namespace": ("name",),
            "NetworkPolicy": ("namespace", "name"),
            "RoleBinding": ("namespace", "binding_name"),
            "ClusterRoleBinding": ("binding_name",),
            "ReplicaSet": ("namespace", "name"),
            "Deployment": ("namespace", "name"),
            "StatefulSet": ("namespace", "name"),
            "Pod": ("namespace", "name"),
            "Role": ("namespace", "name"),
            "ClusterRole": ("name",)
        }
        if label in composite_key_labels:
            try:
                # Join only existing keys to avoid None
                return ':'.join([str(properties[k]) for k in composite_key_labels[label] if properties.get(k) is not None])
            except Exception:
                return None
        return properties.get("uid")

    def to_networkx_full_graph(self, directed: bool = True):
        """Convert the entire Neo4j database to a NetworkX Multi(Di)Graph.

        - Uses internal Neo4j node ids as NetworkX node keys.
        - Copies node labels into the node attribute 'neo4j_labels'.
        - Copies relationship type into edge attribute 'neo4j_type' and the
          relationship id into 'neo4j_rid'.
        - Returns a tuple (G, report) where report contains counts and any
          discrepancy details.
        """
        logger = self.logger or logging.getLogger("Neo4jGraphBuilder")
        G = nx.MultiDiGraph() if directed else nx.MultiGraph()

        # Fetch nodes using elementId() to avoid deprecated id() usage (returns stable string id)
        node_query = "MATCH (n) RETURN elementId(n) as nid, labels(n) as labels, properties(n) as props"
        node_rows = self.connector.run_query(node_query)
        neo4j_node_ids = set()
        for rec in node_rows:
            nid = rec.get("nid")
            if nid is None:
                continue
            neo4j_node_ids.add(nid)
            labels = rec.get("labels") or []
            props = rec.get("props") or {}
            # serialize dict/list props to JSON strings to keep NetworkX happy
            safe_props = {}
            for k, v in props.items():
                if isinstance(v, (dict, list)):
                    try:
                        safe_props[k] = json.dumps(v)
                    except Exception:
                        safe_props[k] = str(v)
                else:
                    safe_props[k] = v
            safe_props["neo4j_labels"] = labels
            G.add_node(nid, **safe_props)

        # Fetch relationships using elementId() to avoid deprecated id() usage
        rel_query = (
            "MATCH (a)-[r]->(b) RETURN elementId(r) as rid, elementId(a) as source, elementId(b) as target, "
            "type(r) as type, properties(r) as props"
        )
        rel_rows = self.connector.run_query(rel_query)
        neo4j_rel_ids = set()
        for rec in rel_rows:
            rid = rec.get("rid")
            src = rec.get("source")
            dst = rec.get("target")
            if rid is None or src is None or dst is None:
                continue
            neo4j_rel_ids.add(rid)
            rtype = rec.get("type")
            props = rec.get("props") or {}
            safe_props = {}
            for k, v in props.items():
                if isinstance(v, (dict, list)):
                    try:
                        safe_props[k] = json.dumps(v)
                    except Exception:
                        safe_props[k] = str(v)
                else:
                    safe_props[k] = v
            safe_props["neo4j_type"] = rtype
            safe_props["neo4j_rid"] = rid
            # Add edge with Neo4j relationship elementId as the key to preserve multiplicity
            try:
                G.add_edge(src, dst, key=rid, **safe_props)
            except Exception:
                # Fallback: add without key if something goes wrong
                G.add_edge(src, dst, **safe_props)

        # Validation: compare counts
        try:
            total_nodes_db = int(self.connector.scalar("MATCH (n) RETURN count(n)"))
        except Exception:
            total_nodes_db = None
        try:
            total_rels_db = int(self.connector.scalar("MATCH ()-[r]->() RETURN count(r)"))
        except Exception:
            total_rels_db = None

        nx_nodes = G.number_of_nodes()
        nx_rels = G.number_of_edges()

        report = {
            "neo4j_node_count": total_nodes_db,
            "neo4j_rel_count": total_rels_db,
            "networkx_node_count": nx_nodes,
            "networkx_rel_count": nx_rels,
            "node_id_set_db": neo4j_node_ids,
            "rel_id_set_db": neo4j_rel_ids,
            "node_id_set_nx": set(G.nodes()),
            "rel_id_set_nx": set((u, v, k) for u, v, k in G.edges(keys=True)),
            "node_discrepancies": [],
            "rel_discrepancies": []
        }

        # Determine discrepancies (only if we successfully fetched DB counts)
        if total_nodes_db is not None and total_nodes_db != nx_nodes:
            missing_in_nx = report["node_id_set_db"] - report["node_id_set_nx"]
            extra_in_nx = report["node_id_set_nx"] - report["node_id_set_db"]
            report["node_discrepancies"] = {
                "missing_in_networkx": missing_in_nx,
                "extra_in_networkx": extra_in_nx
            }
            logger.warning(
                f"Node count mismatch: neo4j={total_nodes_db} vs networkx={nx_nodes}. "
                f"Missing in NX: {len(missing_in_nx)}; Extra in NX: {len(extra_in_nx)}"
            )

        if total_rels_db is not None and total_rels_db != nx_rels:
            # Build set of relationship identifiers from DB rows: (src, dst, rid)
            db_rel_set = set()
            for rec in rel_rows:
                rid = rec.get("rid")
                src = rec.get("source")
                dst = rec.get("target")
                if rid is None or src is None or dst is None:
                    continue
                db_rel_set.add((src, dst, rid))

            nx_rel_set = report["rel_id_set_nx"]
            missing_rels = db_rel_set - nx_rel_set
            extra_rels = nx_rel_set - db_rel_set
            report["rel_discrepancies"] = {
                "missing_in_networkx": missing_rels,
                "extra_in_networkx": extra_rels
            }
            logger.warning(
                f"Relationship count mismatch: neo4j={total_rels_db} vs networkx={nx_rels}. "
                f"Missing in NX: {len(missing_rels)}; Extra in NX: {len(extra_rels)}"
            )

        # Print concise summary to stdout as well for immediate visibility
        print(
            f"[neo4j->networkx] nodes: neo4j={total_nodes_db} networkx={nx_nodes}; "
            f"rels: neo4j={total_rels_db} networkx={nx_rels}"
        )

        return G, report
