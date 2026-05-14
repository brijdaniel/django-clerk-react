param location string
param ENVIRONMENT_NAME string

resource workspace 'Microsoft.OperationalInsights/workspaces@2025-02-01' = {
  name: '1reach-logs-${ENVIRONMENT_NAME}'
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

output workspaceId string = workspace.id
output customerId string = workspace.properties.customerId
output sharedKey string = listKeys(workspace.id, '2025-02-01').primarySharedKey
