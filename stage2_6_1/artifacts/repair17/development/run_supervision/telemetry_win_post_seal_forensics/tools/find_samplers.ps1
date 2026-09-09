$ErrorActionPreference = 'SilentlyContinue'
$procs = Get-CimInstance Win32_Process -Filter "Name like 'powershell%' or Name like 'pwsh%'" |
  Where-Object { $_.CommandLine -match 'win_sampler' }
$out = @()
foreach ($p in $procs) {
  $cl = $p.CommandLine
  if ($cl.Length -gt 400) { $cl = $cl.Substring(0, 400) + '...' }
  $out += [PSCustomObject]@{
    Pid         = $p.ProcessId
    ParentPid   = $p.ParentProcessId
    Created     = $p.CreationDate
    CommandLine = $cl
  }
}
if ($out.Count -eq 0) { Write-Output 'NO_WIN_SAMPLER_PROCESS' }
$out | ConvertTo-Json -Depth 2
