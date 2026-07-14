# 시나리오를 동시 사용자 수를 올려가며 차례로 돌리고, 결과 요약을 out/ 에 남긴다.
#
#   .\run.ps1 -Scenario 10_interview.js -Levels 5,10,15,20,30
#   .\run.ps1 -Scenario 20_answer_burst.js -Levels 1,2,4,8,16
#   .\run.ps1 -Scenario 30_ws_only.js -Levels 10,20,30
#
# 각 실행은 k6 의 임계값(SLO) 통과 여부를 종료 코드로 알려준다.
# 처음으로 실패한 레벨이 곧 '동시 사용자 한계'다.

param(
    [string]$Scenario = "10_interview.js",
    [int[]]$Levels = @(5),
    [hashtable]$Env = @{}
)

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$k6 = Join-Path $here "bin\k6.exe"
$out = Join-Path $here "out"
New-Item -ItemType Directory -Force $out | Out-Null

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$name = [System.IO.Path]::GetFileNameWithoutExtension($Scenario)

foreach ($vus in $Levels) {
    $summary = Join-Path $out "$name-vus$vus-$stamp.json"
    Write-Host "`n=== $Scenario | 동시 $vus 명 ===" -ForegroundColor Cyan

    $args = @("run", "-e", "VUS=$vus", "--summary-export=$summary")
    foreach ($k in $Env.Keys) { $args += @("-e", "$k=$($Env[$k])") }
    $args += (Join-Path $here "scenarios\$Scenario")

    & $k6 @args
    $code = $LASTEXITCODE

    if ($code -eq 0) {
        Write-Host "동시 $vus 명: SLO 통과" -ForegroundColor Green
    } else {
        # k6 는 임계값을 하나라도 못 지키면 99 로 끝난다.
        Write-Host "동시 $vus 명: SLO 실패 (exit $code) -> 여기가 한계다. 요약: $summary" -ForegroundColor Red
        break
    }
}
