<#
.SYNOPSIS
  Provision and deploy Who's On My Grid into its own resource group on Azure.

  Everything lives in one group (infra/main.bicep): registry, Key Vault, storage
  (file share for briefs and datasets, tables for sign-ins and usage), a
  Container Apps environment and one container app. Settings that are not
  secret are in infra/deploy.json.

  Phases, in order:
    platform  create the group and everything but the app
    secrets   copy the gateway and Baseten keys from services/api/.env into the
              vault, mint the session secret once, seed the share with data/ground.
              Values are piped to files and az; nothing is printed.
    image     build the image in the registry (az acr build; no local Docker needed)
    app       create or roll the container app, then poll /api/health
    all       the four above, in order

.EXAMPLE
  ./scripts/deploy.ps1 -Phase platform
  ./scripts/deploy.ps1 -Phase secrets
  ./scripts/deploy.ps1 -Phase image
  ./scripts/deploy.ps1 -Phase app
#>
param(
  [ValidateSet('platform', 'secrets', 'image', 'app', 'all')][string] $Phase = 'all',
  [string] $Settings = '',
  # Image tag; defaults to the short commit sha, so `-Phase app` rolls the image `-Phase image` built.
  [string] $Tag = '',
  # The app phase refuses to ship without a Google client id (the gate would be off for
  # the whole internet). This switch is the explicit, typed way to do it anyway.
  [switch] $AllowOpenGate
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path $PSScriptRoot -Parent
if (-not $Settings) { $Settings = Join-Path $repoRoot 'infra/deploy.json' }
$cfg = Get-Content $Settings -Raw | ConvertFrom-Json
$rg = $cfg.resourceGroup
$bicep = Join-Path $repoRoot 'infra/main.bicep'
if (-not $Tag) { $Tag = (git -C $repoRoot rev-parse --short HEAD) }

# az writes progress chatter to stderr; never let PowerShell 5.1 turn that into
# a terminating error. Judge success by $LASTEXITCODE instead.
function Invoke-Az {
  param([string[]] $AzArgs)
  $prev = $ErrorActionPreference
  $ErrorActionPreference = 'Continue'
  try { return (& az @AzArgs 2>$null) } finally { $ErrorActionPreference = $prev }
}

function New-Secret([int] $Length) {
  $bytes = New-Object byte[] ($Length)
  [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
  $alphabet = [char[]]'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789'
  -join ($bytes | ForEach-Object { $alphabet[$_ % $alphabet.Length] })
}

# One value from a .env file. Inline comments and quotes are stripped; the value
# is returned, never written to the console.
function Read-DotEnv([string] $Path, [string] $Key) {
  if (-not (Test-Path $Path)) { return $null }
  foreach ($line in Get-Content $Path) {
    if ($line -match ('^\s*' + [regex]::Escape($Key) + '\s*=\s*(.*)$')) {
      $v = ($Matches[1] -split '\s+#')[0].Trim().Trim('"').Trim("'")
      if ($v) { return $v }
      return $null
    }
  }
  return $null
}

function Test-VaultSecret([string] $Vault, [string] $Name) {
  Invoke-Az @('keyvault', 'secret', 'show', '--vault-name', $Vault, '-n', $Name, '--query', 'id', '-o', 'tsv') | Out-Null
  return ($LASTEXITCODE -eq 0)
}

# The value goes through an owner-only temp file, never the command line.
function Set-VaultSecret([string] $Vault, [string] $Name, [string] $Value) {
  $file = Join-Path ([IO.Path]::GetTempPath()) ('grid-secret-' + [guid]::NewGuid())
  try {
    [IO.File]::WriteAllText($file, $Value)
    Invoke-Az @('keyvault', 'secret', 'set', '--vault-name', $Vault, '-n', $Name, '--file', $file, '-o', 'none') | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Could not write secret $Name to vault $Vault (is the Secrets Officer role in place yet?)" }
    Write-Host "    $Name written"
  } finally {
    Remove-Item -Path $file -Force -ErrorAction SilentlyContinue
  }
}

function Invoke-Deploy([bool] $DeployApi, [string] $Image) {
  $me = Invoke-Az @('ad', 'signed-in-user', 'show', '--query', 'id', '-o', 'tsv')
  if (-not $me) { throw 'Not signed in: run az login' }
  # A redeploy would drop the custom domains and their certificates (ARM replaces the ingress
  # block), so carry the ones that are bound today.
  $domains = @()
  if ($DeployApi) {
    $raw = Invoke-Az @('containerapp', 'hostname', 'list', '-n', 'ca-grid', '-g', $rg, '-o', 'json')
    if ($LASTEXITCODE -eq 0 -and $raw) {
      foreach ($d in ($raw | Out-String | ConvertFrom-Json)) {
        $entry = @{ name = $d.name; bindingType = $d.bindingType }
        if ($d.certificateId) { $entry.certificateId = $d.certificateId }
        $domains += $entry
      }
    }
  }
  $params = @{
    '$schema'      = 'https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#'
    contentVersion = '1.0.0.0'
    parameters     = @{
      deployerObjectId = @{ value = $me }
      googleClientId   = @{ value = [string]$cfg.googleClientId }
      allowedCountries = @{ value = [string]$cfg.allowedCountries }
      verifyModel      = @{ value = [string]$cfg.verifyModel }
      quotaPerUserDay  = @{ value = [int]$cfg.quotaPerUserDay }
      quotaGlobalDay   = @{ value = [int]$cfg.quotaGlobalDay }
      publicBaseUrl    = @{ value = [string]$cfg.publicBaseUrl }
      customDomains    = @{ value = @($domains) }
      containerImage   = @{ value = $Image }
      deployApi        = @{ value = $DeployApi }
    }
  }
  $file = Join-Path ([IO.Path]::GetTempPath()) ('grid-params-' + [guid]::NewGuid() + '.json')
  try {
    $params | ConvertTo-Json -Depth 5 | Set-Content -Path $file -Encoding utf8
    $name = if ($DeployApi) { 'grid-app' } else { 'grid-platform' }
    $out = Invoke-Az @('deployment', 'group', 'create', '-g', $rg, '-n', $name, '-f', $bicep,
      '-p', "@$file", '--query', 'properties.outputs', '-o', 'json')
    if ($LASTEXITCODE -ne 0) { throw "Bicep deployment '$name' failed. See: az deployment group show -g $rg -n $name" }
    return ($out | Out-String | ConvertFrom-Json)
  } finally {
    Remove-Item -Path $file -Force -ErrorAction SilentlyContinue
  }
}

function Get-FirstName([string[]] $AzArgs) {
  $v = Invoke-Az ($AzArgs + @('-g', $rg, '--query', '[0].name', '-o', 'tsv'))
  if ($LASTEXITCODE -ne 0 -or -not $v) { throw "Nothing found in $rg for: az $($AzArgs -join ' '). Run -Phase platform first." }
  return $v
}

Invoke-Az @('account', 'set', '-s', [string]$cfg.subscription) | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Could not select subscription '$($cfg.subscription)'" }

$steps = if ($Phase -eq 'all') { @('platform', 'secrets', 'image', 'app') } else { @($Phase) }

foreach ($step in $steps) {
  switch ($step) {
    'platform' {
      Write-Host "==> platform: $rg in $($cfg.location)" -ForegroundColor Cyan
      Invoke-Az @('group', 'create', '-n', $rg, '-l', [string]$cfg.location, '-o', 'none') | Out-Null
      if ($LASTEXITCODE -ne 0) { throw "Could not create resource group $rg" }
      $o = Invoke-Deploy $false ''
      Write-Host "    registry $($o.acrName.value), vault $($o.vaultName.value), storage $($o.storageAccount.value)"
    }
    'secrets' {
      Write-Host '==> secrets: services/api/.env -> Key Vault; session secret; seed the share' -ForegroundColor Cyan
      $vault = Get-FirstName @('keyvault', 'list')
      $envFile = Join-Path $repoRoot 'services/api/.env'
      $gateway = Read-DotEnv $envFile 'GRID_OPENAI_API_KEY'
      if (-not $gateway) { throw 'GRID_OPENAI_API_KEY is not set in services/api/.env' }
      Set-VaultSecret $vault 'gateway-key' $gateway
      $baseten = Read-DotEnv $envFile 'GRID_BASETEN_API_KEY'
      if ($baseten) { Set-VaultSecret $vault 'baseten-key' $baseten }
      else { Write-Warning 'GRID_BASETEN_API_KEY is empty: writing a blank baseten-key, claims will stay unchecked.'; Set-VaultSecret $vault 'baseten-key' ' ' }
      if (Test-VaultSecret $vault 'session-secret') { Write-Host '    session-secret kept (rotating it signs everyone out)' }
      else { Set-VaultSecret $vault 'session-secret' (New-Secret 48) }
      $gateway = $null; $baseten = $null

      $account = Get-FirstName @('storage', 'account', 'list')
      # The key goes to az through the environment, never the command line: az.cmd echoes its
      # whole command line on a cmd-level error, and the process list shows arguments.
      $env:AZURE_STORAGE_ACCOUNT = $account
      $env:AZURE_STORAGE_KEY = Invoke-Az @('storage', 'account', 'keys', 'list', '-g', $rg, '-n', $account, '--query', '[0].value', '-o', 'tsv')
      try {
        Invoke-Az @('storage', 'directory', 'create', '--share-name', 'grid', '--name', 'briefs', '-o', 'none') | Out-Null
        $ground = Join-Path $repoRoot 'data/ground'
        if (Test-Path $ground) {
          foreach ($pattern in @('*.json', '*.xlsx')) {
            Invoke-Az @('storage', 'file', 'upload-batch', '--destination', 'grid', '--destination-path', 'ground',
              '--source', $ground, '--pattern', $pattern, '-o', 'none') | Out-Null
          }
          Write-Host '    share seeded from data/ground (json, xlsx)'
        }
      } finally {
        Remove-Item Env:AZURE_STORAGE_KEY -ErrorAction SilentlyContinue
        Remove-Item Env:AZURE_STORAGE_ACCOUNT -ErrorAction SilentlyContinue
      }
    }
    'image' {
      $acr = Get-FirstName @('acr', 'list')
      Write-Host "==> image: grid:$Tag in $acr" -ForegroundColor Cyan
      $mapsKey = Read-DotEnv (Join-Path $repoRoot 'web/.env') 'VITE_GOOGLE_MAPS_API_KEY'
      # --no-logs: az on Windows runs Python in isolated mode and dies with a charmap error
      # the moment the build log prints a non-ASCII character (npm's check mark). Poll instead.
      $buildArgs = @('acr', 'build', '--registry', $acr, '--image', "grid:$Tag", '--image', 'grid:latest',
        '--file', (Join-Path $repoRoot 'Dockerfile'), '--no-logs', '--query', 'runId', '-o', 'tsv')
      if ($mapsKey) { $buildArgs += @('--secret-build-arg', "VITE_GOOGLE_MAPS_API_KEY=$mapsKey") }
      else { Write-Warning 'VITE_GOOGLE_MAPS_API_KEY is empty in web/.env: the address box will be a plain input.' }
      $buildArgs += $repoRoot
      $runId = Invoke-Az $buildArgs
      $mapsKey = $null; $buildArgs = $null
      if ($LASTEXITCODE -ne 0 -or -not $runId) { throw 'ACR build could not be queued' }
      $status = 'Queued'; $last = ''
      while ($status -in @('Queued', 'Started', 'Running')) {
        Start-Sleep -Seconds 15
        $status = Invoke-Az @('acr', 'task', 'show-run', '-r', $acr, '--run-id', $runId, '--query', 'status', '-o', 'tsv')
        if ($status -ne $last) { Write-Host "    run $runId : $status"; $last = $status }
      }
      if ($status -ne 'Succeeded') { throw "ACR build $runId ended $status. Log: az acr task logs -r $acr --run-id $runId" }
    }
    'app' {
      if (-not [string]$cfg.googleClientId -and -not $AllowOpenGate) {
        throw 'googleClientId is empty in infra/deploy.json: the sign-in gate would be OFF for everyone. Create the OAuth client (docs/deploy.md, step 2) or pass -AllowOpenGate.'
      }
      $acr = Get-FirstName @('acr', 'list')
      $login = Invoke-Az @('acr', 'show', '-n', $acr, '--query', 'loginServer', '-o', 'tsv')
      $image = "$login/grid:$Tag"
      Write-Host "==> app: $image" -ForegroundColor Cyan
      $o = Invoke-Deploy $true $image
      $fqdn = $o.appFqdn.value
      Write-Host "    https://$fqdn" -ForegroundColor Green
      $ok = $false
      for ($i = 0; $i -lt 30 -and -not $ok; $i++) {
        try {
          $r = Invoke-WebRequest -UseBasicParsing -Uri "https://$fqdn/api/health" -TimeoutSec 15
          if ($r.StatusCode -eq 200) { $ok = $true; Write-Host "    /api/health: $($r.Content)" }
        } catch { Start-Sleep -Seconds 10 }
      }
      if (-not $ok) { Write-Warning 'The app did not answer /api/health within five minutes. Check: az containerapp logs show -n ca-grid -g ' + $rg }
      Write-Host "    Remember: add https://$fqdn to the Google OAuth client's JavaScript origins and to the Maps key's referrers (docs/deploy.md)."
    }
  }
}
