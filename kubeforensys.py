from src.collector.k8s_data_collector import KubeLogFetcher
from src.platform.azure.upload.azure_connector import AzureConnector
from src.platform.azure.collect.aks_addon_status import AksAddonLister
from src.platform.azure.create.create_env import AzureLogPipelineProvisioner
from src.utils.load_config import parse_args

from dotenv import load_dotenv
import os
import logging
import logging.config

def main():

    user_settings = parse_args()

    load_dotenv()

    logging.config.fileConfig('logger.conf', disable_existing_loggers=False)
    logger = logging.getLogger("appLogger")
    logging.getLogger("azure").setLevel(logging.WARNING)

    required_env_vars = ["SUBSCRIPTION_ID", "RESOURCE_GROUP_NAME", "CLUSTER_NAME"]
    missing_vars = [var for var in required_env_vars if not os.getenv(var)]
    if missing_vars:
        msg = f"Missing required environment variables: {missing_vars}"
        logger.error(msg)
        raise ValueError(msg)

    subscription_id = os.getenv("SUBSCRIPTION_ID")
    resource_group = os.getenv("RESOURCE_GROUP_NAME")
    cluster_name = os.getenv("CLUSTER_NAME")

    import json
    CONFIG_PATH = "cluster_state.json"
    dcr_mappings = None
    connector = None
    config_data = None

    if user_settings.get("initial"):
        provisioner = AzureLogPipelineProvisioner(
            subscription_id=subscription_id,
            resource_group=resource_group,
            location=user_settings.get("location", "westeurope"),
            workspace_name=user_settings.get("workspace_name", "KubeForenSys-LAW"),
            dce_name=user_settings.get("dce_name", "Kube-DCE"),
        )
        result = provisioner.run()
        logger.info("Initial provisioning complete. Proceeding to data collection.")
        # Save DCE endpoint and DCR mappings to config file
        config_data = {
            "dce_endpoint": result["dce_endpoint"],
            "dcr_mappings": result["dcr_mappings"]
        }
        with open(CONFIG_PATH, "w") as f:
            json.dump(config_data, f)
        connector = AzureConnector(endpoint_uri=result["dce_endpoint"])
        dcr_mappings = result["dcr_mappings"]
    else:
        # Load DCE endpoint and DCR mappings from config file
        try:
            with open(CONFIG_PATH, "r") as f:
                config_data = json.load(f)
            connector = AzureConnector(endpoint_uri=config_data["dce_endpoint"])
            dcr_mappings = config_data["dcr_mappings"]
        except Exception as e:
            logger.error(f"Failed to load DCE endpoint and DCR mappings from {CONFIG_PATH}: {e}")
            raise

    fetcher = KubeLogFetcher(user_settings)
    import time
    from datetime import datetime, timezone
    from src.graphing.neo4j_graph_builder import Neo4jGraphBuilder
    from src.graphing.graph_analysis import run_live_security_analyses
    graph_builder = Neo4jGraphBuilder()

    table_names = [
        "nodes_CL", "services_CL", "endpoints_CL", "deployments_CL", "replicasets_CL",
        "statefulsets_CL", "namespaces_CL", "kubelogs_CL", "kubeevents_CL", 
        "commandhistory_CL", "serviceaccounts_CL", "suspiciouspods_CL", "rbacbindings_CL", 
        "cronjobs_CL", "networkpolicies_CL"
    ]
    last_fetch_times = {k: None for k in table_names}
    if not user_settings.get("initial") and config_data and "last_upload" in config_data:
        for k in table_names:
            t = config_data["last_upload"].get(k)
            if t:
                from datetime import datetime
                try:
                    last_fetch_times[k] = datetime.fromisoformat(t)
                except Exception:
                    last_fetch_times[k] = None

    data_sources = {
        "nodes_CL": fetcher.get_nodes,
        "namespaces_CL": fetcher.get_namespaces,
        "kubelogs_CL": fetcher.retrieve_logs_from_pods,
        "services_CL": fetcher.get_services,
        "endpoints_CL": fetcher.get_endpoints,
        "networkpolicies_CL": fetcher.get_network_policies,
        "deployments_CL": fetcher.get_deployments,
        "replicasets_CL": fetcher.get_replicasets,
        "statefulsets_CL": fetcher.get_statefulsets,
        "kubeevents_CL": fetcher.retrieve_events,
        "commandhistory_CL": fetcher.retrieve_command_history,
        "serviceaccounts_CL": fetcher.get_service_accounts,
        "suspiciouspods_CL": fetcher.get_suspicious_pods,
        "rbacbindings_CL": fetcher.get_rbac_bindings,
        "cronjobs_CL": fetcher.get_cronjob_containers_info
    }

    aks_addon_lister = AksAddonLister(subscription_id, resource_group)
    monitoring_enabled = aks_addon_lister.get_enabled_addon_for_cluster(cluster_name, "omsagent")

    def run_collection():
        updated = False

        for table_name, fetch_function in data_sources.items():
            if monitoring_enabled and table_name in ["kubelogs_CL", "kubeevents_CL"]:
                continue  # Skip if monitoring is enabled

            since_time = last_fetch_times[table_name]
            data_items = list(fetch_function(graph_builder=graph_builder, since_time=since_time))

            def data_gen():
                for item in data_items:
                    yield item
            if dcr_mappings:
                connector.upload_in_batches(
                    generator_function=data_gen,
                    stream_name=f"Custom-{table_name}",
                    dcr_stream_id=dcr_mappings[table_name]["dcr_id"]
                )
            now = datetime.now(timezone.utc)
            last_fetch_times[table_name] = now
            if config_data is not None:
                if "last_upload" not in config_data:
                    config_data["last_upload"] = {}
                config_data["last_upload"][table_name] = now.isoformat()
                updated = True

        if updated:
            with open(CONFIG_PATH, "w") as f:
                json.dump(config_data, f)

    if user_settings.get("continuous"):
        while True:
            run_collection()
            try:
                G, report = graph_builder.to_networkx_full_graph()
                neo_nodes = report.get("neo4j_node_count")
                neo_rels = report.get("neo4j_rel_count")
                nx_nodes = report.get("networkx_node_count")
                nx_rels = report.get("networkx_rel_count")
                if (neo_nodes is not None and neo_nodes != nx_nodes) or (neo_rels is not None and neo_rels != nx_rels):
                    logger.warning(f"Graph discrepancy detected after run: neo4j nodes={neo_nodes} networkx nodes={nx_nodes}; neo4j rels={neo_rels} networkx rels={nx_rels}")
                    print("Discrepancy detail summary:")
                    print(f"  node_discrepancies: {report.get('node_discrepancies')}")
                    print(f"  rel_discrepancies: {report.get('rel_discrepancies')}")
                try:
                    prev_graph_state = (config_data or {}).get("graph_state", {}) if config_data is not None else {}
                    print("Running LIVE security analyses (betweenness, communities, temporal anomalies, closeness, pagerank)...")
                    analysis = run_live_security_analyses(G, previous_state=prev_graph_state, print_results=True, top_k=10)
                    new_state = analysis.get("updated_state", {})
                    if config_data is None:
                        config_data = {}
                    config_data["graph_state"] = new_state
                    with open(CONFIG_PATH, "w") as f:
                        json.dump(config_data, f)
                except Exception as e:
                    logger.exception(f"Failed to run LIVE security analyses: {e}")
            except Exception as e:
                logger.exception(f"Failed to convert/validate Neo4j -> NetworkX: {e}")
            time.sleep(user_settings.get("interval", 60))
        graph_builder.close()
    else:
        run_collection()
        try:
            G, report = graph_builder.to_networkx_full_graph()
            neo_nodes = report.get("neo4j_node_count")
            neo_rels = report.get("neo4j_rel_count")
            nx_nodes = report.get("networkx_node_count")
            nx_rels = report.get("networkx_rel_count")
            if (neo_nodes is not None and neo_nodes != nx_nodes) or (neo_rels is not None and neo_rels != nx_rels):
                logger.warning(f"Graph discrepancy detected: neo4j nodes={neo_nodes} networkx nodes={nx_nodes}; neo4j rels={neo_rels} networkx rels={nx_rels}")
                print("Discrepancy detail summary:")
                print(f"  node_discrepancies: {report.get('node_discrepancies')}")
                print(f"  rel_discrepancies: {report.get('rel_discrepancies')}")
        except Exception as e:
            logger.exception(f"Failed to convert/validate Neo4j -> NetworkX: {e}")
        graph_builder.close()

if __name__ == "__main__":
    main()