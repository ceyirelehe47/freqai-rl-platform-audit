# R17 阶段 B：Windows 侧资源采样器（任务书 §4 B1/B2/B4）
# 独立进程，不依赖 WSL 客户端连接（B3：不用 wsl.exe 探测 VM 存活）。
# 启动: powershell.exe -NoProfile -ExecutionPolicy Bypass -File win_sampler.ps1
#   可选参数: -OutFile <path> -IntervalSeconds 5 -MaxSeconds 0(不限)
# 输出: JSONL（每条一行），UTF-8 追加；保护线事件同文件 event 字段区分。
# 兼容 PowerShell 5.1（不用 -AsUTC 等 PS6+ 特性）。

param(
    [string]$OutFile = "F:\r17_diagnosis\windows_samples.jsonl",
    [int]$IntervalSeconds = 5,
    [int]$MaxSeconds = 0,
    [int]$DetailEvery = 6,        # 每 N 次采样附一次进程明细(默认30s)
    [string]$StopMarker = "F:\r17_diagnosis\PROTECTION_STOP"
)

$ErrorActionPreference = "Continue"
$thisProc = $PID
$lowFreeStreak = 0
$highCommitStreak = 0
$detailCount = 0

function Write-JsonLine([object]$obj) {
    $line = $obj | ConvertTo-Json -Compress -Depth 5
    Add-Content -Path $OutFile -Value $line -Encoding UTF8
}

function Get-UtcNowIso {
    return (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ss.fffZ")
}

Write-JsonLine @{ event="sampler_start"; utc=(Get-UtcNowIso); pid=$thisProc;
    interval_s=$IntervalSeconds; out=$OutFile }

$start = Get-Date
while ($true) {
    $now = Get-UtcNowIso
    # --- OS 内存/commit（CIM 单查询，轻量） ---
    $os = Get-CimInstance Win32_OperatingSystem -ErrorAction SilentlyContinue
    $freePhysKB = $null; $totalPhysKB = $null; $commitLimitKB = $null; $commitFreeKB = $null
    if ($os) {
        $freePhysKB   = [double]$os.FreePhysicalMemory
        $totalPhysKB  = [double]$os.TotalVisibleMemorySize
        $commitLimitKB = [double]$os.TotalVirtualMemorySize
        $commitFreeKB  = [double]$os.FreeVirtualMemory
    }
    # --- WSL VM 宿主进程（不触碰 guest） ---
    $vm = @()
    foreach ($p in (Get-Process -Name "vmmem*","WslService" -ErrorAction SilentlyContinue)) {
        $vm += @{ name=$p.Name; pid=$p.Id; ws_mb=[math]::Round($p.WorkingSet64/1MB,1);
                  priv_mb=[math]::Round($p.PrivateMemorySize64/1MB,1) }
    }
    # --- 卷可见性（bool，不触发重扫描） ---
    $vols = @{ C=(Test-Path "C:\"); E=(Test-Path "E:\"); F=(Test-Path "F:\") }

    # --- 采样器自身开销 ---
    $self = Get-Process -Id $thisProc -ErrorAction SilentlyContinue
    $selfWs = if ($self) { [math]::Round($self.WorkingSet64/1MB,1) } else { $null }

    $rec = @{ event="sample"; utc=$now; os=@{ free_phys_gb=[math]::Round($freePhysKB/1MB,3);
            total_phys_gb=[math]::Round($totalPhysKB/1MB,3);
            commit_limit_gb=[math]::Round($commitLimitKB/1MB,3);
            commit_used_gb=[math]::Round(($commitLimitKB-$commitFreeKB)/1MB,3) };
        vm=$vm; vols=$vols; sampler_self_ws_mb=$selfWs }

    # --- 低频进程明细（目标重任务族聚合） ---
    $detailCount++
    if ($DetailEvery -gt 0 -and ($detailCount % $DetailEvery) -eq 0) {
        $heavy = Get-Process -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -match '^(python|python3|wsl|bash|conda|pytest)' } |
            Group-Object Name | ForEach-Object {
                @{ name=$_.Name; n=$_.Count;
                   ws_mb=[math]::Round(($_.Group | Measure-Object WorkingSet64 -Sum).Sum/1MB,1) }
            }
        $rec["heavy_procs"] = $heavy
    }
    Write-JsonLine $rec

    # --- B4 保护线检查（只记录+落 marker，不杀任何进程） ---
    if ($null -ne $freePhysKB -and $totalPhysKB -gt 0) {
        $freeGB = $freePhysKB/1MB
        if ($freeGB -lt 4) { $lowFreeStreak++ } else { $lowFreeStreak = 0 }
        $commitPct = if ($commitLimitKB -gt 0) { 100*($commitLimitKB-$commitFreeKB)/$commitLimitKB } else { -1 }
        if ($commitPct -ge 95) { $highCommitStreak++ } else { $highCommitStreak = 0 }
        if ($lowFreeStreak -ge 3 -or $highCommitStreak -ge 3) {
            Write-JsonLine @{ event="protection_stop"; utc=$now;
                free_phys_gb=[math]::Round($freeGB,3);
                commit_used_pct=[math]::Round($commitPct,2);
                low_free_streak=$lowFreeStreak; high_commit_streak=$highCommitStreak }
            if (-not (Test-Path $StopMarker)) {
                Set-Content -Path $StopMarker -Value ("protection_stop at " + $now)
            }
        }
    }

    # --- 卷失联事件（E/F 掉线即时记录） ---
    if (-not $vols.E) {
        Write-JsonLine @{ event="vol_missing"; utc=$now; vol="E" }
    }
    if (-not $vols.F) {
        Write-JsonLine @{ event="vol_missing"; utc=$now; vol="F" }
    }

    if ($MaxSeconds -gt 0 -and ((Get-Date) - $start).TotalSeconds -ge $MaxSeconds) {
        Write-JsonLine @{ event="sampler_end"; utc=(Get-UtcNowIso); reason="max_seconds" }
        break
    }
    Start-Sleep -Seconds $IntervalSeconds
}
