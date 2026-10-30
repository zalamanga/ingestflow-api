. (Join-Path $PSScriptRoot 'Common.ps1')
Invoke-ProjectCommand { Invoke-Checked -Program docker -Arguments @('compose','-f','compose.yml','-p','ingestflow','down','--remove-orphans') }
