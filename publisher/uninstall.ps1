# Trading Demo HUD - rimozione publisher
$Lnk = Join-Path ([Environment]::GetFolderPath('Startup')) 'TradingDemoHud publisher.lnk'
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" |
  Where-Object { $_.CommandLine -like '*TradingDemoHud*publisher.py*' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Remove-Item -Force -ErrorAction SilentlyContinue $Lnk
Write-Host "Publisher fermato e avvio automatico rimosso."
Write-Host "Per togliere tutto: cancella $env:USERPROFILE\TradingDemoHud e $env:LOCALAPPDATA\TradingDemoHud (contiene la chiave privata)"
Write-Host "e rimuovi la deploy key: gh repo deploy-key list/delete -R nikolasserpilli-max/trading-demo-hud-data"
