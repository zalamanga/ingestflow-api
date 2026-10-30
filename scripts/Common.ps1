$ErrorActionPreference = 'Stop'
$script:ProjectRoot = Split-Path -Parent $PSScriptRoot
function Invoke-Checked {
    param([string]$Program, [string[]]$Arguments)
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Program failed with exit code $LASTEXITCODE" }
}
function Invoke-ProjectCommand {
    param([scriptblock]$Action)
    $saved = @{}
    foreach ($name in @('TEMP','TMP','PIP_CACHE_DIR','PYTHONPYCACHEPREFIX')) {
        $saved[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
    }
    $local = Join-Path $script:ProjectRoot '.local'
    $temp = Join-Path $local 'tmp'
    New-Item -ItemType Directory -Force -Path $temp | Out-Null
    $env:TEMP = $temp
    $env:TMP = $temp
    $env:PIP_CACHE_DIR = Join-Path $local 'pip-cache'
    $env:PYTHONPYCACHEPREFIX = Join-Path $local 'pycache'
    Push-Location -LiteralPath $script:ProjectRoot
    try { & $Action }
    finally {
        Pop-Location
        foreach ($name in $saved.Keys) { [Environment]::SetEnvironmentVariable($name, $saved[$name], 'Process') }
    }
}
