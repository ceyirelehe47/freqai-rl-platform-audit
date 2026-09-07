# R17 Windows 采样器 v2(任务书 WP2;自 blocker_diagnosis/observers/
# win_sampler.ps1 提取修正)。
# 修正点(审查记录 §7-8/§7-13):
#  - commit 口径:GetPerformanceInfo 的 CommitTotal/CommitLimit(页数 x
#    结构返回 PageSize),不再使用语义不明的 CIM 虚拟内存字段;
#  - RunId/OutFile/MaxSeconds 必填且无绝对缺省路径;MaxSeconds>0 强制
#    (supervisor 先死时采样器不无限写盘);
#  - 关键卷:可用空间+预登记卷身份(SerialNumber)+低频真实可写探测
#    (写 1KB 临时文件后删;盘符可见不等于关键文件可写);
#  - 应急保存:EmergencyDir(C: LOCALAPPDATA 下,独立故障域,不与
#    active VHDX 共用 F:);guest 失联(vmmem 消失)等关键事件双写;
#  - 输出 UTF-8 无 BOM 追加,容忍读取端只取完整行。
# 启动(guest 内 interop,路径经 wslpath -w 转 Windows 绝对路径):
#   powershell.exe -NoProfile -ExecutionPolicy Bypass -File <win路径>.ps1
#     -RunId <id> -OutFile <win路径>.jsonl -MaxSeconds <sec>
#     -Volumes "C:,F:" -EmergencyDir <win路径目录>
param(
    [Parameter(Mandatory=$true)][string]$RunId,
    [Parameter(Mandatory=$true)][string]$OutFile,
    [Parameter(Mandatory=$true)][ValidateRange(1, 2147483647)][int]$MaxSeconds,
    [int]$IntervalSeconds = 5,
    [int]$DetailEvery = 6,
    [string]$Volumes = "C:,F:",
    [string]$EmergencyDir = "",
    [int]$WriteProbeEvery = 6
)

$ErrorActionPreference = "Continue"
$thisPid = $PID
$utf8nb = New-Object System.Text.UTF8Encoding($false)
$script:emergencyAvailable = $false
if ($EmergencyDir -ne "") {
    try {
        if (-not (Test-Path $EmergencyDir)) {
            New-Item -ItemType Directory -Path $EmergencyDir -Force | Out-Null
        }
        $script:emergencyAvailable = $true
    } catch { $script:emergencyAvailable = $false }
}

function Write-JsonLine([object]$obj) {
    try {
        $line = $obj | ConvertTo-Json -Compress -Depth 6
        [System.IO.File]::AppendAllText($OutFile, $line + "`n", $utf8nb)
    } catch { }
}

function Write-Emergency([object]$obj) {
    if (-not $script:emergencyAvailable) { return }
    try {
        $line = $obj | ConvertTo-Json -Compress -Depth 6
        $stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmss")
        [System.IO.File]::AppendAllText(
            (Join-Path $EmergencyDir ("emergency_" + $RunId + ".jsonl")),
            $line + "`n", $utf8nb)
    } catch { }
}

function Get-UtcNowIso {
    return (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ss.fffZ")
}

# ---- GetPerformanceInfo(P/Invoke;commit 与物理内存的正式口径) ----
$perfOk = $false
$pageSize = 0
try {
    Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public static class R17PerfInfo {
  // psapi.h:cb=DWORD,其余字段=SIZE_T(x64 上 8 字节)
  [StructLayout(LayoutKind.Sequential)]
  public struct PERFORMANCE_INFORMATION {
    public int cb;
    public IntPtr CommitTotal, CommitLimit, CommitPeak, PhysicalTotal,
               PhysicalAvailable, SystemCache, KernelTotal, KernelPaged,
               KernelNonpaged, PageSize, HandleCount, ProcessCount,
               ThreadCount;
    public static int SizeOf() {
      return Marshal.SizeOf(typeof(PERFORMANCE_INFORMATION));
    }
  }
  [DllImport("psapi.dll", SetLastError=true)]
  public static extern bool GetPerformanceInfo(
    ref PERFORMANCE_INFORMATION p, int cb);
}
"@ -ErrorAction Stop
    $perfOk = $true
} catch { $perfOk = $false }

function Get-PerfMem {
    if (-not $perfOk) { return $null }
    $pi = New-Object R17PerfInfo+PERFORMANCE_INFORMATION
    $pi.cb = [R17PerfInfo+PERFORMANCE_INFORMATION]::SizeOf()
    if ([R17PerfInfo]::GetPerformanceInfo([ref]$pi, $pi.cb)) {
        $ps = [double]$pi.PageSize.ToInt64()
        $script:pageSize = $ps
        $gb = $ps / 1GB
        return @{
            commit_total_gb  = [math]::Round([double]$pi.CommitTotal.ToInt64() * $gb, 3)
            commit_limit_gb  = [math]::Round([double]$pi.CommitLimit.ToInt64() * $gb, 3)
            phys_total_gb    = [math]::Round([double]$pi.PhysicalTotal.ToInt64() * $gb, 3)
            phys_avail_gb    = [math]::Round([double]$pi.PhysicalAvailable.ToInt64() * $gb, 3)
            page_size_b      = $ps
        }
    }
    return $null
}

# ---- 关键卷清单(去尾反斜杠;盘符字母) ----
$volList = @($Volumes -split "," | ForEach-Object { $_.Trim().TrimEnd('\') } |
    Where-Object { $_ -ne "" })
$allDisks = @()
try {
    $allDisks = @(Get-CimInstance Win32_LogicalDisk -ErrorAction Stop)
} catch {
    $allDisks = @()
    Write-JsonLine @{ event="cim_disk_query_failed"; utc=(Get-UtcNowIso);
        err=($_.Exception.GetType().Name + ": " + $_.Exception.Message) }
}
$volIdentity = @{}
foreach ($v in $volList) {
    $d = $allDisks | Where-Object { $_.DeviceID -eq $v } | Select-Object -First 1
    if ($d) { $volIdentity[$v] = [string]$d.VolumeSerialNumber }
    else { $volIdentity[$v] = "unavailable" }
}

Write-JsonLine @{ event="sampler_start"; utc=(Get-UtcNowIso); pid=$thisPid;
    run_id=$RunId; interval_s=$IntervalSeconds; max_seconds=$MaxSeconds;
    volumes=$volList; vol_identity=$volIdentity;
    n_disks=@($allDisks).Count;
    perf_api_ok=$perfOk; emergency_dir=$EmergencyDir }

$start = Get-Date
$detailCount = 0
$probeCount = 0
$seq = 0           # WP3: source sequence (reader rejects dup/regress)
$lastVmPresent = $true
while ($true) {
    $now = Get-UtcNowIso
    $seq = $seq + 1
    $perf = Get-PerfMem
    # 每轮刷新卷表(避免陈旧)
    $allDisks = @()
    try { $allDisks = @(Get-CimInstance Win32_LogicalDisk -ErrorAction Stop) } catch { $allDisks = @() }

    # ---- vmmem/WslService(不触碰 guest) ----
    $vm = @()
    foreach ($p in (Get-Process -Name "vmmem*","WslService" -ErrorAction SilentlyContinue)) {
        $startUtc = $null
        if ($p.StartTime) {
            $startUtc = $p.StartTime.ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
        }
        $vm += @{ name=$p.Name; pid=$p.Id;
                  ws_mb=[math]::Round($p.WorkingSet64/1MB,1);
                  priv_mb=[math]::Round($p.PrivateMemorySize64/1MB,1);
                  start_utc=$startUtc }
    }
    $vmPresent = ($vm | Where-Object { $_.name -like "vmmem*" }).Count -gt 0
    if ($lastVmPresent -and -not $vmPresent) {
        $ev = @{ event="guest_vm_gone"; utc=$now; run_id=$RunId }
        Write-JsonLine $ev
        Write-Emergency $ev
    }
    $lastVmPresent = $vmPresent

    # ---- 关键卷状态(空间+身份核对) ----
    $volState = @()
    foreach ($v in $volList) {
        try {
            $d = $allDisks | Where-Object { $_.DeviceID -eq $v } | Select-Object -First 1
            if ($d) {
                $serial = [string]$d.VolumeSerialNumber
                $volState += @{ vol=$v; present=$true;
                    free_gb=[math]::Round($d.FreeSpace/1GB,2);
                    size_gb=[math]::Round($d.Size/1GB,1);
                    serial=$serial;
                    identity_match=($serial -eq $volIdentity[$v]) }
            } else {
                $volState += @{ vol=$v; present=$false }
            }
        } catch {
            $volState += @{ vol=$v; present=$false; error="query_failed" }
        }
    }

    # ---- low-freq write probe: actual evidence dirs (telemetry out +
    #      emergency); NOT volume roots (non-admin has no root write).
    #      First loop probes immediately ($probeCount starts at 0,
    #      ++ after the check): admission requires the very first
    #      sample to carry a real writable result (unknown != true).
    if ($WriteProbeEvery -gt 0 -and ($probeCount % $WriteProbeEvery) -eq 0) {
        $probeTag = "r17_probe_" + $RunId + ".tmp"
        try {
            $p1 = Join-Path (Split-Path -Parent $OutFile) $probeTag
            [System.IO.File]::WriteAllText($p1, "probe $now")
            Remove-Item $p1 -Force -ErrorAction Stop
            $script:outWritable = $true
        } catch { $script:outWritable = $false }
        if ($script:emergencyAvailable) {
            try {
                $p2 = Join-Path $EmergencyDir $probeTag
                [System.IO.File]::WriteAllText($p2, "probe $now")
                Remove-Item $p2 -Force -ErrorAction Stop
                $script:emWritable = $true
            } catch { $script:emWritable = $false }
        } else { $script:emWritable = $null }
    }
    $detailCount++
    $probeCount++

    $self = Get-Process -Id $thisPid -ErrorAction SilentlyContinue
    $rec = @{ event="sample"; utc=$now; run_id=$RunId; seq=$seq;
        perf=$perf; vm=$vm; vols=$volState;
        telemetry_out_writable=$script:outWritable;
        emergency_writable=$script:emWritable;
        sampler_self_ws_mb=$(if ($self) { [math]::Round($self.WorkingSet64/1MB,1) } else { $null }) }

    # ---- 低频 heavy 进程明细(聚合,不逐进程转储) ----
    if ($DetailEvery -gt 0 -and ($detailCount % $DetailEvery) -eq 0) {
        $heavy = Get-Process -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -match '^(python|python3|wsl|bash|conda|pytest|powershell)' } |
            Group-Object Name | ForEach-Object {
                @{ name=$_.Name; n=$_.Count;
                   ws_mb=[math]::Round(($_.Group | Measure-Object WorkingSet64 -Sum).Sum/1MB,1) }
            }
        $rec["heavy_procs"] = $heavy
    }
    Write-JsonLine $rec

    # ---- 关键卷事故事件(E 不在清单时不产生任何事件) ----
    foreach ($vs in $volState) {
        if (-not $vs.present) {
            $ev = @{ event="vol_missing"; utc=$now; run_id=$RunId; vol=$vs.vol }
            Write-JsonLine $ev; Write-Emergency $ev
        }
    }
    if ($script:outWritable -eq $false) {
        $ev = @{ event="evidence_write_failed"; utc=$now; run_id=$RunId;
            where="telemetry_out" }
        Write-JsonLine $ev; Write-Emergency $ev
    }

    if (((Get-Date) - $start).TotalSeconds -ge $MaxSeconds) {
        Write-JsonLine @{ event="sampler_end"; utc=(Get-UtcNowIso);
            reason="max_seconds" }
        break
    }
    Start-Sleep -Seconds $IntervalSeconds
}
