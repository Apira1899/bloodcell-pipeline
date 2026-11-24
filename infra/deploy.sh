#!/usr/bin/env bash
# =====================================================================================
#  BloodCell pipeline – infrastructure (Azure CLI, run in Azure Cloud Shell – Bash)
#  Team bcellaj · ECE Paris · Distributed Systems and AI capstone
#
#  Run section by section (not blindly in one go): some steps wait for others
#  (Event Grid needs the deployed function, the API needs the GHCR image, etc.).
#  Owner of the subscription only: the role assignments cannot be done by Contributor.
#  No secret in this file: keys/connection strings are read at run time and stored
#  as Azure settings or secrets, never in Git.
# =====================================================================================
set -euo pipefail

# ---------- 0. Variables (Cloud Shell forgets them: paste again after each restart) ----------
EQ=bcellaj
LOC=francecentral                  # allowed by policy + Flex Consumption available
RG=rg-projet-$EQ
ST=st${EQ}pipe                     # storage: globally unique, lowercase, no hyphen
COSMOS=cosmos-$EQ
ENV=cae-$EQ
FUNC=func-$EQ
ID=id-github-$EQ
LAW=log-$EQ
AI=appi-$EQ
GH_OWNER=Apira1899                 # exact case, as on GitHub
GH_REPO=bloodcell-pipeline
IMAGE=ghcr.io/$(echo "$GH_OWNER" | tr '[:upper:]' '[:lower:]')/$GH_REPO/api:1.0.0
ALERT_EMAIL="apiramy.jeyaharan@edu.ece.fr"

# Avoid hidden (Y/n) prompts for CLI extensions in Cloud Shell
az config set extension.use_dynamic_install=yes_without_prompt extension.dynamic_install_allow_preview=true -o none

# ---------- 1. Region checks + providers (subject section 3.2) ----------
az policy assignment list --disable-scope-strict-match \
  --query "[?contains(displayName,'region') || contains(displayName,'location')].parameters" -o json
az functionapp list-flexconsumption-locations -o table
for p in Microsoft.Web Microsoft.App Microsoft.EventGrid Microsoft.DocumentDB \
         Microsoft.OperationalInsights Microsoft.Insights Microsoft.ManagedIdentity; do
  az provider register --namespace $p; done

# ---------- 2. Resource group (tags for cost tracking) ----------
az group create -n $RG -l $LOC --tags projet=dscc equipe=$EQ -o table

# ---------- 3. Cosmos DB FIRST (most often refused for capacity -> validates the region) ----------
az cosmosdb create -n $COSMOS -g $RG --enable-free-tier true \
  --locations regionName=$LOC failoverPriority=0 isZoneRedundant=False -o table
az cosmosdb sql database create -a $COSMOS -g $RG -n pipeline --throughput 400 -o table
az cosmosdb sql container create -a $COSMOS -g $RG -d pipeline -n inferences --partition-key-path /fileName -o table

# ---------- 4. Storage: containers, queues, versioning, static website ----------
az storage account create -n $ST -g $RG -l $LOC --sku Standard_LRS --kind StorageV2 \
  --min-tls-version TLS1_2 --allow-blob-public-access false -o table
az storage account blob-service-properties update -n $ST -g $RG --enable-versioning true -o none
for c in input output rejected models; do az storage container create --account-name $ST -n $c -o none; done
az storage queue create --account-name $ST -n inference-requests -o none
az storage queue create --account-name $ST -n inference-requests-poison -o none
az storage blob service-properties update --account-name $ST --static-website --index-document index.html -o none

# ---------- 5. Monitoring FIRST: capped workspace + workspace-based App Insights ----------
az monitor log-analytics workspace create -g $RG -n $LAW -l $LOC --quota 0.2 -o table
LAW_ID=$(az monitor log-analytics workspace show -g $RG -n $LAW --query id -o tsv)
az monitor app-insights component create --app $AI -g $RG -l $LOC --workspace $LAW_ID -o table

# ---------- 6. Container Apps: one environment, API scaling 0 -> 2 ----------
#  Prerequisite: ci.yml has pushed the image to GHCR and the package is PUBLIC.
az containerapp env create -n $ENV -g $RG -l $LOC \
  --logs-workspace-id "$(az monitor log-analytics workspace show -g $RG -n $LAW --query customerId -o tsv)" \
  --logs-workspace-key "$(az monitor log-analytics workspace get-shared-keys -g $RG -n $LAW --query primarySharedKey -o tsv)" \
  -o table
AI_CONN=$(az monitor app-insights component show --app $AI -g $RG --query connectionString -o tsv)
az containerapp create -n api-$EQ -g $RG --environment $ENV \
  --image $IMAGE --target-port 8000 --ingress external \
  --cpu 0.25 --memory 0.5Gi --min-replicas 0 --max-replicas 2 \
  --secrets appinsights-conn="$AI_CONN" \
  --env-vars APPLICATIONINSIGHTS_CONNECTION_STRING=secretref:appinsights-conn MODEL_VERSION=1.0.0 API_VERSION=1.0.0 \
  --query properties.configuration.ingress.fqdn -o tsv
API=https://$(az containerapp show -n api-$EQ -g $RG --query properties.configuration.ingress.fqdn -o tsv)

# Liveness + readiness probes on /health (not exposed as CLI flags -> PATCH the template)
az containerapp show -n api-$EQ -g $RG -o json > /tmp/app.json
jq '{properties:{template:(.properties.template
  | .containers[0].probes = [
      {type:"Liveness",  httpGet:{path:"/health",port:8000}, initialDelaySeconds:10, periodSeconds:30},
      {type:"Readiness", httpGet:{path:"/health",port:8000}, initialDelaySeconds:5,  periodSeconds:10}])}}' \
  /tmp/app.json > /tmp/patch.json
az rest --method patch --body @/tmp/patch.json -o none \
  --url "https://management.azure.com$(az containerapp show -n api-$EQ -g $RG --query id -o tsv)?api-version=2024-03-01"
curl -s $API/health; echo

# ---------- 7. Function App (Flex Consumption, Python 3.12, 512 MB) ----------
az functionapp create -n $FUNC -g $RG --storage-account $ST --app-insights $AI \
  --flexconsumption-location $LOC --runtime python --runtime-version 3.12 --instance-memory 512 -o table

# Identity-based access: role assignments made ONCE by the subscription owner
az functionapp identity assign -n $FUNC -g $RG -o none
PID=$(az functionapp identity show -n $FUNC -g $RG --query principalId -o tsv)
ST_ID=$(az storage account show -n $ST -g $RG --query id -o tsv)
for r in "Storage Blob Data Owner" "Storage Queue Data Contributor"; do
  az role assignment create --role "$r" --assignee-object-id $PID \
    --assignee-principal-type ServicePrincipal --scope $ST_ID -o none; done
# Cosmos DB data plane (Built-in Data Contributor) – not an Azure RBAC role
az cosmosdb sql role assignment create -a $COSMOS -g $RG --scope / --principal-id $PID \
  --role-definition-id 00000000-0000-0000-0000-000000000002 -o none

# Application settings (no keys: endpoints only, the identity does the auth)
az functionapp config appsettings set -n $FUNC -g $RG -o none --settings \
  STORAGE_ACCOUNT_URL=https://$ST.blob.core.windows.net \
  PIPELINE_STORAGE__queueServiceUri=https://$ST.queue.core.windows.net \
  PIPELINE_STORAGE__blobServiceUri=https://$ST.blob.core.windows.net \
  API_URL=$API \
  COSMOS_ENDPOINT=https://$COSMOS.documents.azure.com:443/ \
  COSMOS_DB=pipeline COSMOS_CONTAINER=inferences

# First code deployment (later deployments: deploy.yml)
cd ~ && rm -rf $GH_REPO && git clone -q https://github.com/$GH_OWNER/$GH_REPO.git
(cd $GH_REPO/functions && zip -qr ~/functions.zip . -x "tests/*" "*.pyc")
az functionapp deployment source config-zip -g $RG -n $FUNC --src ~/functions.zip --build-remote true
az functionapp function list -n $FUNC -g $RG --query "[].name" -o tsv

# ---------- 8. Event Grid -> dispatcher (only AFTER the function code is deployed) ----------
az eventgrid event-subscription create -n blob-to-dispatcher \
  --source-resource-id $ST_ID \
  --endpoint-type azurefunction \
  --endpoint "$(az functionapp show -n $FUNC -g $RG --query id -o tsv)/functions/dispatcher" \
  --included-event-types Microsoft.Storage.BlobCreated \
  --subject-begins-with /blobServices/default/containers/input/ -o table

# ---------- 9. Dashboard ($web) + CORS restricted to its origin ----------
az storage blob upload --account-name $ST -c '$web' -f ~/$GH_REPO/web/index.html -n index.html \
  --content-type "text/html" --overwrite -o none
WEB=$(az storage account show -n $ST -g $RG --query primaryEndpoints.web -o tsv); WEB=${WEB%/}
az functionapp cors add -n $FUNC -g $RG --allowed-origins $WEB -o table
echo "Dashboard: $WEB"

# ---------- 10. GitHub Actions -> Azure through OIDC (no secret, no Entra ID rights) ----------
az identity create -n $ID -g $RG -o none
# GitHub now sends a subject with immutable IDs: copy it from the azure/login log if needed
az identity federated-credential create -n github-production --identity-name $ID -g $RG \
  --issuer https://token.actions.githubusercontent.com \
  --subject "repo:$GH_OWNER/$GH_REPO:environment:production" \
  --audiences api://AzureADTokenExchange -o none
az identity federated-credential create -n github-production-ids --identity-name $ID -g $RG \
  --issuer https://token.actions.githubusercontent.com \
  --subject "repo:Apira1899@132703325/bloodcell-pipeline@1465266331:environment:production" \
  --audiences api://AzureADTokenExchange -o none
# Least privilege: Contributor on the resource group only (cannot assign roles)
az role assignment create --role Contributor \
  --assignee-object-id "$(az identity show -n $ID -g $RG --query principalId -o tsv)" \
  --assignee-principal-type ServicePrincipal \
  --scope "$(az group show -n $RG --query id -o tsv)" -o none
echo "GitHub secrets (identifiers, not passwords):"
echo "  AZURE_CLIENT_ID       = $(az identity show -n $ID -g $RG --query clientId -o tsv)"
echo "  AZURE_TENANT_ID       = $(az account show --query tenantId -o tsv)"
echo "  AZURE_SUBSCRIPTION_ID = $(az account show --query id -o tsv)"

# ---------- 11. Alert: > 3 HTTP errors in 15 min, e-mail (receiver must verify its address) ----------
az monitor action-group create -g $RG -n ag-$EQ --short-name $EQ --action email apira-email "$ALERT_EMAIL" -o none
AI_ID=$(az resource show -g $RG -n $AI --resource-type Microsoft.Insights/components --query id -o tsv)
AG_ID=$(az monitor action-group show -g $RG -n ag-$EQ --query id -o tsv)
az monitor scheduled-query create -g $RG -n alert-api-errors -l $LOC \
  --scopes $AI_ID \
  --condition "count 'Errors' > 3" \
  --condition-query Errors="requests | where toint(resultCode) >= 400" \
  --evaluation-frequency 15m --window-size 15m --severity 2 \
  --action-groups $AG_ID \
  --description "More than 3 HTTP errors (4xx/5xx) in 15 minutes" -o table

# ---------- 12. Budget ----------
#  Created in the portal: Budgets -> scope rg-projet-bcellaj -> budget-bcellaj, $25 monthly,
#  alerts on actual cost at 20 %, 50 %, 80 % -> e-mail.

# ---------- 13. Tests ----------
#  valid   : az storage blob upload --account-name $ST -c input -f docs/demo_images/neutrophil_0.png -n neutrophil_0.png
#  invalid : az storage blob upload --account-name $ST -c input -f bad.txt -n bad.txt          -> rejected/
#  poison  : az storage message put --account-name $ST -q inference-requests --content "bm90IGpzb24="  -> -poison queue
#  alert   : 10 x POST $API/predict with an invalid image -> HTTP 422 -> alert fires

# ---------- 14. Clean-up after the defence (within 48 h) ----------
#  az group delete -n $RG --yes
#  az group exists -n $RG          # -> false
#  az group list -o table          # no leftover DefaultResourceGroup-*
