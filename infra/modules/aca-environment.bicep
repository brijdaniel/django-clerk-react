param location string
param ENVIRONMENT_NAME string
param infrastructureSubnetId string = '' // Empty = default networking (dev). Set to subnet ID for VNet (prod).

resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2025-02-01' = {
  name: 'onereach-logs-${ENVIRONMENT_NAME}'
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

resource env 'Microsoft.App/managedEnvironments@2025-01-01' = {
  name: 'onereach-${ENVIRONMENT_NAME}'
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
  }
}

output environmentId string = env.id
