from kubernetes import client, config
from kubernetes.client.rest import ApiException
from pathlib import Path
import os
import subprocess
from datetime import datetime
import tempfile 

import logging

class KubeLogFetcher:

    def get_namespaces(self):
        self.logger.info("Retrieving namespaces and tracking deletions")
        for ns in self.v1.list_namespace().items:
            yield {
                "TimeGenerated": self.format_timestamp(ns.metadata.creation_timestamp),
                "name": ns.metadata.name,
                "status": ns.status.phase,
                "labels": ns.metadata.labels,
                "annotations": ns.metadata.annotations,
                "deleted": False
            }


    def get_services(self, last_service_states=None):
        self.logger.info("Retrieving service info for topology/graph analysis")
        for svc in self.v1.list_service_for_all_namespaces().items:
            svc_uid = svc.metadata.uid
            svc_info = {
                "TimeGenerated": self.format_timestamp(svc.metadata.creation_timestamp),
                "uid": svc_uid,
                "name": svc.metadata.name,
                "namespace": svc.metadata.namespace,
                "labels": svc.metadata.labels,
                "annotations": svc.metadata.annotations,
                "deleted": False
            }
            yield svc_info

    def get_endpoints(self, last_endpoint_states=None, since_time=None):
        self.logger.info("Retrieving endpoint info for topology/graph analysis")
        for ep in self.v1.list_endpoints_for_all_namespaces().items:
            if since_time and ep.metadata.creation_timestamp and ep.metadata.creation_timestamp <= since_time:
                continue
            ep_uid = ep.metadata.uid
            ep_info = {
                "TimeGenerated": self.format_timestamp(ep.metadata.creation_timestamp),
                "uid": ep_uid,
                "name": ep.metadata.name,
                "namespace": ep.metadata.namespace,
                "labels": ep.metadata.labels,
                "annotations": ep.metadata.annotations,
                "subsets": [s.to_dict() for s in (ep.subsets or [])]
            }
            yield ep_info

    def get_deployments(self, last_deploy_states=None, since_time=None):
        self.logger.info("Retrieving deployment info for topology/graph analysis")
        apps_v1 = client.AppsV1Api()
        for dep in apps_v1.list_deployment_for_all_namespaces().items:
            if since_time and dep.metadata.creation_timestamp and dep.metadata.creation_timestamp <= since_time:
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
            yield dep_info

    def get_replicasets(self, last_rs_states=None, since_time=None):
        self.logger.info("Retrieving replicaset info for topology/graph analysis")
        apps_v1 = client.AppsV1Api()
        for rs in apps_v1.list_replica_set_for_all_namespaces().items:
            if since_time and rs.metadata.creation_timestamp and rs.metadata.creation_timestamp <= since_time:
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
            yield rs_info

    def get_statefulsets(self, last_ss_states=None, since_time=None):
        self.logger.info("Retrieving statefulset info for topology/graph analysis")
        apps_v1 = client.AppsV1Api()
        for ss in apps_v1.list_stateful_set_for_all_namespaces().items:
            if since_time and ss.metadata.creation_timestamp and ss.metadata.creation_timestamp <= since_time:
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
            yield ss_info
    
    def get_nodes(self, last_node_states=None, since_time=None):
        self.logger.info("Retrieving node info for topology/graph analysis")
        for node in self.v1.list_node().items:
            if since_time and node.metadata.creation_timestamp and node.metadata.creation_timestamp <= since_time:
                continue
            node_uid = node.metadata.uid
            node_info = {
                "TimeGenerated": self.format_timestamp(node.metadata.creation_timestamp),
                "uid": node_uid,
                "name": node.metadata.name,
                "labels": node.metadata.labels,
                "taints": [t.to_dict() for t in (node.spec.taints or [])],
                "annotations": node.metadata.annotations,
            }
            yield node_info
    
    def __init__(self, user_settings):
        self.logger = logging.getLogger("kubeLogger")
        try:
            config.load_kube_config()
            self.logger.info("Loaded kubeconfig successfully.")
        except Exception as e:
            self.logger.error(f"Failed to load kubeconfig: {e}")
            raise
        self.v1 = client.CoreV1Api()
        self.since_seconds = user_settings.get("since_seconds", 86400)
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



    def retrieve_logs_from_pods(self, since_time=None):
        for pod in self.get_pods_stream():
            try:
                if not pod.status.container_statuses:
                    self.logger.info("No container status")
                    continue

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
                                    "podIP": pod.status.pod_ip
                                }

                        except ApiException as e:
                            self.logger.error(f"Could not get {label} logs for {container_name}: {e}")

            except ApiException as e:
                self.logger.error(f"Error accessing pod '{pod.metadata.name}': {e}")
    
    def format_timestamp(self, timestamp):
        # Format from datetime object to plain string, since a datetime is not serializable
        return str(timestamp) if timestamp else ""

    def retrieve_events(self, since_time=None):
        self.logger.info("Fetching events for all namespaces")
        data = self.v1.list_event_for_all_namespaces().items
        for event in data:
            event_time = event.metadata.creation_timestamp
            if since_time and event_time and event_time <= since_time:
                continue
            yield {
                "TimeGenerated": self.format_timestamp(event_time),
                "first_timestamp": self.format_timestamp(event.first_timestamp),
                "last_timestamp": self.format_timestamp(event.last_timestamp) if event.last_timestamp else "",
                "action": event.action,
                "reason": event.reason,
                "message": event.message,
                "involved_object_uid": event.involved_object.uid,
                "involved_object_name": event.involved_object.name,
                "reporting_component": event.reporting_instance
            }
    
    def retrieve_command_history(self, since_time=None):
        
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
    
    def get_service_accounts(self):
        self.logger.info("Retrieving service accounts")
        for ns in self.v1.list_namespace().items:
            namespace = ns.metadata.name
            for sa in self.v1.list_namespaced_service_account(namespace).items:
                creation_timestamp = self.format_timestamp(sa.metadata.creation_timestamp)
                yield {
                    "TimeGenerated": creation_timestamp,
                    "namespace": namespace,
                    "name": sa.metadata.name,
                    "automount_service_account_token": sa.automount_service_account_token,
                    "image_pull_secrets": sa.image_pull_secrets,
                    "deleted": False
                }
    
    def get_suspicious_pods(self, since_time=None):
        self.logger.info("Retrieving possibly suspicious pods")
        for pod in self.get_pods_stream():

            creation_timestamp = self.format_timestamp(pod.metadata.creation_timestamp)
            # Only yield if created after since_time
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

    def get_rbac_bindings(self):
        self.logger.info("Retrieving RBAC bindings")
        for binding in self.rbac_v1.list_role_binding_for_all_namespaces().items:
            creation_timestamp = self.format_timestamp(binding.metadata.creation_timestamp)
            binding_name = binding.metadata.name
            namespace = binding.metadata.namespace
            role_ref_kind = binding.role_ref.kind
            role_ref_name = binding.role_ref.name
            role_ref_api_group = getattr(binding.role_ref, "api_group", None)

            # Try to fetch rules for the referenced role
            rules = None
            try:
                if role_ref_kind == "Role":
                    role = self.rbac_v1.read_namespaced_role(role_ref_name, namespace)
                    rules = [r.to_dict() for r in (role.rules or [])]
                elif role_ref_kind == "ClusterRole":
                    role = self.rbac_v1.read_cluster_role(role_ref_name)
                    rules = [r.to_dict() for r in (role.rules or [])]
            except Exception as e:
                self.logger.warning(f"Could not fetch rules for {role_ref_kind} {role_ref_name}: {e}")

            for subject in binding.subjects or []:
                yield {
                    "TimeGenerated": creation_timestamp,
                    "binding_type": "RoleBinding",
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

        for binding in self.rbac_v1.list_cluster_role_binding().items:
            creation_timestamp = self.format_timestamp(binding.metadata.creation_timestamp)
            binding_name = binding.metadata.name
            namespace = binding.metadata.namespace
            role_ref_kind = binding.role_ref.kind
            role_ref_name = binding.role_ref.name
            role_ref_api_group = getattr(binding.role_ref, "api_group", None)

            # Try to fetch rules for the referenced role
            rules = None
            try:
                if role_ref_kind == "Role":
                    # ClusterRoleBinding should not reference Role, but handle just in case
                    role = self.rbac_v1.read_namespaced_role(role_ref_name, namespace)
                    rules = [r.to_dict() for r in (role.rules or [])]
                elif role_ref_kind == "ClusterRole":
                    role = self.rbac_v1.read_cluster_role(role_ref_name)
                    rules = [r.to_dict() for r in (role.rules or [])]
            except Exception as e:
                self.logger.warning(f"Could not fetch rules for {role_ref_kind} {role_ref_name}: {e}")

            for subject in binding.subjects or []:
                yield {
                    "TimeGenerated": creation_timestamp,
                    "binding_type": "RoleBinding",
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
    
    def get_cronjob_containers_info(self, since_time=None):
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

    def get_network_policies(self):
        self.logger.info("Retrieving Network Policies")
        for np in self.networking_v1.list_network_policy_for_all_namespaces().items:
            creation_timestamp = self.format_timestamp(np.metadata.creation_timestamp)
            yield {
                "TimeGenerated": creation_timestamp,
                "namespace": np.metadata.namespace,
                "name": np.metadata.name,
                "rules": np.spec.to_dict() if hasattr(np, "spec") and np.spec else None,
                "deleted": False
            }