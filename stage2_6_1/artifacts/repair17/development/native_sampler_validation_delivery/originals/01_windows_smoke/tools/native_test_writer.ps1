# TEST ONLY: intentionally ignores stop.json; used to test native forced exit.
param([string]$RunnerDirectory,[string]$RunId,[string]$OutFile,
      [string]$ControlDirectory,[string]$InstanceToken)
$ErrorActionPreference='Stop'
. (Join-Path $RunnerDirectory 'r17_win_sampler_lifecycle.ps1')
Initialize-R17SamplerLifecycle
$clock=[Diagnostics.Stopwatch]::StartNew()
while ($clock.Elapsed.TotalSeconds -lt 90) {
    [IO.File]::AppendAllText($OutFile,"{`"test_writer`":true}`n",[Text.UTF8Encoding]::new($false))
    Start-Sleep -Milliseconds 200
}
# No clean terminal acknowledgement: a forced/incomplete stream must not be certified.
