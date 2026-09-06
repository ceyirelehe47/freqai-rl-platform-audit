# R17 阶段 A/C：Windows 存储事件 + 存活任务探针
# 输出: F:\r17_diagnosis\win_storage_events.txt / win_processes.txt
$ErrorActionPreference = "SilentlyContinue"

# --- 近 14 小时存储相关 System 事件 ---
$since = (Get-Date).AddHours(-14)
$ev = Get-WinEvent -FilterHashtable @{LogName="System"; StartTime=$since} |
    Where-Object { $_.ProviderName -match "disk|Ntfs|volmgr|partmgr|storahc|stornvme|Kernel-PnP|volsnap" }
$out = @()
foreach ($e in $ev) {
    $msg = ($e.Message -replace "`r`n", " ")
    if ($msg.Length -gt 160) { $msg = $msg.Substring(0, 160) }
    $out += ("{0} | {1} | {2} | {3}" -f $e.TimeCreated.ToUniversalTime().ToString("u"), $e.Id, $e.ProviderName, $msg)
}
if ($out.Count -eq 0) { $out += "(no storage-related System events in window)" }
$out | Set-Content -Path "F:\r17_diagnosis\win_storage_events.txt" -Encoding UTF8

# --- 当前存活任务（重任务族 + WSL VM） ---
$procs = Get-Process | Where-Object { $_.Name -match "python|wsl|bash|vmmem|conda|pytest|powershell" } |
    Sort-Object WorkingSet64 -Descending |
    Select-Object Name, Id, @{n="WS_MB";e={[math]::Round($_.WorkingSet64/1MB,1)}},
        @{n="Priv_MB";e={[math]::Round($_.PrivateMemorySize64/1MB,1)}},
        @{n="StartUTC";e={if ($_.StartTime) {$_.StartTime.ToUniversalTime().ToString("u")} else {"n/a"}}}
($procs | Format-Table -AutoSize | Out-String -Width 140) | Set-Content -Path "F:\r17_diagnosis\win_processes.txt" -Encoding UTF8

# --- OS 内存快照 ---
$os = Get-CimInstance Win32_OperatingSystem
("free_phys_gb={0:N2} total_phys_gb={1:N2} commit_used_gb={2:N2} commit_limit_gb={3:N2}" -f `
    ($os.FreePhysicalMemory/1MB), ($os.TotalVisibleMemorySize/1MB),
    (($os.TotalVirtualMemorySize - $os.FreeVirtualMemory)/1MB), ($os.TotalVirtualMemorySize/1MB)) |
    Set-Content -Path "F:\r17_diagnosis\win_mem_snapshot.txt" -Encoding UTF8
Write-Output "probe done"
