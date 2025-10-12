from kubernetes import client, config
from kubernetes.client.rest import ApiException
from pathlib import Path
import os
import subprocess
from datetime import datetime
import tempfile 

import logging

class KubeLogFetcher:

    def get_namespaces(self, graph_builder=None, since_time=None):
        self.logger.info("Retrieving namespaces and tracking deletions")
        current_keys = []
        for ns in self.v1.list_namespace().items:
            if ns.metadata.name in self.namespaces_to_skip:
                continue           
            ns_info = {
                "TimeGenerated": self.format_timestamp(ns.metadata.creation_timestamp),
                "name": ns.metadata.name,
                "status": ns.status.phase,
                "labels": ns.metadata.labels,
                "annotations": ns.metadata.annotations,
                "deleted": False
            }
            if graph_builder:
                graph_builder.upsert_node("Namespace", ns_info)
                key = graph_builder.get_composite_key("Namespace", ns_info)
                current_keys.append(key)
            if since_time and ns.metadata.creation_timestamp and ns.metadata.creation_timestamp <= since_time:
                continue
            yield ns_info
        if graph_builder:
            graph_builder.delete_nodes_and_edges_not_in("Namespace", current_keys)


    def get_services(self, graph_builder=None, last_service_states=None, since_time=None):
        self.logger.info("Retrieving service info for topology/graph analysis")
        current_keys = []
        for svc in self.v1.list_service_for_all_namespaces().items:
            if svc.metadata.namespace in self.namespaces_to_skip:
                continue           
            svc_uid = svc.metadata.uid
            selector_pod_keys = []
            if svc.spec.selector:
                label_selector = ','.join([f"{k}={v}" for k, v in svc.spec.selector.items()])
                pods = self.v1.list_namespaced_pod(namespace=svc.metadata.namespace, label_selector=label_selector).items
                for pod in pods:
                    selector_pod_keys.append(f"{pod.metadata.namespace}:{pod.metadata.name}")
            svc_info = {
                "TimeGenerated": self.format_timestamp(svc.metadata.creation_timestamp),
                "uid": svc_uid,
                "name": svc.metadata.name,
                "namespace": svc.metadata.namespace,
                "labels": svc.metadata.labels,
                "annotations": svc.metadata.annotations,
                "deleted": False,
                "selector_pod_keys": selector_pod_keys
            }
            if graph_builder:
                graph_builder.upsert_node("Service", svc_info)
                key = graph_builder.get_composite_key("Service", svc_info)
                current_keys.append(key)
                ns = svc_info.get("namespace")
                if ns:
                    from_key = key
                    graph_builder.upsert_edge("Service", from_key, "Namespace", ns, "IN_NAMESPACE", {})
                for pod_key in selector_pod_keys:
                    svc_key = key
                    if not pod_key:
                        self.logger.warning(f"Pod key is empty for service {svc_info.get('name')}")
                    graph_builder.upsert_edge("Service", svc_key, "Pod", pod_key, "SELECTS")
            if since_time and svc.metadata.creation_timestamp and svc.metadata.creation_timestamp <= since_time:
                continue
            yield svc_info
        if graph_builder:
            edge_types = [
                ("Service", "IN_NAMESPACE", "Namespace"),
                ("Service", "SELECTS", "Pod")
            ]
            graph_builder.delete_nodes_and_edges_not_in("Service", current_keys, edge_types=edge_types)

    def get_endpoints(self, graph_builder=None, last_endpoint_states=None, since_time=None):
        self.logger.info("Retrieving endpoint info for topology/graph analysis")
        current_keys = []
        for ep in self.v1.list_endpoints_for_all_namespaces().items:
            if ep.metadata.namespace in self.namespaces_to_skip:
                continue
            ep_uid = ep.metadata.uid
            pod_keys = []
            for subset in ep.subsets or []:
                for addr in subset.addresses or []:
                    if addr.target_ref and addr.target_ref.kind == "Pod":
                        pod_keys.append(f"{ep.metadata.namespace}:{addr.target_ref.name}")
            ep_info = {
                "TimeGenerated": self.format_timestamp(ep.metadata.creation_timestamp),
                "uid": ep_uid,
                "name": ep.metadata.name,
                "namespace": ep.metadata.namespace,
                "labels": ep.metadata.labels,
                "annotations": ep.metadata.annotations,
                "subsets": [s.to_dict() for s in (ep.subsets or [])],
                "pod_keys": pod_keys
            }
            if graph_builder:
                graph_builder.upsert_node("Endpoint", ep_info)
                key = graph_builder.get_composite_key("Endpoint", ep_info)
                current_keys.append(key)
                for pod_key in pod_keys:
                    ep_key = key
                    graph_builder.upsert_edge("Endpoint", ep_key, "Pod", pod_key, "ENDPOINT_OF")
            if since_time and ep.metadata.creation_timestamp and ep.metadata.creation_timestamp <= since_time:
                self.logger.warning(f"Since_time is {since_time}, skipping endpoint {ep.metadata.name}, created at {ep.metadata.creation_timestamp}")
                continue
            yield ep_info
        if graph_builder:
            edge_types = [("Endpoint", "ENDPOINT_OF", "Pod")]
            graph_builder.delete_nodes_and_edges_not_in("Endpoint", current_keys, edge_types=edge_types)

    def get_deployments(self, graph_builder=None, last_deploy_states=None, since_time=None):
        self.logger.info("Retrieving deployment info for topology/graph analysis")
        apps_v1 = client.AppsV1Api()
        current_keys = []
        for dep in apps_v1.list_deployment_for_all_namespaces().items:
            if dep.metadata.namespace in self.namespaces_to_skip:
                continue
            dep_uid = dep.metadata.uid
            dep_info = {
                "TimeGenerated": self.format_timestamp(dep.metadata.creation_timestamp),
                "uid": dep_uid,
                "name": dep.metadata.name,
                "namespace": dep.metadata.namespace,
                "labels": dep.metadata.labels,
                "annotations": dep.metadata.annotations,
            }
            if graph_builder:
                graph_builder.upsert_node("Deployment", dep_info)
                key = graph_builder.get_composite_key("Deployment", dep_info)
                current_keys.append(key)
            if since_time and dep.metadata.creation_timestamp and dep.metadata.creation_timestamp <= since_time:
                continue
            yield dep_info
        if graph_builder:
            graph_builder.delete_nodes_and_edges_not_in("Deployment", current_keys)

    def get_replicasets(self, graph_builder=None, last_rs_states=None, since_time=None):
        self.logger.info("Retrieving replicaset info for topology/graph analysis")
        apps_v1 = client.AppsV1Api()
        current_keys = []
        for rs in apps_v1.list_replica_set_for_all_namespaces().items:
            if rs.metadata.namespace in self.namespaces_to_skip:
                continue
            rs_uid = rs.metadata.uid
            rs_info = {
                "TimeGenerated": self.format_timestamp(rs.metadata.creation_timestamp),
                "uid": rs_uid,
                "name": rs.metadata.name,
                "namespace": rs.metadata.namespace,
                "labels": rs.metadata.labels,
                "annotations": rs.metadata.annotations,
            }
            if graph_builder:
                graph_builder.upsert_node("ReplicaSet", rs_info)
                key = graph_builder.get_composite_key("ReplicaSet", rs_info)
                current_keys.append(key)
                # Add OWNS edge for all owner kinds
                if rs.metadata.owner_references:
                    for owner in rs.metadata.owner_references:
                        owner_info = {
                            "name": owner.name,
                            "namespace": rs.metadata.namespace
                        }
                        owner_key = graph_builder.get_composite_key(owner.kind, owner_info)
                        graph_builder.upsert_edge(owner.kind, owner_key, "ReplicaSet", key, "OWNS")
            if since_time and rs.metadata.creation_timestamp and rs.metadata.creation_timestamp <= since_time:
                continue
            yield rs_info
        if graph_builder:
            edge_types = [("Deployment", "OWNS", "ReplicaSet")]
            graph_builder.delete_nodes_and_edges_not_in("ReplicaSet", current_keys, edge_types=edge_types)

    def get_statefulsets(self, graph_builder=None, last_ss_states=None, since_time=None):
        self.logger.info("Retrieving statefulset info for topology/graph analysis")
        apps_v1 = client.AppsV1Api()
        current_keys = []
        for ss in apps_v1.list_stateful_set_for_all_namespaces().items:
            if ss.metadata.namespace in self.namespaces_to_skip:
                continue
            ss_uid = ss.metadata.uid
            ss_info = {
                "TimeGenerated": self.format_timestamp(ss.metadata.creation_timestamp),
                "uid": ss_uid,
                "name": ss.metadata.name,
                "namespace": ss.metadata.namespace,
                "labels": ss.metadata.labels,
                "annotations": ss.metadata.annotations,
            }
            if graph_builder:
                graph_builder.upsert_node("StatefulSet", ss_info)
                key = graph_builder.get_composite_key("StatefulSet", ss_info)
                current_keys.append(key)
            if since_time and ss.metadata.creation_timestamp and ss.metadata.creation_timestamp <= since_time:
                continue
            yield ss_info
        if graph_builder:
            graph_builder.delete_nodes_and_edges_not_in("StatefulSet", current_keys)
    
    def get_nodes(self, graph_builder=None, last_node_states=None, since_time=None):
        self.logger.info("Retrieving node info for topology/graph analysis")
        current_keys = []
        for node in self.v1.list_node().items:
            node_uid = node.metadata.uid
            node_info = {
                "TimeGenerated": self.format_timestamp(node.metadata.creation_timestamp),
                "uid": node_uid,
                "name": node.metadata.name,
                "labels": node.metadata.labels,
                "taints": [t.to_dict() for t in (node.spec.taints or [])],
                "annotations": node.metadata.annotations,
            }
            if graph_builder:
                graph_builder.upsert_node("KubeNode", node_info)
                current_keys.append(node_info["name"])
            if since_time and node.metadata.creation_timestamp and node.metadata.creation_timestamp <= since_time:
                self.logger.warning(f"Since_time is {since_time}, skipping node {node.metadata.name}, created at {node.metadata.creation_timestamp}")
                continue
            yield node_info
        if graph_builder:
            graph_builder.delete_nodes_and_edges_not_in("KubeNode", current_keys, None, "name")

    def __init__(self, user_settings):
        self.logger = logging.getLogger("kubeLogger")
        try:
            config.load_kube_config()
            self.logger.info("Loaded kubeconfig successfully.")
        except Exception as e:
            self.logger.error(f"Failed to load kubeconfig: {e}")
            raise
        self.v1 = client.CoreV1Api()
        self.since_seconds = user_settings.get("since_seconds", 2147483647)  # Default to max int if not set
        self.namespaces_to_skip = ["kube-system", "azure-arc", "gatekeeper-system"]
        self.pod_batch_size = 500
        self.rbac_v1 = client.RbacAuthorizationV1Api()
        self.batch_v1 = client.BatchV1Api()
        self.networking_v1 = client.NetworkingV1Api()
    
    def is_pod_valid(self, pod):
        return pod.status.phase != "Succeeded" and pod.metadata.namespace not in self.namespaces_to_skip
    

    def get_pods_stream(self):
        try:
            pods = self.v1.list_pod_for_all_namespaces(limit=self.pod_batch_size)
            while True:
                for pod in pods.items:
                    if self.is_pod_valid(pod):
                        yield pod
                if pods.metadata._continue:
                    pods = self.v1.list_pod_for_all_namespaces(limit=self.pod_batch_size, _continue=pods.metadata._continue)
                else:
                    break
        except ApiException as e:
            self.logger.error(f"Error fetching pods: {e}")

    def retrieve_logs_from_pods(self, graph_builder=None, since_time=None):
        self.logger.info("Retrieving logs from pods and upserting Pod nodes")
        current_keys = []
        for pod in self.get_pods_stream():
            try:
                # Upsert Pod node for graph
                pod_info = {
                    "TimeGenerated": self.format_timestamp(pod.metadata.creation_timestamp),
                    "name": pod.metadata.name,
                    "namespace": pod.metadata.namespace,
                    "labels": pod.metadata.labels,
                    "annotations": pod.metadata.annotations,
                    "nodeName": pod.spec.node_name,
                    "podIP": pod.status.pod_ip,
                    "images": [c.image for c in pod.spec.containers],
                    "deleted": False
                }
                if graph_builder:
                    graph_builder.upsert_node("Pod", pod_info)
                    key = graph_builder.get_composite_key("Pod", pod_info)
                    current_keys.append(key)
                    node_name = pod.spec.node_name
                    if node_name:
                        graph_builder.upsert_edge("Pod", key, "KubeNode", node_name, "RUNS_ON", {}, "composite_key", "name")
                    if pod.metadata.owner_references:
                        for owner in pod.metadata.owner_references:
                            if owner.kind in ("Deployment", "ReplicaSet", "StatefulSet"):
                                owner_info = {
                                    "name": owner.name,
                                    "namespace": pod.metadata.namespace
                                }
                                owner_key = graph_builder.get_composite_key(owner.kind, owner_info)
                                graph_builder.upsert_edge(owner.kind, owner_key, "Pod", key, "OWNS")
                    ns = pod.metadata.namespace
                    if ns:
                        graph_builder.upsert_edge("Pod", key, "Namespace", ns, "IN_NAMESPACE", {})

                if not pod.status.container_statuses:
                    self.logger.info("No container status")
                    continue

                # Try to get service account name
                service_account_name = pod.spec.service_account_name if hasattr(pod.spec, "service_account_name") else None
                # Add AUTHENTICATED_AS edge: Pod -> ServiceAccount
                if graph_builder and service_account_name:
                    pod_key = graph_builder.get_composite_key("Pod", pod_info)
                    sa_info = {"namespace": pod.metadata.namespace, "name": service_account_name}
                    sa_key = graph_builder.get_composite_key("ServiceAccount", sa_info)
                    graph_builder.upsert_edge("Pod", pod_key, "ServiceAccount", sa_key, "AUTHENTICATED_AS")

                for container_status in pod.status.container_statuses:
                    container_name = container_status.name

                    # Determine if we should collect previous logs based on whether the container restarted
                    log_modes = [("current", False)]
                    if container_status.restart_count > 0:
                        self.logger.info("Running with Previous true")
                        log_modes.insert(0, ("previous", True))

                    for label, is_previous in log_modes:
                        self.logger.info(f"Fetching {label} logs for container: {container_name}")

                        try:
                            log_response = self.v1.read_namespaced_pod_log(
                                name=pod.metadata.name,
                                namespace=pod.metadata.namespace,
                                container=container_name,
                                timestamps=True,
                                previous=is_previous,
                                since_seconds=self.since_seconds,
                                _preload_content=False
                            )

                            if not log_response:
                                continue  # skip empty logs

                            for raw_line in log_response:
                                line = raw_line.decode("utf-8")
                                timestamp, message = line.split(" ", maxsplit=1)
                                # If since_time is set, filter logs by log line timestamp
                                if since_time:
                                    from datetime import datetime
                                    try:
                                        log_time = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                                    except Exception:
                                        continue
                                    if log_time <= since_time:
                                        continue
                                yield {
                                    "TimeGenerated": self.format_timestamp(timestamp),
                                    "message": message,
                                    "container_name": container_name,
                                    "container_restart_count": container_status.restart_count,
                                    "namespace": pod.metadata.namespace,
                                    "pod_name": pod.metadata.name,
                                    "images": [c.image for c in pod.spec.containers],
                                    "labels": pod.metadata.labels,
                                    "annotations": pod.metadata.annotations,
                                    "ownerReferences": [ref.to_dict() for ref in (pod.metadata.owner_references or [])],
                                    "nodeName": pod.spec.node_name,
                                    "podIP": pod.status.pod_ip,
                                    "service_account_name": service_account_name
                                }

                        except ApiException as e:
                            self.logger.error(f"Could not get {label} logs for {container_name}: {e}")

            except ApiException as e:
                self.logger.error(f"Error accessing pod '{pod.metadata.name}': {e}")
        if graph_builder:
            edge_types = [
                ("Pod", "RUNS_ON", "KubeNode"),
                ("ReplicaSet", "OWNS", "Pod"),
                ("StatefulSet", "OWNS", "Pod"),
                ("Pod", "IN_NAMESPACE", "Namespace")
            ]
            graph_builder.delete_nodes_and_edges_not_in("Pod", current_keys, edge_types=edge_types)

    def format_timestamp(self, timestamp):
        # Format from datetime object to plain string, since a datetime is not serializable
        return str(timestamp) if timestamp else ""

    def retrieve_events(self, graph_builder=None, since_time=None):
        self.logger.info("Fetching events for all namespaces")
        data = self.v1.list_event_for_all_namespaces().items
        for event in data:
            event_time = event.metadata.creation_timestamp
            if since_time and event_time and event_time <= since_time:
                continue
            namespace = getattr(event.involved_object, "namespace", None)
            yield {
                "TimeGenerated": self.format_timestamp(event_time),
                "first_timestamp": self.format_timestamp(event.first_timestamp),
                "last_timestamp": self.format_timestamp(event.last_timestamp) if event.last_timestamp else "",
                "action": event.action,
                "reason": event.reason,
                "message": event.message,
                "involved_object_uid": event.involved_object.uid,
                "involved_object_name": event.involved_object.name,
                "namespace": namespace,
                "reporting_component": event.reporting_instance
            }

    def retrieve_command_history(self, graph_builder=None, since_time=None):

        HISTORY_PATHS = [
        "/root/.ash_history",
        "/root/.bash_history"
        ]
        self.logger.info("Retrieving command history")
        for pod in self.get_pods_stream():

            with tempfile.TemporaryDirectory() as temp_dir:
                for container in pod.spec.containers:
                    for history_path in HISTORY_PATHS:
                        dest_file = os.path.join(temp_dir, f"{container.name}_{os.path.basename(history_path)}")
                        self.logger.info(f"Attempting to copy {history_path} from {pod.metadata.name}/{container.name}")
                        
                        try:
                            subprocess.run([
                                "kubectl", "cp",
                                f"{pod.metadata.namespace}/{pod.metadata.name}:{history_path}",
                                dest_file,
                                "-c", container.name
                            ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

                            with open(dest_file, "r", encoding="utf-8", errors="ignore") as f:
                                for line in f:
                                    line = line.strip()
                                    if line:
                                        # Optionally filter by since_time if needed (not timestamped, so skip for now)
                                        yield {
                                            "TimeGenerated": datetime.utcnow().isoformat(),
                                            "namespace": pod.metadata.namespace,
                                            "pod_name": pod.metadata.name,
                                            "container_name": container.name,
                                            "command": line
                                        }

                        except subprocess.CalledProcessError:
                            self.logger.error(f"Failed to copy {history_path} from {pod.metadata.name}/{container.name}")
                        except FileNotFoundError:
                            continue
    
    def get_service_accounts(self, graph_builder=None, since_time=None):
        self.logger.info("Retrieving service accounts")
        current_keys = []
        for ns in self.v1.list_namespace().items:
            namespace = ns.metadata.name
            if namespace in self.namespaces_to_skip:
                continue
            for sa in self.v1.list_namespaced_service_account(namespace).items:                
                creation_timestamp = self.format_timestamp(sa.metadata.creation_timestamp)
                sa_info = {
                    "TimeGenerated": creation_timestamp,
                    "namespace": namespace,
                    "name": sa.metadata.name,
                    "automount_service_account_token": sa.automount_service_account_token,
                    "image_pull_secrets": sa.image_pull_secrets,
                    "deleted": False
                }
                if graph_builder:
                    graph_builder.upsert_node("ServiceAccount", sa_info)
                    key = graph_builder.get_composite_key("ServiceAccount", sa_info)
                    current_keys.append(key)
                if since_time and sa.metadata.creation_timestamp and sa.metadata.creation_timestamp <= since_time:
                    continue
                yield sa_info
        if graph_builder:
            graph_builder.delete_nodes_and_edges_not_in("ServiceAccount", current_keys)

    def get_suspicious_pods(self, graph_builder=None, since_time=None):
        self.logger.info("Retrieving possibly suspicious pods")
        for pod in self.get_pods_stream():

            creation_timestamp = self.format_timestamp(pod.metadata.creation_timestamp)
            if since_time and pod.metadata.creation_timestamp and pod.metadata.creation_timestamp <= since_time:
                continue

            name = pod.metadata.name
            ns = pod.metadata.namespace
            spec = pod.spec

            if spec.host_network:
                yield {
                    "TimeGenerated": creation_timestamp,
                    "pod_name": name,
                    "namespace": ns,
                    "issue_type": "hostNetwork",
                    "details": "hostNetwork=true"
                }

            for container in spec.containers:
                security = container.security_context
                if security and security.privileged:
                    yield {
                        "TimeGenerated": creation_timestamp,
                        "name": name,
                        "namespace": ns,
                        "issue_type": "privileged",
                        "details": f"{container.name}: privileged=true"
                    }

            for volume in spec.volumes or []:
                if volume.host_path:
                    vol_type = volume.host_path.type or ""
                    if vol_type in ["DirectoryOrCreate", "FileOrCreate"]:
                        issue = "hostPath (creation-capable)"
                    else:
                        issue = "hostPath"
                    yield {
                        "TimeGenerated": creation_timestamp,
                        "name": name,
                        "namespace": ns,
                        "issue_type": issue,
                        "details": f"hostPath: {volume.host_path.path}, type: {vol_type}"
                    }

    def get_rbac_bindings(self, graph_builder=None, since_time=None):
        self.logger.info("Retrieving RBAC bindings")
        current_keys = []

        # Loop over RoleBindings (namespaced) and ClusterRoleBindings (cluster-scoped)
        def fetch_role_rules(kind, name, namespace=None):
            try:
                if kind == "Role" and namespace:
                    role = self.rbac_v1.read_namespaced_role(name, namespace)
                elif kind == "ClusterRole":
                    role = self.rbac_v1.read_cluster_role(name)
                else:
                    return None
                return [r.to_dict() for r in (role.rules or [])]
            except Exception as e:
                self.logger.warning(f"Could not fetch rules for {kind} {name}: {e}")
                return None
        bindings = (
            [(b, False) for b in self.rbac_v1.list_role_binding_for_all_namespaces().items] +
            [(b, True) for b in self.rbac_v1.list_cluster_role_binding().items]
        )

        for binding, is_cluster_scope in bindings:           
            creation_timestamp = self.format_timestamp(binding.metadata.creation_timestamp)
            binding_name = binding.metadata.name
            namespace = binding.metadata.namespace

            if namespace in self.namespaces_to_skip:
                continue

            role_ref_kind = binding.role_ref.kind
            role_ref_name = binding.role_ref.name
            role_ref_api_group = getattr(binding.role_ref, "api_group", None)
            rules = fetch_role_rules(role_ref_kind, role_ref_name, namespace)

            for subject in binding.subjects or []:
                rb_info = {
                    "TimeGenerated": creation_timestamp,
                    "binding_type": "ClusterRoleBinding" if is_cluster_scope else "RoleBinding",
                    "binding_name": binding_name,
                    "namespace": namespace,
                    "subject_kind": subject.kind,
                    "subject_name": subject.name,
                    "subject_namespace": getattr(subject, "namespace", namespace),
                    "role_ref_kind": role_ref_kind,
                    "role_ref_name": role_ref_name,
                    "role_ref_api_group": role_ref_api_group,
                    "rules": rules,
                    "subjects": [s.to_dict() for s in (binding.subjects or [])],
                    "roleRef": binding.role_ref.to_dict() if hasattr(binding, "role_ref") else None,
                    "deleted": False
                }

                # Composite key for binding
                if is_cluster_scope:
                    binding_key = graph_builder.get_composite_key("ClusterRoleBinding", {"binding_name": binding_name}) if graph_builder else f"{binding_name}"
                else:
                    ns = namespace if namespace is not None else "default"
                    binding_key = graph_builder.get_composite_key("RoleBinding", {"namespace": ns, "binding_name": binding_name}) if graph_builder else f"{ns}:{binding_name}"
                current_keys.append(binding_key)

                if graph_builder:
                    graph_builder.upsert_node(rb_info["binding_type"], rb_info)

                if subject.kind == "ServiceAccount":
                    sa_ns = getattr(subject, "namespace", namespace)
                    if sa_ns is None:
                        sa_ns = "default"
                    sa_name = subject.name
                    sa_key = graph_builder.get_composite_key("ServiceAccount", {"namespace": sa_ns, "name": sa_name}) if graph_builder else f"{sa_ns}:{sa_name}"
                    if graph_builder:
                        graph_builder.upsert_edge("ServiceAccount", sa_key, rb_info["binding_type"], binding_key, "GRANTED")
                else:
                    self.logger.info(f"RBAC binding {binding_name}: ignoring subject kind {subject.kind} ({getattr(subject, 'name', None)})")
                if since_time and binding.metadata.creation_timestamp and binding.metadata.creation_timestamp <= since_time:
                    continue
                yield rb_info

        if graph_builder:
            graph_builder.delete_nodes_and_edges_not_in("RoleBinding", current_keys)
            graph_builder.delete_nodes_and_edges_not_in("ClusterRoleBinding", current_keys)

    def get_cronjob_containers_info(self, graph_builder=None, since_time=None):
        self.logger.info("Extracting CronJob container info")
        for cj in self.batch_v1.list_cron_job_for_all_namespaces().items:
            creation_timestamp = self.format_timestamp(cj.metadata.creation_timestamp)
            cj_name = cj.metadata.name
            namespace = cj.metadata.namespace
            containers = cj.spec.job_template.spec.template.spec.containers

            if since_time and cj.metadata.creation_timestamp and cj.metadata.creation_timestamp <= since_time:
                continue
            for c in containers:
                command_str = " ".join(c.command) if c.command else ""
                yield {
                    "TimeGenerated": creation_timestamp,
                    "cronjob_name": cj_name,
                    "namespace": namespace,
                    "container_name": c.name,
                    "image": c.image,
                    "command": command_str,
                    "schedule": cj.spec.schedule
                }

    def get_network_policies(self, graph_builder=None, since_time=None):
        self.logger.info("Retrieving Network Policies")
        current_keys = []
        for np in self.networking_v1.list_network_policy_for_all_namespaces().items:
            if np.metadata.namespace in self.namespaces_to_skip:
                continue
            creation_timestamp = self.format_timestamp(np.metadata.creation_timestamp)
            allowed_pod_keys = []
            # Handle podSelector: {} at the policy level (matches all pods in the namespace)
            if hasattr(np, "spec") and np.spec and hasattr(np.spec, "pod_selector") and np.spec.pod_selector is not None:
                pod_selector = getattr(np.spec, "pod_selector", None)
                if pod_selector is not None:
                    match_labels = getattr(pod_selector, "match_labels", None)
                    if not match_labels:  # True if None or empty dict
                        # podSelector: {} matches all pods
                        pods = self.v1.list_namespaced_pod(namespace=np.metadata.namespace).items
                        for pod in pods:
                            allowed_pod_keys.append(f"{pod.metadata.namespace}:{pod.metadata.name}")
            # Try to resolve allowed pods from ingress/egress rules
            if hasattr(np, "spec") and np.spec and np.spec.ingress:
                for ingress in np.spec.ingress:
                    for peer in getattr(ingress, "from", []) or []:
                        if getattr(peer, "pod_selector", None):
                            label_selector = ','.join([f"{k}={v}" for k, v in peer.pod_selector.match_labels.items()])
                            pods = self.v1.list_namespaced_pod(namespace=np.metadata.namespace, label_selector=label_selector).items
                            for pod in pods:
                                allowed_pod_keys.append(f"{pod.metadata.namespace}:{pod.metadata.name}")
            np_info = {
                "TimeGenerated": creation_timestamp,
                "namespace": np.metadata.namespace,
                "name": np.metadata.name,
                "rules": np.spec.to_dict() if hasattr(np, "spec") and np.spec else None,
                "deleted": False,
                "allowed_pod_keys": allowed_pod_keys
            }
            if graph_builder:
                graph_builder.upsert_node("NetworkPolicy", np_info)
                key = graph_builder.get_composite_key("NetworkPolicy", np_info)
                current_keys.append(key)
                for pod_key in allowed_pod_keys:
                    graph_builder.upsert_edge("NetworkPolicy", key, "Pod", pod_key, "ALLOWS")
            if since_time and np.metadata.creation_timestamp and np.metadata.creation_timestamp <= since_time:
                continue
            yield np_info
        if graph_builder:
            edge_types = [("NetworkPolicy", "ALLOWS", "Pod")]
            graph_builder.delete_nodes_and_edges_not_in("NetworkPolicy", current_keys, edge_types=edge_types)