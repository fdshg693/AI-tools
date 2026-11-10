#!/usr/bin/env bash
# Local Azure helpers for ai-logs Blob archive. Invoked from the justfile.
# Does not use the skills-site SWA resource group (rg-ai-skill-catalog).
set -euo pipefail

usage() {
  echo "usage: $0 provision <rg> <account> <container> <location>" >&2
  echo "       $0 env <rg> <container> <ssh_key> <tf_dir>" >&2
  exit 2
}

cmd="${1:-}"
shift || true

case "$cmd" in
  provision)
    [ "$#" -eq 4 ] || usage
    RG="$1"
    ACCOUNT="$2"
    CONTAINER="$3"
    LOCATION="$4"
    echo "Using resource group $RG in $LOCATION (not rg-ai-skill-catalog)"
    az group create --name "$RG" --location "$LOCATION" --tags application=ai-logs managedBy=az-cli
    EXISTING="$(az storage account list --resource-group "$RG" --query "[0].name" -o tsv)"
    if [ -n "$EXISTING" ]; then
      ACCOUNT="$EXISTING"
      echo "Reusing storage account $ACCOUNT in $RG"
    else
      AVAIL="$(az storage account check-name --name "$ACCOUNT" --query nameAvailable -o tsv)"
      if [ "$AVAIL" != "true" ]; then
        ACCOUNT="stailogs$(openssl rand -hex 4)"
        echo "Default account name is taken; using $ACCOUNT"
      fi
      az storage account create \
        --name "$ACCOUNT" \
        --resource-group "$RG" \
        --location "$LOCATION" \
        --sku Standard_LRS \
        --kind StorageV2 \
        --access-tier Cool \
        --min-tls-version TLS1_2 \
        --allow-blob-public-access false \
        --tags application=ai-logs managedBy=az-cli
    fi
    az storage container create --account-name "$ACCOUNT" --name "$CONTAINER" --auth-mode login
    echo "Done. account=$ACCOUNT container=$CONTAINER"
    echo "Next: just archive-env"
    ;;
  env)
    [ "$#" -eq 4 ] || usage
    RG="$1"
    CONTAINER="$2"
    SSH_KEY="$3"
    TF_DIR="$4"
    ACCOUNT="$(az storage account list --resource-group "$RG" --query "[0].name" -o tsv)"
    if [ -z "$ACCOUNT" ]; then
      echo "error: no storage account in $RG (run just archive-provision first)" >&2
      exit 1
    fi
    CONN="$(az storage account show-connection-string --name "$ACCOUNT" --resource-group "$RG" -o tsv)"
    SNAP="$(mktemp)"
    cleanup() { rm -f "$SNAP"; }
    trap cleanup EXIT
    umask 077
    printf 'AZURE_STORAGE_CONNECTION_STRING=%s\nAZURE_STORAGE_CONTAINER=%s\n' "$CONN" "$CONTAINER" > "$SNAP"
    IP="$(terraform -chdir="$TF_DIR" output -raw server_ip_address)"
    scp -i "$SSH_KEY" "$SNAP" root@"$IP":/tmp/ai-logs-archive.env
    ssh -i "$SSH_KEY" root@"$IP" 'set -euo pipefail
      if [ ! -f /opt/ai-logs/.env ]; then
        echo "error: /opt/ai-logs/.env is missing (run just vm-env first)" >&2
        exit 1
      fi
      grep -vE "^(AZURE_STORAGE_CONNECTION_STRING|AZURE_STORAGE_CONTAINER)=" /opt/ai-logs/.env > /opt/ai-logs/.env.new
      cat /tmp/ai-logs-archive.env >> /opt/ai-logs/.env.new
      mv /opt/ai-logs/.env.new /opt/ai-logs/.env
      rm -f /tmp/ai-logs-archive.env
      echo "Updated /opt/ai-logs/.env with Azure Blob settings."
    '
    if [ -f .env ]; then
      grep -vE "^(AZURE_STORAGE_CONNECTION_STRING|AZURE_STORAGE_CONTAINER)=" .env > .env.new
      cat "$SNAP" >> .env.new
      mv .env.new .env
      echo "Updated local .env with Azure Blob settings."
    else
      echo "Local .env is missing; copy .env.example to .env and re-run, or paste the two Azure keys yourself."
    fi
    ;;
  *)
    usage
    ;;
esac
