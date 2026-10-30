. (Join-Path $PSScriptRoot 'Common.ps1')
Invoke-ProjectCommand { Invoke-Checked -Program python -Arguments @('scripts/init_env.py') }
