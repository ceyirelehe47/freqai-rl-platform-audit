# A bounded native-handle controller, not a process-name killer.
param([Parameter(Mandatory=$true)][string]$RequestFile)
$ErrorActionPreference='Stop'
$request = $null
try {
    $request = [System.IO.File]::ReadAllText($RequestFile) | ConvertFrom-Json
    if ($request.protocol -ne 'r17-native-sampler-v1' -or $request.token -notmatch '^[a-f0-9]{64}$') {
        throw 'Invalid controller request'
    }
    . (Join-Path $PSScriptRoot 'r17_win_sampler_lifecycle.ps1')
    Add-Type -Path (Join-Path $PSScriptRoot 'r17_win_process.cs') -ErrorAction Stop
    $r = [R17Sampler.Native]::Stop([int]$request.pid,[string]$request.creation_filetime,
        [int]$request.cooperate_ms,[int]$request.force_wait_ms,[int]$request.budget_ms,
        [string]$request.expires_utc)
    $reply = @{
        protocol='r17-native-sampler-v1'; run_id=$request.run_id; token=$request.token;
        pid=$request.pid; creation_filetime=$request.creation_filetime;
        status=$r.Status; native_exited=$r.NativeExited; identity_matched=$r.IdentityMatched;
        forced=$r.Forced; actual_creation_filetime=$r.ActualCreation; win32_error=$r.Error;
        finished_utc=[DateTime]::UtcNow.ToString('o')
    }
    # Fixed sibling filename: caller cannot redirect the controller's output.
    Write-R17NewJson (Join-Path (Split-Path -Parent $RequestFile) 'native_confirmation.json') $reply
    if ($r.NativeExited) { exit 0 } else { exit 3 }
} catch {
    # Do not invent an exit confirmation on errors. Python records missing/invalid proof.
    [Console]::Error.WriteLine('Native sampler control failed: '+$_.Exception.Message)
    exit 4
}
