# Trading Demo HUD - installazione publisher (solo lettura, nessuna finestra)
# Da eseguire SOLO dopo l'ok di Nikolas, in PowerShell normale (non admin).
$ErrorActionPreference = 'Stop'
$Dir     = Join-Path $env:USERPROFILE 'TradingDemoHud'
$PyW     = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\pythonw.exe'
$Py      = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'
$Target  = 'trading-demo-hud-publisher'
$Startup = [Environment]::GetFolderPath('Startup')
$Lnk     = Join-Path $Startup 'TradingDemoHud publisher.lnk'

if (-not (Test-Path $PyW)) { throw "pythonw.exe non trovato in $PyW" }
New-Item -ItemType Directory -Force -Path $Dir | Out-Null
Copy-Item -Force (Join-Path $PSScriptRoot 'publisher.py') (Join-Path $Dir 'publisher.py')

# 1) token: deve gia' essere nel Gestore credenziali di Windows (target $Target)
$chk = & $Py (Join-Path $Dir 'publisher.py') --check
$chk | ForEach-Object { Write-Host $_ }
if ($chk -match 'MANCANTE') {
  Write-Host "Inserisci il token GitHub (non verra' mostrato):"
  cmdkey /generic:$Target /user:github /pass
}

# 2) prova singola (pubblica una volta, poi esce)
& $Py (Join-Path $Dir 'publisher.py') --once
if ($LASTEXITCODE -ne 0) { throw "Prova di pubblicazione fallita: vedi $env:LOCALAPPDATA\TradingDemoHud\publisher.log" }

# 3) avvio automatico al login: collegamento nella cartella Esecuzione automatica (nessuna attivita' pianificata)
$ws = New-Object -ComObject WScript.Shell
$s = $ws.CreateShortcut($Lnk)
$s.TargetPath = $PyW
$s.Arguments = '"' + (Join-Path $Dir 'publisher.py') + '"'
$s.WorkingDirectory = $Dir
$s.WindowStyle = 7
$s.Description = 'Trading Demo HUD publisher (sola lettura)'
$s.Save()

# 4) avvio adesso, nascosto (pythonw non apre finestre; doppio avvio impedito da un mutex)
Start-Process -FilePath $PyW -ArgumentList ('"' + (Join-Path $Dir 'publisher.py') + '"') -WorkingDirectory $Dir -WindowStyle Hidden
Write-Host "Publisher installato e avviato. Log: $env:LOCALAPPDATA\TradingDemoHud\publisher.log"
