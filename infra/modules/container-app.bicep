// Reusable container app module — used for API, worker, and beat.
// Ingress and health probes are conditional based on parameters.

param appName string
param location string
param environmentId string
param identityId string
param acrLoginServer string
param image string
param cpu string
param memory string
param minReplicas int
param maxReplicas int
param ingressEnabled bool
param ingressExternal bool = false
param targetPort int = 8000
param secrets array = []
param env array = []
param healthProbePath string = ''

resource app 'Microsoft.App/containerApps@2025-01-01' = {
  name: appName
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${identityId}': {}
    }
  }
  properties: {
    managedEnvironmentId: environmentId
    configuration: {
      activeRevisionsMode: 'Single'
      registries: [
        {
          server: acrLoginServer
          identity: identityId
        }
      ]
      secrets: secrets
      ingress: ingressEnabled ? {
        external: ingressExternal
        targetPort: targetPort
        transport: 'auto'
      } : null
    }
    template: {
      containers: [
        {
          name: appName
          image: image
          resources: {
            cpu: json(cpu)
            memory: memory
          }
          env: env
          probes: !empty(healthProbePath) ? [
            {
              type: 'Liveness'
              httpGet: { path: healthProbePath, port: targetPort }
              periodSeconds: 30
              failureThreshold: 3
            }
            {
              type: 'Readiness'
              httpGet: { path: healthProbePath, port: targetPort }
              periodSeconds: 10
              failureThreshold: 3
            }
            {
              type: 'Startup'
              httpGet: { path: healthProbePath, port: targetPort }
              periodSeconds: 5
              failureThreshold: 30 // 150s startup budget (DB wait loop)
            }
          ] : []
        }
      ]
      scale: {
        minReplicas: minReplicas
        maxReplicas: maxReplicas
      }
    }
  }
}

output fqdn string = ingressEnabled ? app.properties.configuration.ingress.fqdn : ''
