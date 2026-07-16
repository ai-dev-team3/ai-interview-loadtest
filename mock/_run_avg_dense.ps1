# 평균 시나리오 (밀집 분포판): 답변 길이를 30~90초 2초 간격 삼각분포로 뽑는다.
# 실 STT, LLM 2.0초, 도착 지터 85초(lockstep 방지), 답변 캡 없음. 나머지는 _run_avg.ps1 과 동일.
$env:PREPARE_SECONDS = "10"
$env:ANSWER_SECONDS = "75"
$env:START_JITTER_SECONDS = "85"
Remove-Item Env:\MAX_ANSWERS -ErrorAction SilentlyContinue
Remove-Item Env:\STUB_STT -ErrorAction SilentlyContinue
Remove-Item Env:\FORCE_ANSWER -ErrorAction SilentlyContinue
Set-Location "C:\Users\main\Desktop\ai-team3\load_test"
& ".\run.ps1" -Scenario "10_interview.js" -Levels "15,20,25"
