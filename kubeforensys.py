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
    graph_builder = Neo4jGraphBuilder()

    # Load last upload times from config if present (and not --initial)
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

    # Data sources for stateful resources
    stateful_resources = {
        "namespaces_CL": fetcher.get_namespaces,
        "services_CL": fetcher.get_services,
        "serviceaccounts_CL": fetcher.get_service_accounts,
        "rbacbindings_CL": fetcher.get_rbac_bindings,
        "networkpolicies_CL": fetcher.get_network_policies
    }

    # All data sources
    data_sources = {
        "nodes_CL": fetcher.get_nodes,
        "services_CL": fetcher.get_services,
        "endpoints_CL": fetcher.get_endpoints,
        "deployments_CL": fetcher.get_deployments,
        "replicasets_CL": fetcher.get_replicasets,
        "statefulsets_CL": fetcher.get_statefulsets,
        "namespaces_CL": fetcher.get_namespaces,
        "kubelogs_CL": fetcher.retrieve_logs_from_pods,
        "kubeevents_CL": fetcher.retrieve_events,
        "commandhistory_CL": fetcher.retrieve_command_history,
        "serviceaccounts_CL": fetcher.get_service_accounts,
        "suspiciouspods_CL": fetcher.get_suspicious_pods,
        "rbacbindings_CL": fetcher.get_rbac_bindings,
        "cronjobs_CL": fetcher.get_cronjob_containers_info,
        "networkpolicies_CL": fetcher.get_network_policies
    }

    aks_addon_lister = AksAddonLister(subscription_id, resource_group)
    monitoring_enabled = aks_addon_lister.get_enabled_addon_for_cluster(cluster_name, "omsagent")

    def run_collection():
        updated = False
        # Map table names to Neo4j node labels
        table_to_label = {
            "nodes_CL": "KubeNode",
            "services_CL": "Service",
            "endpoints_CL": "Endpoint",
            "deployments_CL": "Deployment",
            "replicasets_CL": "ReplicaSet",
            "statefulsets_CL": "StatefulSet",
            "namespaces_CL": "Namespace",
            "serviceaccounts_CL": "ServiceAccount",
            "networkpolicies_CL": "NetworkPolicy",
            "rbacbindings_CL": "RoleBinding"
        }
        # Load last seen state for stateful resources
        if config_data is not None and "last_seen_state" in config_data:
            last_seen_state = config_data["last_seen_state"]
        else:
            last_seen_state = {}

        for table_name, fetch_function in data_sources.items():
            if monitoring_enabled and table_name in ["kubelogs_CL", "kubeevents_CL"]:
                continue  # Skip if monitoring is enabled

            label = table_to_label.get(table_name)

            # Stateful resource diff logic (only for Neo4j-mapped tables)
            if label and table_name in stateful_resources:
                current_items = list(fetch_function())
                def get_key(item):
                    if table_name == "namespaces_CL":
                        return item["name"]
                    elif table_name == "services_CL":
                        return f"{item['namespace']}:{item['name']}"
                    elif table_name == "serviceaccounts_CL":
                        return f"{item['namespace']}:{item['name']}"
                    elif table_name == "rbacbindings_CL":
                        return f"{item['namespace']}:{item['binding_name']}"
                    elif table_name == "networkpolicies_CL":
                        return f"{item['namespace']}:{item['name']}"
                    else:
                        return item.get("uid") or item.get("name")

                current_state = {get_key(item): item for item in current_items}
                prev_state = last_seen_state.get(table_name, {})

                # Detect additions
                additions = [item for k, item in current_state.items() if k not in prev_state]
                # Detect deletions
                deletions = [item for k, item in prev_state.items() if k not in current_state]

                # Update graph for additions
                for item in additions:
                    graph_builder.upsert_node(label, item)

                # Update graph for deletions
                for item in deletions:
                    key = get_key(item)
                    graph_builder.delete_node(label, key)

                # Send additions to Azure
                if additions and dcr_mappings:
                    def add_gen():
                        for item in additions:
                            yield item
                    connector.upload_in_batches(
                        generator_function=add_gen,
                        stream_name=f"Custom-{table_name}",
                        dcr_stream_id=dcr_mappings[table_name]["dcr_id"]
                    )

                # Send deletions as custom log entries
                if deletions and dcr_mappings:
                    def del_gen():
                        for item in deletions:
                            del_log = dict(item)
                            del_log["TimeGenerated"] = datetime.now(timezone.utc).isoformat()
                            del_log["deleted"] = True
                            yield del_log
                    connector.upload_in_batches(
                        generator_function=del_gen,
                        stream_name=f"Custom-{table_name}",
                        dcr_stream_id=dcr_mappings[table_name]["dcr_id"]
                    )

                # Update last seen state
                last_seen_state[table_name] = current_state
                if config_data is not None:
                    config_data["last_seen_state"] = last_seen_state
                    updated = True

                # Always update last_upload time for this table
                now = datetime.now(timezone.utc)
                last_fetch_times[table_name] = now
                if config_data is not None:
                    if "last_upload" not in config_data:
                        config_data["last_upload"] = {}
                    config_data["last_upload"][table_name] = now.isoformat()
                    updated = True
            else:
                # For all tables (even those not mapped to Neo4j), upload to Azure
                since_time = last_fetch_times[table_name]
                data_items = list(fetch_function(since_time=since_time))
                # Special handling for kubeevents_CL: create/update Pod nodes for relevant events
                if table_name == "kubeevents_CL":
                    for event in data_items:
                        reason = event.get("reason", "")
                        pod_name = event.get("involved_object_name")
                        pod_uid = event.get("involved_object_uid")
                        namespace = event.get("namespace") or event.get("involved_object_namespace")
                        if pod_name and namespace:
                            pod_key = f"{namespace}:{pod_name}"
                            if reason == "Killing":
                                print(f"Deleting Pod node due to Killing event: {pod_key}")
                                graph_builder.delete_node("Pod", pod_key, key_name="composite_key")
                            elif reason in ["Started", "Created"]:
                                print(f"Upserting Pod node: {pod_key}")
                                pod_props = {
                                    "name": pod_name,
                                    "namespace": namespace,
                                    "uid": pod_uid,
                                    "phase": reason,
                                    "lastSeen": event.get("TimeGenerated"),
                                }
                                graph_builder.upsert_node("Pod", pod_props)
                else:
                    # Update graph for each item (add/update)
                    for item in data_items:
                        graph_builder.upsert_node(label, item)
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

        # Save updated last_upload times and last_seen_state to config file
        if updated:
            with open(CONFIG_PATH, "w") as f:
                json.dump(config_data, f)

    # Run once if --initial is set (even if --continuous is not)
    if user_settings.get("continuous"):
        while True:
            run_collection()
            time.sleep(user_settings.get("interval", 60))
        graph_builder.close()
    else:
        run_collection()
        graph_builder.close()

if __name__ == "__main__":
    main()