using './main.bicep'

param ENVIRONMENT_NAME = 'dev'
param ACR_NAME = '1reachcr'

// Scaling (dev: scale to zero when idle, max 1 replica)
param API_MIN_REPLICAS = 0
param API_MAX_REPLICAS = 1
param WORKER_MIN_REPLICAS = 0
param WORKER_MAX_REPLICAS = 1

// Resources (dev: minimal)
param API_CPU = '0.25'
param API_MEMORY = '0.5Gi'
param WORKER_CPU = '0.25'
param WORKER_MEMORY = '0.5Gi'
param BEAT_CPU = '0.25'
param BEAT_MEMORY = '0.5Gi'

// Non-secret config — fill in your dev values
param POSTGRES_HOST = '<server>.postgres.database.azure.com'
param POSTGRES_DB = '<db-name>'
param POSTGRES_USER = '<user>'
param ALLOWED_HOSTS = '*'
param CORS_ALLOWED_ORIGINS = 'https://<dev-swa>.azurestaticapps.net'
param CLERK_FRONTEND_API = '<clerk-url>'
param CLERK_AUTHORIZED_PARTIES = 'https://<dev-swa>.azurestaticapps.net'
param STORAGE_ACCOUNT_NAME = '<account>'
param STORAGE_CONTAINER = 'media-dev'

// Secrets are NOT in this file — they come from infra/.env.dev via deploy.sh
