param location string
param VNET_NAME string
param VNET_CIDR string
param ACA_SUBNET_CIDR string
param PE_SUBNET_CIDR string

resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' = {
  name: VNET_NAME
  location: location
  properties: {
    addressSpace: {
      addressPrefixes: [VNET_CIDR]
    }
    subnets: [
      {
        name: 'snet-aca'
        properties: {
          addressPrefix: ACA_SUBNET_CIDR
          delegations: [
            {
              name: 'aca-delegation'
              properties: {
                serviceName: 'Microsoft.App/environments'
              }
            }
          ]
        }
      }
      {
        name: 'snet-private-endpoints'
        properties: {
          addressPrefix: PE_SUBNET_CIDR
        }
      }
    ]
  }
}

output acaSubnetId string = vnet.properties.subnets[0].id
output peSubnetId string = vnet.properties.subnets[1].id
