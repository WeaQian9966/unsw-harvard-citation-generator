$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..')

pyinstaller `
  --noconfirm `
  --clean `
  --windowed `
  --onefile `
  --name UNSWHarvardCiteGenerator `
  unsw_harvard_cite_generator_gui.py

Write-Host "Built Windows exe at: dist/UNSWHarvardCiteGenerator.exe"
