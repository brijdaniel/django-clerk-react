#!/bin/bash
# Deploy 1Reach infrastructure via Bicep.
#
# Usage:
#   ./infra/deploy.sh deploy dev     — provision/update dev infrastructure
#   ./infra/deploy.sh deploy prod    — provision/update prod infrastructure
#   ./infra/deploy.sh preview dev    — preview dev changes without applying
#   ./infra/deploy.sh preview prod   — preview prod changes without applying
#
# Secrets are loaded from infra/.env.<env> (gitignored).
# Same UPPER_SNAKE_CASE names as GitHub secrets — one list, zero conversion.

set -e

ACTION="${1:?Usage: deploy.sh <deploy|preview> <dev|prod>}"
ENV="${2:?Usage: deploy.sh <deploy|preview> <dev|prod>}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/.env.${ENV}"
PARAM_FILE="${SCRIPT_DIR}/main.${ENV}.bicepparam"

[ -f "$ENV_FILE" ] || { echo "Error: $ENV_FILE not found. Copy from .env.example and fill in values."; exit 1; }
[ -f "$PARAM_FILE" ] || { echo "Error: $PARAM_FILE not found."; exit 1; }

# Build --parameters args from every key=value line in the .env file
PARAMS=""
while IFS='=' read -r key value; do
  # Skip comments and blank lines
  [[ "$key" =~ ^[[:space:]]*#.*$ || -z "$key" ]] && continue
  key=$(echo "$key" | xargs)
  value=$(echo "$value" | xargs)
  PARAMS="$PARAMS $key=$value"
done < "$ENV_FILE"

echo "Environment: $ENV"
echo "Action: $ACTION"
echo "Param file: $PARAM_FILE"
echo "Secrets from: $ENV_FILE"
echo ""

if [ "$ACTION" = "preview" ]; then
  echo "Running what-if preview (no changes will be applied)..."
  az deployment group create \
    --resource-group "rg-1reach-${ENV}" \
    --parameters "$PARAM_FILE" \
    --parameters $PARAMS \
    --what-if
elif [ "$ACTION" = "deploy" ]; then
  az deployment group create \
    --resource-group "rg-1reach-${ENV}" \
    --parameters "$PARAM_FILE" \
    --parameters $PARAMS
else
  echo "Error: Unknown action '$ACTION'. Use 'deploy' or 'preview'."
  exit 1
fi
