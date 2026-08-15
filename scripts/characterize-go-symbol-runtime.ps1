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
$existingPythonPath = $env:PYTHONPATH
$pythonPaths = @(
    (Join-Path $Root 'src'),
    (Join-Path $Root 'tests')
)
if ($existingPythonPath) {
    $pythonPaths += $existingPythonPath
}
$env:PYTHONPATH = $pythonPaths -join [IO.Path]::PathSeparator

Push-Location $Root
try {
    & $resolved.Exe @($resolved.Prefix) (Join-Path $Root 'tests/characterize_go_symbol_runtime.py')
    exit $LASTEXITCODE
}
finally {
    Pop-Location
    $env:PYTHONPATH = $existingPythonPath
}
