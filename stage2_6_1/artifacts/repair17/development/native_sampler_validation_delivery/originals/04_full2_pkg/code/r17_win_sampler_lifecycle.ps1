# Dot-sourced by the sampler only. The sampler remains the sole telemetry writer.
# All protocol files are per-launch, create-only UTF-8 JSON. No stdout protocol.
$script:r17NativeSource = Join-Path $PSScriptRoot 'r17_win_process.cs'
$script:r17LifecycleScript = $PSCommandPath
function Write-R17NewJson([string]$Path, [object]$Value) {
    $tmp = $Path + "." + [guid]::NewGuid().ToString("N") + ".tmp"
    $created = $false
    try {
        $bytes = [System.Text.UTF8Encoding]::new($false).GetBytes(($Value | ConvertTo-Json -Compress -Depth 10))
        $f = [System.IO.File]::Open($tmp, [System.IO.FileMode]::CreateNew,
            [System.IO.FileAccess]::Write, [System.IO.FileShare]::Read)
        $created = $true
        try { $f.Write($bytes, 0, $bytes.Length); $f.Flush($true) } finally { $f.Dispose() }
        # .NET Framework's two-argument Move refuses an existing destination.
        [System.IO.File]::Move($tmp, $Path)
    } finally {
        if ($created -and [System.IO.File]::Exists($tmp)) { [System.IO.File]::Delete($tmp) }
    }
}
function Initialize-R17SamplerLifecycle {
    if ($InstanceToken -notmatch '^[a-f0-9]{64}$' -or [string]::IsNullOrWhiteSpace($ControlDirectory)) {
        throw "Missing per-launch sampler control identity"
    }
    if (-not [System.IO.Directory]::Exists($ControlDirectory)) { throw "Control directory not prepared" }
    Add-Type -Path $script:r17NativeSource -ErrorAction Stop
    $script:r17Creation = [R17Sampler.Native]::CurrentCreation()
    $script:r17TelemetryWriteFailed = $false
    $script:r17FinishDone = $false
    $script:r17StopReason = 'unexpected_exit'
    $script:r17OutPath = [System.IO.Path]::GetFullPath($OutFile)
    # Never append to an old run's file, even if this process started twice.
    $out = [System.IO.File]::Open($script:r17OutPath,[System.IO.FileMode]::CreateNew,
        [System.IO.FileAccess]::Write,[System.IO.FileShare]::Read)
    $out.Dispose()
    $script:r17Identity = @{
        protocol='r17-native-sampler-v1'; run_id=$RunId; token=$InstanceToken;
        pid=$PID; creation_filetime=$script:r17Creation; out_file=$script:r17OutPath;
        lifecycle_script=$script:r17LifecycleScript; started_utc=[DateTime]::UtcNow.ToString('o')
    }
    Write-R17NewJson (Join-Path $ControlDirectory 'identity.json') $script:r17Identity
}
function Test-R17SamplerStop {
    $p = Join-Path $ControlDirectory 'stop.json'
    if (-not [System.IO.File]::Exists($p)) { return $false }
    # A broken request never grants authority to a different run. MaxSeconds remains a backstop.
    try {
        $s = [System.IO.File]::ReadAllText($p) | ConvertFrom-Json -ErrorAction Stop
        return ($s.protocol -eq 'r17-native-sampler-v1' -and
                $s.run_id -ceq $RunId -and $s.token -ceq $InstanceToken)
    } catch { return $false }
}
function Wait-R17SamplerInterval([int]$Seconds) {
    $until = [System.Diagnostics.Stopwatch]::StartNew()
    do {
        if (Test-R17SamplerStop) { return $true }
        if ($until.Elapsed.TotalSeconds -ge $Seconds) { return $false }
        Start-Sleep -Milliseconds 100
    } while ($true)
}
function Complete-R17SamplerLifecycle {
    if ($script:r17FinishDone) { return }
    $script:r17FinishDone = $true
    $clean = (-not $script:r17TelemetryWriteFailed) -and ($script:r17StopReason -in @('stop_requested','max_seconds'))
    $err = $null
    try {
        # The LAST telemetry append. Nothing after this function writes telemetry.
        $end = @{
            event='sampler_end'; utc=[DateTime]::UtcNow.ToString('o'); run_id=$RunId;
            token=$InstanceToken; pid=$PID; creation_filetime=$script:r17Creation;
            reason=$script:r17StopReason
        }
        $line = $end | ConvertTo-Json -Compress -Depth 6
        [System.IO.File]::AppendAllText($script:r17OutPath,$line+"`n",[System.Text.UTF8Encoding]::new($false))
    } catch { $clean=$false; $err=$_.Exception.Message }
    $size = $null; $digest = $null
    try {
        # AppendAllText has closed its handle. Hash while disallowing another writer.
        $f = [System.IO.File]::Open($script:r17OutPath,[System.IO.FileMode]::Open,
            [System.IO.FileAccess]::Read,[System.IO.FileShare]::Read)
        $sha = [System.Security.Cryptography.SHA256]::Create()
        try { $size=$f.Length; $digest=([BitConverter]::ToString($sha.ComputeHash($f))).Replace('-','').ToLowerInvariant() }
        finally { $sha.Dispose(); $f.Dispose() }
    } catch { $clean=$false; $err=$_.Exception.Message }
    $terminal = @{
        protocol='r17-native-sampler-v1'; run_id=$RunId; token=$InstanceToken;
        pid=$PID; creation_filetime=$script:r17Creation; out_file=$script:r17OutPath;
        clean=$clean; reason=$script:r17StopReason; bytes=$size; sha256=$digest;
        finished_utc=[DateTime]::UtcNow.ToString('o'); error=$err
    }
    # This is a write-completion acknowledgement, NOT proof that the process exited.
    Write-R17NewJson (Join-Path $ControlDirectory 'terminal.json') $terminal
}
