# 평균 시나리오 벽 좁히기: 동시 15명 (10 통과 / 20 실패 사이)
$env:PREPARE_SECONDS = "10"
$env:ANSWER_SECONDS = "75"
$env:START_JITTER_SECONDS = "85"
Remove-Item Env:\MAX_ANSWERS -ErrorAction SilentlyContinue
Remove-Item Env:\STUB_STT -ErrorAction SilentlyContinue
Set-Location "C:\Users\main\Desktop\ai-team3\load_test"
& ".\run.ps1" -Scenario "10_interview.js" -Levels "15"
