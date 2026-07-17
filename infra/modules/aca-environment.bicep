param location string
param ENVIRONMENT_NAME string
param APP_NAME string = 'app'
param infrastructureSubnetId string = '' // Empty = default networking (dev). Set to subnet ID for VNet (prod).

resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2025-02-01' = {
  name: '${APP_NAME}-logs-${ENVIRONMENT_NAME}'
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

resource env 'Microsoft.App/managedEnvironments@2025-01-01' = {
  name: '${APP_NAME}-${ENVIRONMENT_NAME}'
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalytics.properties.customerId
        #disable-next-line use-secure-value-for-secure-inputs
        sharedKey: logAnalytics.listKeys().primarySharedKey
      }
    }
    vnetConfiguration: !empty(infrastructureSubnetId) ? {
      infrastructureSubnetId: infrastructureSubnetId
      internal: false
    } : null
    // NOTE: zoneRedundant is intentionally not set — it can only be chosen
    // when an environment is first created (changing it forces recreation).
    // Revisit if the environment is ever rebuilt.
  }
}

output environmentId string = env.id
output defaultDomain string = env.properties.defaultDomain
