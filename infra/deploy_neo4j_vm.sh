#!/bin/bash
# Automated Azure VM creation and Neo4j setup from local machine

set -e

# Variables
RESOURCE_GROUP="RP-daan"
VM_NAME="neo4j-vm"
LOCATION="westeurope"
ADMIN_USER="azureuser"
VM_IMAGE="Ubuntu2204"
VM_SIZE="Standard_B2s"
SETUP_SCRIPT="setup_neo4j.sh"

# Ensure Azure CLI is logged in
az account show > /dev/null 2>&1 || az login

# Create VM
az vm create \
    --resource-group "$RESOURCE_GROUP" \
    --name "$VM_NAME" \
    --image "$VM_IMAGE" \
    --admin-username "$ADMIN_USER" \
    --generate-ssh-keys \
    --size "$VM_SIZE"

# Open Neo4j ports with different priorities to avoid NSG rule conflict
az vm open-port --port 7474 --resource-group "$RESOURCE_GROUP" --name "$VM_NAME" --priority 900
az vm open-port --port 7687 --resource-group "$RESOURCE_GROUP" --name "$VM_NAME" --priority 901

# Get public IP
VM_PUBLIC_IP=$(az vm show -d -g "$RESOURCE_GROUP" -n "$VM_NAME" --query publicIps -o tsv)
echo "VM Public IP: $VM_PUBLIC_IP"
ssh-keygen -f '/home/derksen/.ssh/known_hosts' -R "$VM_PUBLIC_IP"

# Wait for VM to boot
sleep 30

# Copy setup script to VM
scp "$SETUP_SCRIPT" "$ADMIN_USER@$VM_PUBLIC_IP:~"

# Run setup script remotely, passing public IP as argument
ssh "$ADMIN_USER@$VM_PUBLIC_IP" "bash ~/setup_neo4j.sh $VM_PUBLIC_IP"

echo "Neo4j setup complete. Access Neo4j Browser at http://$VM_PUBLIC_IP:7474"