param ACR_NAME string
param location string
param principalId string

resource acr 'Microsoft.ContainerRegistry/registries@2025-04-01' = {
  name: ACR_NAME
  location: location
  sku: { name: 'Basic' }
  properties: { adminUserEnabled: false }
}

// AcrPull role assignment for the managed identity
var acrPullRoleId = '7f951dda-4ed3-4680-a7ca-43fe172d538d'
resource acrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(acr.id, principalId, acrPullRoleId)
  scope: acr
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPullRoleId)
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}

output loginServer string = acr.properties.loginServer
