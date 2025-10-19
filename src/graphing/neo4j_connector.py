from neo4j import GraphDatabase, basic_auth
import json
import logging
import os
from typing import Optional, Dict, Any


class Neo4jConnector:
    def __init__(self, credentials_path: Optional[str] = None):
        self.logger = logging.getLogger("Neo4jConnector")
        if credentials_path is None:
            credentials_path = os.path.join(os.getcwd(), "neo4j-credentials.json")
        if not os.path.exists(credentials_path):
            raise FileNotFoundError(f"Credentials file not found: {credentials_path}")
        with open(credentials_path, "r") as f:
            creds = json.load(f)
        uri = creds.get("uri") or f"bolt://{creds.get('vm_public_ip')}:{creds.get('port', 7687)}"
        user = creds.get("neo4j_username") or creds.get("user")
        password = creds.get("neo4j_password") or creds.get("password")
        if not uri or not user or not password:
            raise ValueError("Missing required neo4j credentials (uri/user/password or vm_public_ip/neo4j_username/neo4j_password)")
        self.driver = GraphDatabase.driver(uri, auth=basic_auth(user, password))

    def close(self):
        try:
            self.driver.close()
        except Exception:
            pass

    def run_query(self, query: str, parameters: Optional[Dict[str, Any]] = None, fetch_one: bool = False):
        """Run a Cypher query and return results as list of records (dicts).

        If fetch_one is True, return a single record or None.
        """
        parameters = parameters or {}
        with self.driver.session() as session:
            result = session.run(query, **parameters)
            rows = [record.data() for record in result]
            if fetch_one:
                return rows[0] if rows else None
            return rows

    def scalar(self, query: str, parameters: Optional[Dict[str, Any]] = None):
        """Run a query expected to return a single scalar value (first field of first row).
        Returns None if no rows were returned.
        """
        parameters = parameters or {}
        with self.driver.session() as session:
            result = session.run(query, **parameters)
            rec = result.single()
            if not rec:
                return None
            # return first value
            return rec.values()[0]

    def get_node_count(self, label: str) -> int:
        q = f"MATCH (n:`{label}`) RETURN count(n) as cnt"
        val = self.scalar(q)
        return int(val) if val is not None else 0


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO)
    connector = None
    try:
        creds_path = os.path.join(os.getcwd(), "neo4j-credentials.json")
        connector = Neo4jConnector(credentials_path=creds_path)
        print("Connected to Neo4j")
        # Print counts for a few common labels used by the project
        for label in ["Deployment", "ReplicaSet", "StatefulSet", "Pod", "Namespace"]:
            try:
                cnt = connector.get_node_count(label)
                print(f"{label}: {cnt}")
            except Exception as e:
                print(f"Failed to count nodes for {label}: {e}")
    except Exception as e:
        print(f"Connection/test failed: {e}")
    finally:
        if connector:
            connector.close()
