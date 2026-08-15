[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]] $Tests
)

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
$env:PYTHONPATH = Join-Path $Root 'src'
if ($existingPythonPath) {
    $env:PYTHONPATH = "$env:PYTHONPATH$([IO.Path]::PathSeparator)$existingPythonPath"
}

Push-Location $Root
try {
    if ($Tests.Count -gt 0) {
        $resolvedTests = @(
            foreach ($test in $Tests) {
                $candidate = $test
                if (-not (Test-Path $candidate) -and $test -notmatch '[\\/]' -and -not $test.EndsWith('.py')) {
                    $localTest = Join-Path 'tests' "$test.py"
                    if (Test-Path $localTest) {
                        $candidate = $localTest
                    }
                }
                $candidate
            }
        )
        & $resolved.Exe @($resolved.Prefix) -m unittest @resolvedTests -v
    }
    else {
        & $resolved.Exe @($resolved.Prefix) -m unittest discover -s tests -v
    }

    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}
finally {
    Pop-Location
    $env:PYTHONPATH = $existingPythonPath
}
