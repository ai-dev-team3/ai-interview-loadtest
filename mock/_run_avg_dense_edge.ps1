# 평균(밀집) 시나리오 경계 탐색: 25명 통과 / 30명 실패 사이의 정확한 한계.
$env:PREPARE_SECONDS = "10"
$env:ANSWER_SECONDS = "75"
$env:START_JITTER_SECONDS = "85"
Remove-Item Env:\MAX_ANSWERS -ErrorAction SilentlyContinue
Remove-Item Env:\STUB_STT -ErrorAction SilentlyContinue
Remove-Item Env:\FORCE_ANSWER -ErrorAction SilentlyContinue
Set-Location "C:\Users\main\Desktop\ai-team3\load_test"
& ".\run.ps1" -Scenario "10_interview.js" -Levels "26,27,28"
