# 평균 시나리오: 실제 STT, LLM 2.0초, 12분 면접, 도착 지터 85초(lockstep 방지), 답변 캡 없음
$env:PREPARE_SECONDS = "10"
$env:ANSWER_SECONDS = "75"
$env:START_JITTER_SECONDS = "85"
Remove-Item Env:\MAX_ANSWERS -ErrorAction SilentlyContinue
Remove-Item Env:\STUB_STT -ErrorAction SilentlyContinue
Set-Location "C:\Users\main\Desktop\ai-team3\load_test"
& ".\run.ps1" -Scenario "10_interview.js" -Levels "10,20,30"
