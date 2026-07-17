param location string
param ENVIRONMENT_NAME string
param APP_NAME string = 'app'

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' = {
  name: '${APP_NAME}-identity-${ENVIRONMENT_NAME}'
  location: location
}

output principalId string = identity.properties.principalId
output identityId string = identity.id
