# Trading Demo HUD - installazione publisher (sola lettura, nessuna finestra, nessuna attivita' pianificata)
# Prerequisito: chiave deploy generata sul PC in %LOCALAPPDATA%\TradingDemoHud\deploy_ed25519 (la .pub e' registrata
# come deploy key con scrittura SOLO sul repo nikolasserpilli-max/trading-demo-hud-data).
$ErrorActionPreference = 'Stop'
$Dir     = Join-Path $env:USERPROFILE 'TradingDemoHud'
$State   = Join-Path $env:LOCALAPPDATA 'TradingDemoHud'
$PyW     = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\pythonw.exe'
$Py      = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'
$Script  = Join-Path $Dir 'publisher.py'
$Lnk     = Join-Path ([Environment]::GetFolderPath('Startup')) 'TradingDemoHud publisher.lnk'

if (-not (Test-Path $PyW)) { throw "pythonw.exe non trovato in $PyW" }
if (-not (Test-Path (Join-Path $State 'deploy_ed25519'))) { throw "chiave deploy mancante in $State" }
New-Item -ItemType Directory -Force -Path $Dir | Out-Null
Copy-Item -Force (Join-Path $PSScriptRoot 'publisher.py') $Script
# chiavi host di github.com (impronte verificate: ED25519 SHA256:+DiY3wvvV6TuJJhbpZisF/zLDA0zPMSvHdkr4UvCOqU)
Copy-Item -Force (Join-Path $PSScriptRoot 'known_hosts_github') (Join-Path $State 'known_hosts_github')

# 1) controlli + prova singola
& $Py $Script --check
& $Py $Script --once
if ($LASTEXITCODE -ne 0) { throw "Prova di pubblicazione fallita: vedi $State\publisher.log" }

# 2) avvio automatico al login (collegamento in Esecuzione automatica, pythonw = nessuna finestra)
$ws = New-Object -ComObject WScript.Shell
$s = $ws.CreateShortcut($Lnk)
$s.TargetPath = $PyW
$s.Arguments = '"' + $Script + '"'
$s.WorkingDirectory = $Dir
$s.WindowStyle = 7
$s.Description = 'Trading Demo HUD publisher (sola lettura)'
$s.Save()

# 3) avvio adesso, nascosto (doppio avvio impedito dal mutex Local\TradingDemoHudPublisher)
Start-Process -FilePath $PyW -ArgumentList ('"' + $Script + '"') -WorkingDirectory $Dir -WindowStyle Hidden
Write-Host "Publisher installato e avviato. Log: $State\publisher.log"
