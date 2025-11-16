
#!/bin/bash
# set -euo pipefail

# Revised Attack1: ServiceAccount token theft + cross-namespace pivot (models Pod → ServiceAccount → Namespace path)
#
# Important modelling note (FIX applied): in our graph model ServiceAccounts do NOT have a direct
# edge to Namespace. All ServiceAccount "reach" into namespaces is only visible via Pods:
#
#   Pod AUTHENTICATED_AS ServiceAccount
#   Pod IN_NAMESPACE       Namespace
#
# Therefore this script explicitly creates a pivot Pod in a target namespace that is
# authenticated as the (compromised/escalated) ServiceAccount. That Pod → ServiceAccount → Pod → Namespace
# subgraph is what influences betweenness, closeness and RBAC PageRank for SAs. Detection logic
# should look for changes in Pod distribution and the new Pod->SA edges as the root cause,
# not a direct SA->Namespace edge.
#
# Attack flow modeled here (Scenario: Token theft + cross-namespace pivot):
# 1) Ensure source and target namespaces exist (ns-01, ns-02)
# 2) Create a privileged ServiceAccount in kube-system (sa-evil) and bind a ClusterRoleBinding
#    to simulate privilege escalation (GRANTED / ClusterRoleBinding edge)
# 3) Create an initial compromised Pod in ns-01 (compromised-app) that demonstrates the
#    initial foothold (Pod AUTHENTICATED_AS default)
# 4) Using the stolen/elevated SA, create a new Pod in ns-02 with serviceAccountName=sa-evil
#    (Pod AUTHENTICATED_AS sa-evil; Pod IN_NAMESPACE ns-02). This is the lateral pivot.
# 5) Optionally create a Service in ns-02 and annotate it to indicate cross-namespace selection
#    (for graph collectors that infer SELECTS/SELECTED_BY). If you can produce traffic from the
#    new Pod to pods in ns-01, collectors will create communicates_with edges and community changes.
#
# Detection expectations (root-cause mapping):
# - Betweenness pivoting: increase for the Pod(s) and for the SA only insofar as the SA has
#   associated pods in multiple namespaces (i.e., the SA's pods act as bridges).
# - Closeness influence: the pivot Pod's closeness will increase when it acquires short paths
#   into many other nodes (services/pods) across namespaces.
# - RBAC PageRank: spikes when the SA receives ClusterRoleBinding/RoleBinding edges (authority)
# - Community changes: communities merge if new cross-namespace communication edges are created
#   (e.g., pivot Pod talks to services/pods in another namespace).

INTERVAL_SEC="${INTERVAL_SEC:-40}"
SRC_NS="ns-01"
TGT_NS="ns-02"
KUBE_SYS_NS="kube-system"
SA_NAME="sa-evil"
CRB_NAME="crb-sa-evil-cluster-admin"
COMP_POD_NAME="compromised-app-01"
PIVOT_POD_NAME="pivot-${SA_NAME}-${TGT_NS}"
BRIDGE_SVC_NAME="svc-bridge-${TGT_NS}"

echo "=== Revised Attack1: Token theft + cross-namespace pivot ==="

echo "[Step 1] Ensure namespaces exist: ${SRC_NS}, ${TGT_NS}, ${KUBE_SYS_NS}"
for ns in "$SRC_NS" "$TGT_NS" "$KUBE_SYS_NS"; do
		kubectl get ns "$ns" >/dev/null 2>&1 || kubectl create ns "$ns"
done

echo "[Step 2] Create privileged ServiceAccount in ${KUBE_SYS_NS} and grant cluster-admin (simulated escalation)"
kubectl -n "$KUBE_SYS_NS" get sa "$SA_NAME" >/dev/null 2>&1 || \
		kubectl -n "$KUBE_SYS_NS" create sa "$SA_NAME"

kubectl get clusterrolebinding "$CRB_NAME" >/dev/null 2>&1 || \
		kubectl create clusterrolebinding "$CRB_NAME" \
				--clusterrole=cluster-admin \
				--serviceaccount="${KUBE_SYS_NS}:${SA_NAME}" \
				--dry-run=client -o yaml | kubectl apply -f -

# NOTE: Pods can only reference ServiceAccounts that exist in the same namespace.
# To simulate a cross-namespace pivot we create an SA in the target namespace as
# well and bind it to cluster-admin. This models the attacker either creating
# a privileged SA in the target namespace (via API) or copying permissions there.
CRB_TGT_NAME="${CRB_NAME}-${TGT_NS}"
kubectl -n "$TGT_NS" get sa "$SA_NAME" >/dev/null 2>&1 || \
  kubectl -n "$TGT_NS" create sa "$SA_NAME"
kubectl get clusterrolebinding "$CRB_TGT_NAME" >/dev/null 2>&1 || \
  kubectl create clusterrolebinding "$CRB_TGT_NAME" \
    --clusterrole=cluster-admin \
    --serviceaccount="${TGT_NS}:${SA_NAME}" \
    --dry-run=client -o yaml | kubectl apply -f -

echo "[Step 3] Ensure there is a compromised app Pod in ${SRC_NS} (initial foothold)"
kubectl -n "$SRC_NS" get pod "$COMP_POD_NAME" >/dev/null 2>&1 || cat <<EOF | kubectl -n "$SRC_NS" apply -f -
apiVersion: v1
kind: Pod
metadata:
  name: ${COMP_POD_NAME}
  labels:
    app: compromised
spec:
  containers:
  - name: sleeper
    image: busybox
    command: ["/bin/sh","-c","sleep 3600"]
  # uses default service account to represent original compromised workload
EOF

echo "[Step 4] Simulate lateral pivot: create a new Pod in ${TGT_NS} authenticated as ${SA_NAME}"
kubectl -n "$TGT_NS" get pod "$PIVOT_POD_NAME" >/dev/null 2>&1 || cat <<EOF | kubectl -n "$TGT_NS" apply -f -
apiVersion: v1
kind: Pod
metadata:
  name: ${PIVOT_POD_NAME}
  labels:
    app: pivot
    attacker: "true"
spec:
  serviceAccountName: ${SA_NAME}
  containers:
  - name: pivot
    image: busybox
    command: ["/bin/sh","-c","sleep 3600"]
EOF

echo "[Optional Step 5] Create a Service in ${TGT_NS} to function as a bridge (annotations indicate cross-ns intent)"
kubectl -n "$TGT_NS" get svc "$BRIDGE_SVC_NAME" >/dev/null 2>&1 || cat <<EOF | kubectl -n "$TGT_NS" apply -f -
apiVersion: v1
kind: Service
metadata:
  name: ${BRIDGE_SVC_NAME}
  annotations:
    kubeforensys/simulated-cross-namespace: "true"
spec:
  selector:
    app: pivot
  ports:
  - port: 8080
    targetPort: 8080
EOF

echo "Sleeping ${INTERVAL_SEC}s to allow collector to ingest the new Pod->SA and Pod->Namespace edges..."
sleep "$INTERVAL_SEC"

echo "=== Revised Attack1 finished ==="
echo "What changed in the graph (examples of edges your collector should emit):"
echo " - Pod ${COMP_POD_NAME} AUTHENTICATED_AS default (original foothold)"
echo " - ${PIVOT_POD_NAME} AUTHENTICATED_AS ${SA_NAME} (new pivot pod in ${TGT_NS})"
echo " - ${PIVOT_POD_NAME} IN_NAMESPACE ${TGT_NS}"
echo " - ClusterRoleBinding ${CRB_NAME} binds ${SA_NAME} to cluster-admin (GRANTED edge)"
echo "Detection triggers to map to root cause (remember SA->Namespace is only via Pods):"
echo " - Betweenness pivoting: spike will be attributable to the pivot pod(s) and the SA only via their pods"
echo " - Closeness influence: pivot pod closeness increases as it shortens paths across namespaces"
echo " - RBAC PageRank: SA PageRank increases after the CRB is created (authority change)"
echo " - Community changes: if your collector infers communicates_with edges (traffic) or SELECTS links, communities may merge"

echo "Tip: To fully demonstrate cross-namespace communication, you can (optionally) exec into ${PIVOT_POD_NAME} and curl services/pods in ${SRC_NS} to create communicates_with edges."

