Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" |
  Where-Object { $_.CommandLine -like '*r17_win_sampler*' } |
  ForEach-Object {
    "PID=$($_.ProcessId) CREATED=$($_.CreationDate) PARENTPID=$($_.ParentProcessId)"
    "CMD=$($_.CommandLine.Substring(0,[Math]::Min(200,$_.CommandLine.Length)))"
  }
