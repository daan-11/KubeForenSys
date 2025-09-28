#!/bin/bash
# Neo4j setup script for Ubuntu VM

set -e

VM_PUBLIC_IP="$1"
NEO4J_VERSION="5"
NEO4J_PASSWORD=$(tr -dc 'A-Za-z0-9' </dev/urandom | head -c 16)
echo "$NEO4J_PASSWORD" > neo4j-password.txt
echo "Generated Neo4j password: $NEO4J_PASSWORD (also saved to neo4j-password.txt)"

wget -O - https://debian.neo4j.com/neotechnology.gpg.key | sudo gpg --dearmor -o /usr/share/keyrings/neo4j-archive-keyring.gpg
echo "deb [signed-by=/usr/share/keyrings/neo4j-archive-keyring.gpg] https://debian.neo4j.com stable $NEO4J_VERSION" | sudo tee /etc/apt/sources.list.d/neo4j.list

sudo apt update
sudo apt install neo4j -y

sudo sed -i '/^server.default_listen_address/d' /etc/neo4j/neo4j.conf
sudo sed -i '/^server.default_advertised_address/d' /etc/neo4j/neo4j.conf
echo "server.default_listen_address=0.0.0.0" | sudo tee -a /etc/neo4j/neo4j.conf
echo "server.default_advertised_address=${VM_PUBLIC_IP}" | sudo tee -a /etc/neo4j/neo4j.conf

sudo systemctl enable neo4j
sudo systemctl restart neo4j

sudo ufw allow 22/tcp
sudo ufw allow 7474/tcp
sudo ufw allow 7687/tcp
sudo ufw enable

sudo neo4j-admin dbms set-initial-password "$NEO4J_PASSWORD"
echo "Neo4j default username: neo4j"
echo "Neo4j password: $NEO4J_PASSWORD"

sudo systemctl restart neo4j
sudo systemctl status neo4j

