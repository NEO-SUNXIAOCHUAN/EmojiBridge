# Shared family policy. No UI actions or account data. Pin version per helper
# session as well, so changing a client during an operation still stops it.
$script:BridgeClientPolicy=Get-Content -LiteralPath (Join-Path $PSScriptRoot '../assets/client-compat.json') -Raw | ConvertFrom-Json
$script:BridgeVersionPins=@{}
function Test-BridgeVersion([string]$client,[string]$version) {
 if($version -notmatch '^\d+\.\d+\.\d+\.\d+$'){return $false}
 $policy=$script:BridgeClientPolicy.$client
 if($null -eq $policy){return $false}
 $parts=$version.Split('.')
 $families=@(,$policy.family)
 foreach($candidate in $policy.candidate_families){$families+=,$candidate}
 foreach($family in $families){
  if([int]$parts[0] -eq $family[0] -and [int]$parts[1] -eq $family[1]){return $true}
 }
 return $false
}
function Confirm-BridgeVersion([string]$client,[string]$exe) {
 $version=[Diagnostics.FileVersionInfo]::GetVersionInfo($exe).FileVersion
 if(-not (Test-BridgeVersion $client $version)){throw 'client_family_unadapted'}
 if($script:BridgeVersionPins.ContainsKey($exe) -and $script:BridgeVersionPins[$exe] -ne $version){throw 'client_version_changed'}
 $script:BridgeVersionPins[$exe]=$version
}
