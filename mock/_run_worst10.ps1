# 최악 시나리오 동시 10명 단독 측정
& "C:\Users\main\Desktop\ai-team3\ai_interview-main\back_tooktac\.venv\Scripts\python.exe" `
    "C:\Users\main\Desktop\ai-team3\load_test\seed\seed.py" -n 60 | Out-Null
$env:PREPARE_SECONDS = "0"
$env:START_JITTER_SECONDS = "0"
$env:FORCE_ANSWER = "90"
$env:MAX_ANSWERS = "3"
Remove-Item Env:\STUB_STT -ErrorAction SilentlyContinue
Set-Location "C:\Users\main\Desktop\ai-team3\load_test"
& ".\run.ps1" -Scenario "10_interview.js" -Levels "10"
