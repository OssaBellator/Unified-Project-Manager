[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)

& (Join-Path $Root 'scripts/build.ps1')
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

& (Join-Path $Root 'scripts/test.ps1')
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
