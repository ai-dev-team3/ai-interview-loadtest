# 평균 + 서버 MediaPipe(JPEG): 랜덤 도착·랜덤 답변길이 + 접속마다 MediaPipe 그래프
# (토큰은 외부에서 갱신한다 — 이 스크립트는 시딩하지 않는다)
$env:VIDEO_MODE = "jpeg"
$env:PREPARE_SECONDS = "10"
$env:ANSWER_SECONDS = "75"
$env:START_JITTER_SECONDS = "85"
$env:MAX_ANSWERS = "3"
Remove-Item Env:\FORCE_ANSWER -ErrorAction SilentlyContinue
Remove-Item Env:\STUB_STT -ErrorAction SilentlyContinue
Set-Location "C:\Users\main\Desktop\ai-team3\load_test"
& ".\run.ps1" -Scenario "10_interview.js" -Levels "5,10,15"
