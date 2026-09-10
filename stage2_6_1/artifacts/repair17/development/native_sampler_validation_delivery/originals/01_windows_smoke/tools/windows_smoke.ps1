# Native host tests only. No courses, qualification state, or blanket process kills.
param([Parameter(Mandatory=$true)][string]$RunnerDirectory,
      [Parameter(Mandatory=$true)][string]$TestRoot)
$ErrorActionPreference='Stop'
if (Test-Path -LiteralPath $TestRoot) { throw 'Use a new TestRoot; no overwrite' }
[IO.Directory]::CreateDirectory($TestRoot) | Out-Null
$RunnerDirectory=[IO.Path]::GetFullPath($RunnerDirectory)
$TestRoot=[IO.Path]::GetFullPath($TestRoot)
$ps=Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'
$results=@();$owned=@()
function Q([string]$s) { return "'"+$s.Replace("'","''")+"'" }
function Encode([string]$s) { return [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($s)) }
function Spawn([string]$Body) {
    $si=[Diagnostics.ProcessStartInfo]::new()
    $si.FileName=$ps;$si.Arguments='-NoProfile -EncodedCommand '+(Encode $Body)
    $si.UseShellExecute=$false;$si.CreateNoWindow=$true
    return [Diagnostics.Process]::Start($si)
}
function AwaitFile([string]$p,[int]$Ms) {
    $clock=[Diagnostics.Stopwatch]::StartNew()
    while (-not [IO.File]::Exists($p)) {
        if ($clock.ElapsedMilliseconds -ge $Ms) { throw ('File timeout: '+$p) }
        Start-Sleep -Milliseconds 50
    }
    return ([IO.File]::ReadAllText($p) | ConvertFrom-Json)
}
function Hash([string]$p) { return (Get-FileHash -LiteralPath $p -Algorithm SHA256).Hash.ToLowerInvariant() }
function NativeAlive($id) {
    try {
        $p=[Diagnostics.Process]::GetProcessById([int]$id.pid)
        try { return (-not $p.HasExited -and $p.StartTime.ToUniversalTime().ToFileTimeUtc().ToString() -eq $id.creation_filetime) }
        finally { $p.Dispose() }
    } catch [ArgumentException] { return $false }
}
try {
    foreach ($name in @('r17_win_sampler.ps1','r17_win_sampler_control.ps1','r17_win_sampler_lifecycle.ps1')) {
        $tokens=$null;$errors=$null
        [System.Management.Automation.Language.Parser]::ParseFile((Join-Path $RunnerDirectory $name),[ref]$tokens,[ref]$errors) | Out-Null
        if ($errors.Count) { throw ($name+': '+($errors | Out-String)) }
    }
    Add-Type -Path (Join-Path $RunnerDirectory 'r17_win_process.cs') -ErrorAction Stop
    . (Join-Path $RunnerDirectory 'r17_win_sampler_lifecycle.ps1')
    foreach ($kind in @('cooperative','detached','forced','wrong_creation')) {
        $dir=Join-Path $TestRoot $kind;[IO.Directory]::CreateDirectory($dir) | Out-Null
        $control=Join-Path $dir 'control';[IO.Directory]::CreateDirectory($control) | Out-Null
        $out=Join-Path $dir 'samples.jsonl'
        $token=([guid]::NewGuid().ToString('N')+[guid]::NewGuid().ToString('N'))
        $rid='native_'+$kind+'_'+[guid]::NewGuid().ToString('N')
        $fixture=$kind -in @('forced','wrong_creation')
        $script=if ($fixture) { Join-Path $PSScriptRoot 'native_test_writer.ps1' } else { Join-Path $RunnerDirectory 'r17_win_sampler.ps1' }
        $body='& '+(Q $script)+' -RunId '+(Q $rid)+' -OutFile '+(Q $out)+
            ' -ControlDirectory '+(Q $control)+' -InstanceToken '+(Q $token)
        if ($fixture) { $body+=' -RunnerDirectory '+(Q $RunnerDirectory) }
        else { $body+=' -MaxSeconds 60 -IntervalSeconds 1 -Volumes '+(Q 'C:,F:') }
        if ($kind -eq 'detached') {
            # Real Windows launcher exits while the native sampler is detached.
            $encoded=Encode $body
            $launcher=Spawn ('Start-Process -FilePath '+(Q $ps)+
                ' -ArgumentList @('+(Q '-NoProfile')+','+(Q '-EncodedCommand')+','+(Q $encoded)+') | Out-Null')
            if (-not $launcher.WaitForExit(10000)) { throw 'Detached launcher did not exit' }
        } else { $launcher=Spawn $body }
        $id=AwaitFile (Join-Path $control 'identity.json') 25000
        $owned+=@{id=$id;dir=$dir}
        if ($id.token -cne $token -or $id.run_id -cne $rid) { throw 'Identity mismatch' }
        if (-not (NativeAlive $id)) { throw 'Native writer did not start' }
        $transportExited=if ($kind -eq 'detached') { $launcher.HasExited } else { $null }
        $launcher.Dispose()
        $request=@{protocol='r17-native-sampler-v1';run_id=$rid;token=$token;
            pid=$id.pid;creation_filetime=$id.creation_filetime;
            cooperate_ms=4000;force_wait_ms=4000;budget_ms=15000;
            expires_utc=[DateTime]::UtcNow.AddSeconds(15).ToString('o')}
        if ($kind -eq 'wrong_creation') {
            $request.creation_filetime=([UInt64]::Parse($id.creation_filetime)+1).ToString()
        } else {
            Write-R17NewJson (Join-Path $control 'stop.json') @{
                protocol='r17-native-sampler-v1';run_id=$rid;token=$token}
        }
        $req=Join-Path $control 'native_request.json';Write-R17NewJson $req $request
        $controller=Spawn ('& '+(Q (Join-Path $RunnerDirectory 'r17_win_sampler_control.ps1'))+' -RequestFile '+(Q $req))
        if (-not $controller.WaitForExit(25000)) { $controller.Kill();throw 'Controller watchdog expired (not product success)' }
        $controllerRc=$controller.ExitCode;$controller.Dispose()
        $proof=AwaitFile (Join-Path $control 'native_confirmation.json') 1000
        $alive=NativeAlive $id
        if ($kind -eq 'wrong_creation') {
            if (-not $alive -or $proof.forced -or $proof.identity_matched) { throw 'Wrong creation time affected actual writer' }
        } else {
            if ($alive -or -not $proof.native_exited) { throw 'Writer still alive after claimed exit' }
            $h0=Hash $out;$n0=(Get-Item -LiteralPath $out).Length
            Start-Sleep -Seconds 12
            if ((Hash $out) -ne $h0 -or (Get-Item -LiteralPath $out).Length -ne $n0) { throw 'Telemetry grew after native exit' }
            if ($kind -eq 'forced') {
                if (-not $proof.forced -or [IO.File]::Exists((Join-Path $control 'terminal.json'))) {
                    throw 'Forced fixture falsely has a clean terminal'
                }
            } else {
                $terminal=AwaitFile (Join-Path $control 'terminal.json') 1000
                if (-not $terminal.clean -or $terminal.reason -ne 'stop_requested' -or
                    $terminal.sha256 -ne $h0 -or $terminal.bytes -ne $n0) { throw 'Terminal/bytes mismatch' }
            }
        }
        $results+=@{case=$kind;ok=$true;native_identity=$id;proof=$proof;
            controller_rc=$controllerRc;actual_native_alive=$alive;
            launcher_exited_before_stop=$transportExited}
    }
    Write-R17NewJson (Join-Path $TestRoot 'result.json') @{ok=$true;cases=$results}
    Write-Output ('native_windows_tests=PASS; results='+$TestRoot)
} catch {
    $errorText=$_.Exception.ToString()
    try { Write-R17NewJson (Join-Path $TestRoot 'failure.json') @{ok=$false;error=$errorText;cases=$results} } catch { }
    throw
} finally {
    # Test cleanup is separate from product success; only exact instances created by this test.
    foreach ($obj in $owned) {
        $id=$obj.id
        if (NativeAlive $id) {
            $cleanup=[R17Sampler.Native]::Stop([int]$id.pid,[string]$id.creation_filetime,
                0,3000,4000,[DateTime]::UtcNow.AddSeconds(4).ToString('o'))
            try { Write-R17NewJson (Join-Path $obj.dir 'test_cleanup.json') $cleanup } catch { }
        }
    }
}
