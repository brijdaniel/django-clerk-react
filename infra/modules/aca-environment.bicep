param location string
param ENVIRONMENT_NAME string
param logAnalyticsCustomerId string
param logAnalyticsSharedKey string

resource env 'Microsoft.App/managedEnvironments@2025-01-01' = {
  name: '1reach-${ENVIRONMENT_NAME}'
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalyticsCustomerId
        sharedKey: logAnalyticsSharedKey
      }
    }
  }
}

output environmentId string = env.id
