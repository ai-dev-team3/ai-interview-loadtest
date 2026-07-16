# 평균(밀집) 시나리오 상위 스윕: 25명이 여유롭게 통과해 천장을 더 위에서 찾는다.
$env:PREPARE_SECONDS = "10"
$env:ANSWER_SECONDS = "75"
$env:START_JITTER_SECONDS = "85"
Remove-Item Env:\MAX_ANSWERS -ErrorAction SilentlyContinue
Remove-Item Env:\STUB_STT -ErrorAction SilentlyContinue
Remove-Item Env:\FORCE_ANSWER -ErrorAction SilentlyContinue
Set-Location "C:\Users\main\Desktop\ai-team3\load_test"
& ".\run.ps1" -Scenario "10_interview.js" -Levels "30,35,40"
