#!/usr/bin/env python3
import os
from pathlib import Path

BASE = Path(__file__).resolve().parent

NS_COUNT = 10
DEP_PER_NS = 6  # 10 * 6 = 60 deployments
SVC_PER_NS = 2  # 10 * 2 = 20 services
NP_PER_NS = 3   # 10 * 3 = 30 network policies
ROLES_PER_NS = 5  # 10 * 5 = 50 RBAC Roles

BASE.mkdir(parents=True, exist_ok=True)


def w(path: Path, content: str):
    path.write_text(content, encoding="utf-8")


def ns_name(i: int) -> str:
    return f"ns-{i:02d}"


def dep_name(ns_i: int, dep_i: int) -> str:
    return f"dep-{ns_i:02d}-{dep_i:02d}"


def app_label(ns_i: int, dep_i: int) -> str:
    return f"app-{ns_i:02d}-{dep_i:02d}"


def svc_name(ns_i: int, svc_i: int) -> str:
    return f"svc-{ns_i:02d}-{svc_i:02d}"


def role_name(ns_i: int, role_i: int) -> str:
    return f"role-{ns_i:02d}-{role_i:02d}"


# 1) Namespaces
for i in range(1, NS_COUNT + 1):
    ns = ns_name(i)
    yaml = f"""
apiVersion: v1
kind: Namespace
metadata:
  name: {ns}
""".lstrip()
    w(BASE / f"namespace-{ns}.yaml", yaml)

# 2) Deployments (nginx, one replica) -> 60 total
for ns_i in range(1, NS_COUNT + 1):
    ns = ns_name(ns_i)
    for d in range(1, DEP_PER_NS + 1):
        name = dep_name(ns_i, d)
        app = app_label(ns_i, d)
        yaml = f"""
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {name}
  namespace: {ns}
  labels:
    app: {app}
spec:
  replicas: 1
  selector:
    matchLabels:
      app: {app}
  template:
    metadata:
      labels:
        app: {app}
    spec:
      serviceAccountName: default
      containers:
      - name: nginx
        image: nginx:1.25
        ports:
        - containerPort: 80
""".lstrip()
        w(BASE / f"deployment-{ns}-{name}.yaml", yaml)

# 3) Services (2 per namespace selecting first two deployments)
for ns_i in range(1, NS_COUNT + 1):
    ns = ns_name(ns_i)
    for s in range(1, SVC_PER_NS + 1):
        name = svc_name(ns_i, s)
        app = app_label(ns_i, s)  # select dep 01 and 02
        yaml = f"""
apiVersion: v1
kind: Service
metadata:
  name: {name}
  namespace: {ns}
spec:
  selector:
    app: {app}
  ports:
  - protocol: TCP
    port: 80
    targetPort: 80
""".lstrip()
        w(BASE / f"service-{ns}-{name}.yaml", yaml)

# 4) NetworkPolicies (3 per namespace, non-empty rules to reflect ALLOWS)
for ns_i in range(1, NS_COUNT + 1):
    ns = ns_name(ns_i)
    app1 = app_label(ns_i, 1)
    app2 = app_label(ns_i, 2)

    # allow-same-namespace-ingress: allow ingress from any pod within same ns
    yaml1 = f"""
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: np-{ns}-allow-same-ns-ingress
  namespace: {ns}
spec:
  podSelector: {{}}  # all pods
  ingress:
  - from:
    - podSelector: {{}}  # same namespace
  egress:
  - to:
    - podSelector: {{}}  # same namespace (keeps rules non-empty)
""".lstrip()
    w(BASE / f"networkpolicy-{ns}-allow-same-ns-ingress.yaml", yaml1)

    # allow-kube-dns-egress: allow egress to kube-dns in kube-system namespace
    yaml2 = f"""
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: np-{ns}-allow-kube-dns-egress
  namespace: {ns}
spec:
  podSelector: {{}}  # all pods
  egress:
  - to:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: kube-system
      podSelector:
        matchLabels:
          k8s-app: kube-dns
    ports:
    - protocol: UDP
      port: 53
  policyTypes:
  - Egress
""".lstrip()
    w(BASE / f"networkpolicy-{ns}-allow-kube-dns-egress.yaml", yaml2)

    # allow-from-app1-to-app2 ingress
    yaml3 = f"""
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: np-{ns}-allow-from-{app1}-to-{app2}
  namespace: {ns}
spec:
  podSelector:
    matchLabels:
      app: {app2}
  ingress:
  - from:
    - podSelector:
        matchLabels:
          app: {app1}
  policyTypes:
  - Ingress
""".lstrip()
    w(BASE / f"networkpolicy-{ns}-allow-from-app1-to-app2.yaml", yaml3)

# 5) RBAC Roles (5 per namespace, one simple rule each) -> 50 total
RBAC_RULES = [
    ("", ["pods"], ["get"]),
    ("", ["configmaps"], ["list"]),
    ("", ["secrets"], ["get"]),
    ("apps", ["deployments"], ["watch"]),
    ("networking.k8s.io", ["networkpolicies"], ["get", "list"]),
]

for ns_i in range(1, NS_COUNT + 1):
    ns = ns_name(ns_i)
    for r in range(ROLES_PER_NS):
        api_group, resources, verbs = RBAC_RULES[r % len(RBAC_RULES)]
        name = role_name(ns_i, r + 1)
        # Build YAML for Role with a single rule entry
        api_group_entry = f"- \"{api_group}\"" if api_group else "- \"\""
        resources_entry = "\n    - ".join(resources)
        verbs_entry = "\n    - ".join(verbs)
        yaml = f"""
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: {name}
  namespace: {ns}
rules:
- apiGroups:
  {api_group_entry}
  resources:
  - {resources[0]}
  verbs:
  - {verbs[0]}
""".lstrip()
        w(BASE / f"role-{ns}-{name}.yaml", yaml)

print(f"Generated baseline manifests in {BASE}")
