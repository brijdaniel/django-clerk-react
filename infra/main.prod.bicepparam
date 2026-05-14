using './main.bicep'

param ENVIRONMENT_NAME = 'prod'
param ACR_NAME = '1reachcr'

// Scaling (prod: always-on, can scale up)
param API_MIN_REPLICAS = 1
param API_MAX_REPLICAS = 3
param WORKER_MIN_REPLICAS = 1
param WORKER_MAX_REPLICAS = 3

// Resources (prod: more headroom)
param API_CPU = '0.5'
param API_MEMORY = '1Gi'
param WORKER_CPU = '0.5'
param WORKER_MEMORY = '1Gi'
param BEAT_CPU = '0.25'
param BEAT_MEMORY = '0.5Gi'

// Non-secret config — fill in your production values
param POSTGRES_HOST = '<server>.postgres.database.azure.com'
param POSTGRES_DB = '<db-name>'
param POSTGRES_USER = '<user>'
param ALLOWED_HOSTS = '<api-app>.azurecontainerapps.io'
param CORS_ALLOWED_ORIGINS = 'https://<prod-swa>.azurestaticapps.net'
param CLERK_FRONTEND_API = '<clerk-url>'
param CLERK_AUTHORIZED_PARTIES = 'https://<prod-swa>.azurestaticapps.net'
param STORAGE_ACCOUNT_NAME = '<account>'
param STORAGE_CONTAINER = 'media'

// Secrets are NOT in this file — they come from infra/.env.prod via deploy.sh
