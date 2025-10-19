import json
import logging
import os
from .neo4j_connector import Neo4jConnector


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
