[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)

function Resolve-Python {
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        return @{ Exe = $python.Source; Prefix = @() }
    }

    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        return @{ Exe = $py.Source; Prefix = @('-3') }
    }

    throw 'Python 3 is required but neither python nor py is available.'
}

$resolved = Resolve-Python
Push-Location $Root
try {
    & $resolved.Exe @($resolved.Prefix) -m compileall -q src tests
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}
finally {
    Pop-Location
}
