import json
from neo4j import GraphDatabase
import logging
import os

class Neo4jGraphBuilder:
    def __init__(self, credentials_path="infra/neo4j-credentials.json"):
        with open(credentials_path, "r") as f:
            creds = json.load(f)
        self.driver = GraphDatabase.driver(
            creds["uri"], auth=(creds["user"], creds["password"])
        )
        self.logger = logging.getLogger("Neo4jGraphBuilder")

    def close(self):
        self.driver.close()

    def upsert_node(self, label, properties):
        """
        Create or update a node with the given label and properties.
        Uses uid or id as primary key if available.
        """
        key = properties.get("uid") or properties.get("id") or properties.get("name")
        if not key:
            self.logger.warning(f"No key found for node {label}: {properties}")
            return
        prop_keys = ", ".join([f"n.{k} = ${k}" for k in properties.keys()])
        query = (
            f"MERGE (n:{label} {{uid: $uid}}) "
            f"SET {prop_keys} "
        )
        with self.driver.session() as session:
            session.run(query, **properties)

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