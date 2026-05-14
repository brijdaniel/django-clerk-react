// 1Reach v2 — Azure Container Apps infrastructure
// Provisions: ACR, ACA Environment, 3 container apps (API, worker, beat), managed identity
//
// Usage:
//   ./deploy.sh deploy dev      — provision/update dev
//   ./deploy.sh deploy prod     — provision/update prod
//   ./deploy.sh preview dev     — dry-run preview

targetScope = 'resourceGroup'

// --- Environment ---
param ENVIRONMENT_NAME string // 'dev' or 'prod'
param location string = resourceGroup().location
param ACR_NAME string
param IMAGE_NAME string = '' // Empty on first deploy → uses placeholder image

// --- Scaling ---
param API_MIN_REPLICAS int
param API_MAX_REPLICAS int
param WORKER_MIN_REPLICAS int
param WORKER_MAX_REPLICAS int

// --- Resources (environment-dependent) ---
param API_CPU string
param API_MEMORY string
param WORKER_CPU string
param WORKER_MEMORY string
param BEAT_CPU string
param BEAT_MEMORY string

// --- Secrets (values come from infra/.env.dev or .env.prod via deploy.sh) ---
@secure()
param DJANGO_SECRET_KEY string
@secure()
param POSTGRES_PASSWORD string
@secure()
param CLERK_SECRET_KEY string
@secure()
param CLERK_WEBHOOK_SIGNING_SECRET string
@secure()
param STRIPE_SECRET_KEY string
@secure()
param STRIPE_WEBHOOK_SECRET string
@secure()
param CELERY_BROKER_URL string
@secure()
param STORAGE_ACCOUNT_KEY string

// --- Non-secret config ---
param POSTGRES_HOST string
param POSTGRES_DB string
param POSTGRES_USER string
param ALLOWED_HOSTS string
param CORS_ALLOWED_ORIGINS string
param CLERK_FRONTEND_API string
param CLERK_AUTHORIZED_PARTIES string
param STORAGE_ACCOUNT_NAME string
param STORAGE_CONTAINER string

// ============================================================================
// Modules
// ============================================================================

module identity 'modules/identity.bicep' = {
  name: 'identity'
  params: {
    location: location
    ENVIRONMENT_NAME: ENVIRONMENT_NAME
  }
}

module acr 'modules/acr.bicep' = {
  name: 'acr'
  params: {
    ACR_NAME: ACR_NAME
    location: location
    principalId: identity.outputs.principalId
  }
}

module logAnalytics 'modules/log-analytics.bicep' = {
  name: 'log-analytics'
  params: {
    location: location
    ENVIRONMENT_NAME: ENVIRONMENT_NAME
  }
}

module acaEnv 'modules/aca-environment.bicep' = {
  name: 'aca-environment'
  params: {
    location: location
    ENVIRONMENT_NAME: ENVIRONMENT_NAME
    logAnalyticsCustomerId: logAnalytics.outputs.customerId
    logAnalyticsSharedKey: logAnalytics.outputs.sharedKey
  }
}

// ============================================================================
// Shared configuration for all 3 container apps
// ============================================================================

// ACA secrets — sensitive values stored securely, referenced by env vars via secretRef
var secrets = [
  { name: 'django-secret-key', value: DJANGO_SECRET_KEY }
  { name: 'postgres-password', value: POSTGRES_PASSWORD }
  { name: 'clerk-secret-key', value: CLERK_SECRET_KEY }
  { name: 'clerk-webhook-signing-secret', value: CLERK_WEBHOOK_SIGNING_SECRET }
  { name: 'stripe-secret-key', value: STRIPE_SECRET_KEY }
  { name: 'stripe-webhook-secret', value: STRIPE_WEBHOOK_SECRET }
  { name: 'celery-broker-url', value: CELERY_BROKER_URL }
  { name: 'storage-account-key', value: STORAGE_ACCOUNT_KEY }
]

// Environment variables shared by API, worker, and beat
var sharedEnv = [
  // Secrets (referenced by name)
  { name: 'DJANGO_SECRET_KEY', secretRef: 'django-secret-key' }
  { name: 'POSTGRES_PASSWORD', secretRef: 'postgres-password' }
  { name: 'CELERY_BROKER_URL', secretRef: 'celery-broker-url' }
  { name: 'CELERY_RESULT_BACKEND', secretRef: 'celery-broker-url' }
  { name: 'CLERK_SECRET_KEY', secretRef: 'clerk-secret-key' }
  { name: 'CLERK_WEBHOOK_SIGNING_SECRET', secretRef: 'clerk-webhook-signing-secret' }
  { name: 'STRIPE_SECRET_KEY', secretRef: 'stripe-secret-key' }
  { name: 'STRIPE_WEBHOOK_SECRET', secretRef: 'stripe-webhook-secret' }
  { name: 'AZURE_STORAGE_ACCOUNT_KEY', secretRef: 'storage-account-key' }

  // Database
  { name: 'POSTGRES_HOST', value: POSTGRES_HOST }
  { name: 'POSTGRES_DB', value: POSTGRES_DB }
  { name: 'POSTGRES_USER', value: POSTGRES_USER }
  { name: 'POSTGRES_PORT', value: '5432' }

  // Clerk
  { name: 'CLERK_FRONTEND_API', value: CLERK_FRONTEND_API }
  { name: 'CLERK_AUTHORIZED_PARTIES', value: CLERK_AUTHORIZED_PARTIES }

  // Networking
  { name: 'ALLOWED_HOSTS', value: ALLOWED_HOSTS }
  { name: 'CORS_ALLOWED_ORIGINS', value: CORS_ALLOWED_ORIGINS }

  // Storage
  { name: 'STORAGE_PROVIDER_CLASS', value: 'app.utils.storage.AzureBlobStorageProvider' }
  { name: 'AZURE_STORAGE_ACCOUNT_NAME', value: STORAGE_ACCOUNT_NAME }
  { name: 'AZURE_CONTAINER', value: STORAGE_CONTAINER }

  // Django settings
  { name: 'DEBUG', value: '0' }
  { name: 'DB_POOL', value: 'true' }
  { name: 'LOG_FORMAT', value: 'json' }
  { name: 'LOG_LEVEL', value: 'INFO' }
  { name: 'SESSION_COOKIE_SECURE', value: 'True' }
  { name: 'CSRF_COOKIE_SECURE', value: 'True' }
  { name: 'SECURE_HSTS_SECONDS', value: '31536000' }
]

// Use placeholder image on first deploy (ACR is empty until CI pushes a real image)
var containerImage = !empty(IMAGE_NAME) ? IMAGE_NAME : 'mcr.microsoft.com/k8se/quickstart:latest'

// ============================================================================
// Container Apps
// ============================================================================

module api 'modules/container-app.bicep' = {
  name: 'api'
  params: {
    appName: '1reach-api-${ENVIRONMENT_NAME}'
    location: location
    environmentId: acaEnv.outputs.environmentId
    identityId: identity.outputs.identityId
    acrLoginServer: acr.outputs.loginServer
    image: containerImage
    cpu: API_CPU
    memory: API_MEMORY
    minReplicas: API_MIN_REPLICAS
    maxReplicas: API_MAX_REPLICAS
    ingressEnabled: true
    ingressExternal: true
    targetPort: 8000
    secrets: secrets
    env: union(sharedEnv, [
      { name: 'CONTAINER_ROLE', value: 'api' }
      { name: 'DB_POOL_MIN_SIZE', value: '2' }
      { name: 'DB_POOL_MAX_SIZE', value: '8' }
    ])
    healthProbePath: '/api/health/'
  }
}

module worker 'modules/container-app.bicep' = {
  name: 'worker'
  params: {
    appName: '1reach-worker-${ENVIRONMENT_NAME}'
    location: location
    environmentId: acaEnv.outputs.environmentId
    identityId: identity.outputs.identityId
    acrLoginServer: acr.outputs.loginServer
    image: containerImage
    cpu: WORKER_CPU
    memory: WORKER_MEMORY
    minReplicas: WORKER_MIN_REPLICAS
    maxReplicas: WORKER_MAX_REPLICAS
    ingressEnabled: false
    secrets: secrets
    env: union(sharedEnv, [
      { name: 'CONTAINER_ROLE', value: 'worker' }
      { name: 'DB_POOL_MIN_SIZE', value: '1' }
      { name: 'DB_POOL_MAX_SIZE', value: '4' }
    ])
  }
}

module beat 'modules/container-app.bicep' = {
  name: 'beat'
  params: {
    appName: '1reach-beat-${ENVIRONMENT_NAME}'
    location: location
    environmentId: acaEnv.outputs.environmentId
    identityId: identity.outputs.identityId
    acrLoginServer: acr.outputs.loginServer
    image: containerImage
    cpu: BEAT_CPU
    memory: BEAT_MEMORY
    minReplicas: 1 // beat must always run
    maxReplicas: 1 // singleton — only one beat instance allowed
    ingressEnabled: false
    secrets: secrets
    env: union(sharedEnv, [
      { name: 'CONTAINER_ROLE', value: 'beat' }
      { name: 'DB_POOL_MIN_SIZE', value: '1' }
      { name: 'DB_POOL_MAX_SIZE', value: '2' }
    ])
  }
}

// ============================================================================
// Outputs
// ============================================================================

output apiUrl string = api.outputs.fqdn
output acrLoginServer string = acr.outputs.loginServer
