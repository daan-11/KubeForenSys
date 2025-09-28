#!/bin/bash
set -euo pipefail

RESOURCE_GROUP="RP-daan"
AKS_CLUSTER="myAKSCluster"
VENV_PATH="/home/derksen/Documents/KubeForenSys/venv"

echo "Getting AKS credentials (before starting)..."
az aks get-credentials -g $RESOURCE_GROUP -n $AKS_CLUSTER --overwrite-existing || true

echo "Starting AKS cluster: $AKS_CLUSTER..."
az aks start -g $RESOURCE_GROUP -n $AKS_CLUSTER

echo "Waiting for cluster to be ready..."
az aks wait -g $RESOURCE_GROUP -n $AKS_CLUSTER --created

echo "Deploying Neo4j VM..."
bash deploy_neo4j_vm.sh

echo "Activating virtual environment..."
source "$VENV_PATH/bin/activate"

echo "Running kubeforensys.py with --initial..."
python3 kubeforensys.py --initial

echo "Cluster started and script executed."