#!/bin/bash
# Deploy 1Reach infrastructure via Bicep.
#
# Usage:
#   ./infra/deploy.sh deploy dev     — provision/update dev infrastructure
#   ./infra/deploy.sh deploy prod    — provision/update prod infrastructure
#   ./infra/deploy.sh preview dev    — preview dev changes without applying
#   ./infra/deploy.sh preview prod   — preview prod changes without applying
#
# All config (infrastructure + secrets + app vars) lives in infra/.env.<env>.
# One file per environment. deploy.sh passes everything to Bicep as parameters.

set -e

ACTION="${1:?Usage: deploy.sh <deploy|preview> <dev|prod>}"
ENV="${2:?Usage: deploy.sh <deploy|preview> <dev|prod>}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/.env.${ENV}"
TEMPLATE_FILE="${SCRIPT_DIR}/main.bicep"

[ -f "$ENV_FILE" ] || { echo "Error: $ENV_FILE not found. Copy from .env.example and fill in values."; exit 1; }
[ -f "$TEMPLATE_FILE" ] || { echo "Error: $TEMPLATE_FILE not found."; exit 1; }

# Read RESOURCE_GROUP and build Bicep params from the .env file
RESOURCE_GROUP=""
PARAMS=""
while IFS='=' read -r key value; do
  # Skip comments and blank lines
  [[ "$key" =~ ^[[:space:]]*#.*$ || -z "$key" ]] && continue
  key=$(echo "$key" | xargs)
  value=$(echo "$value" | xargs)
  if [ "$key" = "RESOURCE_GROUP" ]; then
    RESOURCE_GROUP="$value"
  else
    PARAMS="$PARAMS $key=$value"
  fi
done < "$ENV_FILE"

[ -n "$RESOURCE_GROUP" ] || { echo "Error: RESOURCE_GROUP not set in $ENV_FILE"; exit 1; }

echo "Environment: $ENV"
echo "Resource group: $RESOURCE_GROUP"
echo "Action: $ACTION"
echo "Template: $TEMPLATE_FILE"
echo "Config from: $ENV_FILE"
echo ""

if [ "$ACTION" = "preview" ]; then
  echo "Running what-if preview (no changes will be applied)..."
  az deployment group create \
    --resource-group "$RESOURCE_GROUP" \
    --template-file "$TEMPLATE_FILE" \
    --parameters $PARAMS \
    --what-if
elif [ "$ACTION" = "deploy" ]; then
  az deployment group create \
    --resource-group "$RESOURCE_GROUP" \
    --template-file "$TEMPLATE_FILE" \
    --parameters $PARAMS
else
  echo "Error: Unknown action '$ACTION'. Use 'deploy' or 'preview'."
  exit 1
fi
