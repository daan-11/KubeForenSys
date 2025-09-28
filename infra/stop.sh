#!/bin/bash
set -euo pipefail

RESOURCE_GROUP="RP-daan"
AKS_CLUSTER="myAKSCluster"
LAW_NAME="KubeForenSys-LAW"
STATE_FILE="../kubeforensys_config.json"

echo "Deleting all Data Collection Rules (DCRs) in $RESOURCE_GROUP..."
for dcr in $(az monitor data-collection rule list -g $RESOURCE_GROUP --query "[].name" -o tsv); do
  az monitor data-collection rule delete -g $RESOURCE_GROUP -n $dcr --yes
done

echo "Deleting all Data Collection Endpoints (DCEs) in $RESOURCE_GROUP..."
for dce in $(az monitor data-collection endpoint list -g $RESOURCE_GROUP --query "[].name" -o tsv); do
  az monitor data-collection endpoint delete -g $RESOURCE_GROUP -n $dce --yes
done

echo "Deleting Log Analytics Workspace: $LAW_NAME..."
az monitor log-analytics workspace delete -g $RESOURCE_GROUP -n $LAW_NAME --yes --force

echo "Stopping AKS cluster: $AKS_CLUSTER..."
az aks stop -g $RESOURCE_GROUP -n $AKS_CLUSTER

echo "Waiting for AKS cluster to be fully stopped..."
while true; do
    state=$(az aks show -g $RESOURCE_GROUP -n $AKS_CLUSTER --query "powerState.code" -o tsv 2>/dev/null || echo "NotFound")
    if [[ "$state" == "Stopped" ]]; then
        echo "AKS cluster is fully stopped."
        break
    else
        echo "Current state: $state. Waiting..."
        sleep 10
    fi
done

echo "Deleting state file: $STATE_FILE..."
rm -f $STATE_FILE

VM_NAME="neo4j-vm"
echo "Deleting VM: $VM_NAME in $RESOURCE_GROUP..."
az vm delete --resource-group "$RESOURCE_GROUP" --name "$VM_NAME" --yes --force-deletion true

echo "Cleanup and stop completed."
