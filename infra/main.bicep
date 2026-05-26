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
param CREATE_ACR string // 'true' to create ACR, 'false' to reuse existing
param ACR_LOGIN_SERVER string // Used when CREATE_ACR=false (e.g. '1reachcr.azurecr.io')
param IMAGE_NAME string = '' // Empty on first deploy → uses placeholder image

// --- VNet (prod only) ---
param USE_VNET string // 'true' for prod (VNet + private endpoints), 'false' for dev
param VNET_NAME string
param VNET_CIDR string
param ACA_SUBNET_CIDR string
param PE_SUBNET_CIDR string

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

// --- App config (all values come from infra/.env.<env> via deploy.sh) ---

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
param AZURE_STORAGE_ACCOUNT_KEY string
@secure()
param WELCORP_PASSWORD string
@secure()
param WELCORP_CALLBACK_SECRET string
param POSTGRES_HOST string
param POSTGRES_DB string
param POSTGRES_USER string
param CLERK_FRONTEND_API string
param CLERK_AUTHORIZED_PARTIES string
param ALLOWED_HOSTS string
param CORS_ALLOWED_ORIGINS string
param AZURE_STORAGE_ACCOUNT_NAME string
param AZURE_CONTAINER string
param STORAGE_PROVIDER_CLASS string
param SMS_PROVIDER_CLASS string
param WELCORP_BASE_URL string
param WELCORP_USERNAME string
param BASE_URL string
param SENTRY_DSN string
param SENTRY_ENVIRONMENT string
param FREE_CREDIT_AMOUNT string
param SMS_RATE string
param MMS_RATE string
param DEBUG string
param TEST string
param SKIP_AUTO_MIGRATE string = 'false'

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

module acr 'modules/acr.bicep' = if (CREATE_ACR == 'true') {
  name: 'acr'
  params: {
    ACR_NAME: ACR_NAME
    location: location
    principalId: identity.outputs.principalId
  }
}

var acrServer = CREATE_ACR == 'true' ? acr.outputs.loginServer : ACR_LOGIN_SERVER

module vnet 'modules/vnet.bicep' = if (USE_VNET == 'true') {
  name: 'vnet'
  params: {
    location: location
    VNET_NAME: VNET_NAME
    VNET_CIDR: VNET_CIDR
    ACA_SUBNET_CIDR: ACA_SUBNET_CIDR
    PE_SUBNET_CIDR: PE_SUBNET_CIDR
  }
}

module acaEnv 'modules/aca-environment.bicep' = {
  name: 'aca-environment'
  params: {
    location: location
    ENVIRONMENT_NAME: ENVIRONMENT_NAME
    infrastructureSubnetId: USE_VNET == 'true' ? vnet.outputs.acaSubnetId : ''
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
  { name: 'azure-storage-account-key', value: AZURE_STORAGE_ACCOUNT_KEY }
  { name: 'welcorp-password', value: WELCORP_PASSWORD }
  { name: 'welcorp-callback-secret', value: WELCORP_CALLBACK_SECRET }
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
  { name: 'AZURE_STORAGE_ACCOUNT_KEY', secretRef: 'azure-storage-account-key' }
  { name: 'WELCORP_PASSWORD', secretRef: 'welcorp-password' }
  { name: 'WELCORP_CALLBACK_SECRET', secretRef: 'welcorp-callback-secret' }

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
  { name: 'STORAGE_PROVIDER_CLASS', value: STORAGE_PROVIDER_CLASS }
  { name: 'AZURE_STORAGE_ACCOUNT_NAME', value: AZURE_STORAGE_ACCOUNT_NAME }
  { name: 'AZURE_CONTAINER', value: AZURE_CONTAINER }

  // SMS provider
  { name: 'SMS_PROVIDER_CLASS', value: SMS_PROVIDER_CLASS }
  { name: 'WELCORP_BASE_URL', value: WELCORP_BASE_URL }
  { name: 'WELCORP_USERNAME', value: WELCORP_USERNAME }
  { name: 'BASE_URL', value: BASE_URL }

  // Monitoring
  { name: 'SENTRY_DSN', value: SENTRY_DSN }
  { name: 'SENTRY_ENVIRONMENT', value: SENTRY_ENVIRONMENT }

  // Billing
  { name: 'FREE_CREDIT_AMOUNT', value: FREE_CREDIT_AMOUNT }
  { name: 'SMS_RATE', value: SMS_RATE }
  { name: 'MMS_RATE', value: MMS_RATE }

  // Django settings
  { name: 'DEBUG', value: DEBUG }
  { name: 'TEST', value: TEST }
  { name: 'DB_POOL', value: 'true' }
  { name: 'LOG_FORMAT', value: 'json' }
  { name: 'LOG_LEVEL', value: 'INFO' }
  { name: 'SESSION_COOKIE_SECURE', value: 'True' }
  { name: 'CSRF_COOKIE_SECURE', value: 'True' }
  { name: 'SECURE_HSTS_SECONDS', value: '31536000' }
  { name: 'SKIP_AUTO_MIGRATE', value: SKIP_AUTO_MIGRATE }
]

// Use placeholder image on first deploy (ACR is empty until CI pushes a real image)
var containerImage = !empty(IMAGE_NAME) ? IMAGE_NAME : 'mcr.microsoft.com/k8se/quickstart:latest'
// Skip health probes when using placeholder image (it listens on port 80, not 8000)
var apiHealthProbe = !empty(IMAGE_NAME) ? '/api/health/' : ''

// ============================================================================
// Container Apps
// ============================================================================

module api 'modules/container-app.bicep' = {
  name: 'api'
  params: {
    appName: 'onereach-api-${ENVIRONMENT_NAME}'
    location: location
    environmentId: acaEnv.outputs.environmentId
    identityId: identity.outputs.identityId
    acrLoginServer: acrServer
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
    healthProbePath: apiHealthProbe
  }
}

module worker 'modules/container-app.bicep' = {
  name: 'worker'
  params: {
    appName: 'onereach-worker-${ENVIRONMENT_NAME}'
    location: location
    environmentId: acaEnv.outputs.environmentId
    identityId: identity.outputs.identityId
    acrLoginServer: acrServer
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
    appName: 'onereach-beat-${ENVIRONMENT_NAME}'
    location: location
    environmentId: acaEnv.outputs.environmentId
    identityId: identity.outputs.identityId
    acrLoginServer: acrServer
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
output acrLoginServer string = acrServer
