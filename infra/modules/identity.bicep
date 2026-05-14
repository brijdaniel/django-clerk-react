param location string
param ENVIRONMENT_NAME string

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' = {
  name: '1reach-identity-${ENVIRONMENT_NAME}'
  location: location
}

output principalId string = identity.properties.principalId
output identityId string = identity.id
