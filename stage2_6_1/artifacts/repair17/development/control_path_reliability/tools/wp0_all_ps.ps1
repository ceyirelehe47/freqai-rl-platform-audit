Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" |
  ForEach-Object { "PID=$($_.ProcessId) CREATED=$($_.CreationDate) PPID=$($_.ParentProcessId) CMDLEN=$($_.CommandLine.Length)" }
"---- pwsh ----"
Get-CimInstance Win32_Process -Filter "Name='pwsh.exe'" | ForEach-Object { "PID=$($_.ProcessId) CREATED=$($_.CreationDate)" }
