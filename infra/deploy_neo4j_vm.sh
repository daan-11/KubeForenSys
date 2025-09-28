#!/bin/bash
# Automated Azure VM creation and Neo4j setup from local machine

set -e

RESOURCE_GROUP="RP-daan"
VM_NAME="neo4j-vm"
LOCATION="westeurope"
ADMIN_USER="azureuser"
VM_IMAGE="Ubuntu2204"
VM_SIZE="Standard_B2s"
SETUP_SCRIPT="setup_neo4j.sh"

az account show > /dev/null 2>&1 || az login
az vm create \
    --resource-group "$RESOURCE_GROUP" \
    --name "$VM_NAME" \
    --image "$VM_IMAGE" \
    --admin-username "$ADMIN_USER" \
    --generate-ssh-keys \
    --size "$VM_SIZE"

az vm open-port --port 7474 --resource-group "$RESOURCE_GROUP" --name "$VM_NAME" --priority 900
az vm open-port --port 7687 --resource-group "$RESOURCE_GROUP" --name "$VM_NAME" --priority 901

VM_PUBLIC_IP=$(az vm show -d -g "$RESOURCE_GROUP" -n "$VM_NAME" --query publicIps -o tsv)
echo "VM Public IP: $VM_PUBLIC_IP"
ssh-keygen -f '/home/derksen/.ssh/known_hosts' -R "$VM_PUBLIC_IP"

NEO4J_PASSWORD=$(tr -dc 'A-Za-z0-9' </dev/urandom | head -c 16)
echo "Generated Neo4j password: $NEO4J_PASSWORD"

cat > ../neo4j-credentials.json <<EOF
{
  "vm_public_ip": "$VM_PUBLIC_IP",
  "vm_admin_user": "$ADMIN_USER",
  "neo4j_username": "neo4j",
  "neo4j_password": "$NEO4J_PASSWORD"
}
EOF
echo "Credentials saved to neo4j-credentials.json"

sleep 30
scp "$SETUP_SCRIPT" "$ADMIN_USER@$VM_PUBLIC_IP:~"
ssh "$ADMIN_USER@$VM_PUBLIC_IP" "bash ~/setup_neo4j.sh $VM_PUBLIC_IP $NEO4J_PASSWORD"

echo "Neo4j setup complete. Access Neo4j Browser at http://$VM_PUBLIC_IP:7474"