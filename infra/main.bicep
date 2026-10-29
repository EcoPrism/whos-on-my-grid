targetScope = 'resourceGroup'

// Who's On My Grid runs inside ONE resource group: registry, Key Vault,
// storage (a file share for the brief cache and datasets, two tables for
// sign-ins and usage), a Container Apps environment and one container app.
//
// Two-phase deploy (scripts/deploy.ps1): deployApi=false provisions the
// platform; secrets are written to the vault and the image built; then
// deployApi=true creates or rolls the app. The app never references a
// secret or an image that is missing.
//
// Secret VALUES never pass through this file. The vault holds gateway-key,
// baseten-key and session-secret, written by the deploy script's `secrets`
// phase; the app reads them through its identity.

@description('Region for every resource.')
param location string = resourceGroup().location

@description('Object id of the person deploying; gets Secrets Officer on this vault only.')
param deployerObjectId string

@description('Google OAuth web client id (public). Empty keeps the gate off, which is not what production wants.')
param googleClientId string = ''

@description('Comma-separated ISO country codes allowed to make briefs. Empty = off. Set to US only once Cloudflare fronts the app and writes cf-ipcountry.')
param allowedCountries string = ''

@description('Verifier model id on Baseten. The hackathon key serves only the -1026 build.')
param verifyModel string = 'meta-models/muse-spark-open-1026'

@description('New briefs per signed-in user per UTC day.')
param quotaPerUserDay int = 5

@description('New briefs per UTC day for everyone together: the gateway budget belt.')
param quotaGlobalDay int = 40

@description('Scheme and host the share links and cards print, no trailing slash. Empty = the app\'s own FQDN; set it to the custom domain once one is bound.')
param publicBaseUrl string = ''

@description('Custom domains already on the app (name, bindingType, certificateId). ARM replaces the whole ingress block, so the deploy script passes the current list and a redeploy keeps the domains and their certificates.')
param customDomains array = []

@description('Fully qualified image. Used only when deployApi is true.')
param containerImage string = ''

@description('Phase switch, see header.')
param deployApi bool = false

var suffix = uniqueString(resourceGroup().id)
var roles = {
  acrPull: '7f951dda-4ed3-4680-a7ca-43fe172d538d'
  kvSecretsUser: '4633458b-17de-408a-b874-0445c86b69e6'
  kvSecretsOfficer: 'b86a8fe4-44ce-4948-aee5-eccb2c155cd7'
  tableDataContributor: '0a9a7e1f-b9d0-4cc4-a60d-0319b160aaa3'
}
var shareName = 'grid'
var vaultUri = 'https://kv-grid-${suffix}${environment().suffixes.keyvaultDns}/secrets/'

// --- logs --------------------------------------------------------------------

resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: 'log-grid'
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
    workspaceCapping: { dailyQuotaGb: 1 }
  }
}

// --- identity ----------------------------------------------------------------

resource appIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-grid-app'
  location: location
}

// --- registry ----------------------------------------------------------------

resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: 'crgrid${suffix}'
  location: location
  sku: { name: 'Basic' }
  properties: { adminUserEnabled: false }
}

resource acrPullApp 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(acr.id, appIdentity.id, roles.acrPull)
  scope: acr
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.acrPull)
    principalId: appIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// --- key vault ---------------------------------------------------------------

resource kv 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: 'kv-grid-${suffix}'
  location: location
  properties: {
    tenantId: subscription().tenantId
    sku: { family: 'A', name: 'standard' }
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 7
    publicNetworkAccess: 'Enabled'
  }
}

resource kvUserApp 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(kv.id, appIdentity.id, roles.kvSecretsUser)
  scope: kv
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.kvSecretsUser)
    principalId: appIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource kvOfficerDeployer 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(kv.id, deployerObjectId, roles.kvSecretsOfficer)
  scope: kv
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.kvSecretsOfficer)
    principalId: deployerObjectId
    principalType: 'User'
  }
}

// --- storage: file share (briefs, datasets) and tables (users, usage) --------

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: 'stgrid${suffix}'
  location: location
  kind: 'StorageV2'
  sku: { name: 'Standard_LRS' }
  properties: {
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
    supportsHttpsTrafficOnly: true
    // The Container Apps file mount authenticates with the account key. The app
    // itself never sees it: tables are reached with the managed identity.
    allowSharedKeyAccess: true
  }
}

resource fileServices 'Microsoft.Storage/storageAccounts/fileServices@2023-05-01' = {
  parent: storage
  name: 'default'
}

resource share 'Microsoft.Storage/storageAccounts/fileServices/shares@2023-05-01' = {
  parent: fileServices
  name: shareName
  properties: { shareQuota: 5 }
}

resource tableServices 'Microsoft.Storage/storageAccounts/tableServices@2023-05-01' = {
  parent: storage
  name: 'default'
}

resource usersTable 'Microsoft.Storage/storageAccounts/tableServices/tables@2023-05-01' = {
  parent: tableServices
  name: 'users'
}

resource usageTable 'Microsoft.Storage/storageAccounts/tableServices/tables@2023-05-01' = {
  parent: tableServices
  name: 'usage'
}

resource tableApp 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storage.id, appIdentity.id, roles.tableDataContributor)
  scope: storage
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.tableDataContributor)
    principalId: appIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// --- container apps environment ---------------------------------------------

resource env 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: 'cae-grid'
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logs.properties.customerId
        sharedKey: logs.listKeys().primarySharedKey
      }
    }
  }
}

resource envStorage 'Microsoft.App/managedEnvironments/storages@2024-03-01' = {
  parent: env
  name: shareName
  properties: {
    azureFile: {
      accountName: storage.name
      accountKey: storage.listKeys().keys[0].value
      shareName: shareName
      accessMode: 'ReadWrite'
    }
  }
  dependsOn: [share]
}

// --- the app -----------------------------------------------------------------

var secretNames = ['gateway-key', 'baseten-key', 'session-secret']

resource app 'Microsoft.App/containerApps@2024-03-01' = if (deployApi) {
  name: 'ca-grid'
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${appIdentity.id}': {} }
  }
  properties: {
    managedEnvironmentId: env.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        targetPort: 8000
        transport: 'auto'
        allowInsecure: false
        customDomains: customDomains
      }
      registries: [{ server: acr.properties.loginServer, identity: appIdentity.id }]
      secrets: [for name in secretNames: {
        name: name
        keyVaultUrl: '${vaultUri}${name}'
        identity: appIdentity.id
      }]
    }
    template: {
      containers: [
        {
          name: 'api'
          image: containerImage
          resources: { cpu: json('0.5'), memory: '1Gi' }
          env: [
            { name: 'GRID_BRIEF_SOURCE', value: 'full' }
            { name: 'GRID_LLM_PROVIDER', value: 'openai' }
            { name: 'GRID_OPENAI_API_KEY', secretRef: 'gateway-key' }
            { name: 'GRID_BASETEN_API_KEY', secretRef: 'baseten-key' }
            { name: 'GRID_VERIFY_MODEL', value: verifyModel }
            { name: 'GRID_DATA_DIR', value: '/mnt/grid/briefs' }
            { name: 'GRID_GROUND_DIR', value: '/mnt/grid/ground' }
            { name: 'GRID_CARDS_DIR', value: '/mnt/grid/cards' }
            // Fixed, never the request's Host: briefs and cached cards print it.
            { name: 'GRID_PUBLIC_BASE_URL', value: empty(publicBaseUrl) ? 'https://ca-grid.${env.properties.defaultDomain}' : publicBaseUrl }
            { name: 'GRID_CORS_ORIGINS', value: '' }
            { name: 'GRID_ALLOWED_COUNTRIES', value: allowedCountries }
            { name: 'GRID_AUTH_PROVIDER', value: empty(googleClientId) ? 'off' : 'google' }
            { name: 'GRID_GOOGLE_CLIENT_ID', value: googleClientId }
            { name: 'GRID_SESSION_SECRET', secretRef: 'session-secret' }
            { name: 'GRID_COOKIE_SECURE', value: 'true' }
            { name: 'GRID_USAGE_STORE', value: 'table' }
            { name: 'GRID_STORAGE_ACCOUNT', value: storage.name }
            { name: 'GRID_QUOTA_PER_USER_DAY', value: string(quotaPerUserDay) }
            { name: 'GRID_QUOTA_GLOBAL_DAY', value: string(quotaGlobalDay) }
            { name: 'AZURE_CLIENT_ID', value: appIdentity.properties.clientId }
          ]
          probes: [
            {
              type: 'Readiness'
              httpGet: { path: '/api/health', port: 8000 }
              initialDelaySeconds: 5
              periodSeconds: 10
              failureThreshold: 6
            }
            {
              type: 'Liveness'
              httpGet: { path: '/api/health', port: 8000 }
              initialDelaySeconds: 30
              periodSeconds: 30
              failureThreshold: 3
            }
          ]
          volumeMounts: [{ volumeName: shareName, mountPath: '/mnt/grid' }]
        }
      ]
      volumes: [
        {
          name: shareName
          storageType: 'AzureFile'
          storageName: envStorage.name
          // The container runs as uid 10001 (Dockerfile); own the share as it.
          mountOptions: 'uid=10001,gid=10001,dir_mode=0770,file_mode=0660,nobrl'
        }
      ]
      // One replica by design: the in-process in-flight registry and the
      // cache's temp files assume a single writer.
      scale: { minReplicas: 1, maxReplicas: 1 }
    }
  }
  dependsOn: [acrPullApp, kvUserApp, tableApp]
}

output acrName string = acr.name
output acrLoginServer string = acr.properties.loginServer
output vaultName string = kv.name
output storageAccount string = storage.name
output appName string = 'ca-grid'
output appFqdn string = deployApi ? app!.properties.configuration.ingress.fqdn : ''
