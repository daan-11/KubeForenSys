import json
from neo4j import GraphDatabase
import logging
import os

class Neo4jGraphBuilder:
    def __init__(self, credentials_path="/home/derksen/Documents/KubeForenSys/neo4j-credentials.json"):
        with open(credentials_path, "r") as f:
            creds = json.load(f)
        uri = f"bolt://{creds['vm_public_ip']}:7687"
        user = creds["neo4j_username"]
        password = creds["neo4j_password"]
        self.driver = GraphDatabase.driver(uri, auth=(user, password))
        self.logger = logging.getLogger("Neo4jGraphBuilder")

    def close(self):
        self.driver.close()

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
            "ReplicaSet": ("namespace", "name"),
            "Deployment": ("namespace", "name"),
            "StatefulSet": ("namespace", "name"),
            "Pod": ("namespace", "name")
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
            "Pod": None
        }
        if label not in allowed_labels:
            return  # Ignore all other types
        # Determine key
        if label in composite_key_labels:
            key_fields = composite_key_labels[label]
            try:
                key = ':'.join([str(properties[k]) for k in key_fields])
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
        with self.driver.session() as session:
            session.run(query, **safe_props)

    def delete_node(self, label, key, key_name="uid"):
        query = f"MATCH (n:{label} {{{key_name}: $key}}) DETACH DELETE n"
        with self.driver.session() as session:
            session.run(query, key=key)

    def upsert_edge(self, from_label, from_key, to_label, to_key, rel_type, properties, from_key_name="uid", to_key_name="uid"):
        prop_keys = ", ".join([f"r.{k} = ${k}" for k in properties.keys()])
        query = (
            f"MATCH (a:{from_label} {{{from_key_name}: $from_key}}), (b:{to_label} {{{to_key_name}: $to_key}}) "
            f"MERGE (a)-[r:{rel_type}]->(b) "
            f"SET {prop_keys} "
        )
        params = {"from_key": from_key, "to_key": to_key, **properties}
        with self.driver.session() as session:
            session.run(query, **params)