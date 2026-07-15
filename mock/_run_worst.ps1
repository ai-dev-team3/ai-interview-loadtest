# 최악 시나리오: 동기화 버스트 (평균 bisect 가 끝나면 이어서 실행).
#   - 도착 지터 0 + 준비 0초 -> 전원이 같은 순간 /answer 를 STT 에 던진다
#   - 답변 길이 90초 고정 -> 가장 무거운 STT 를 동시에 몰아친다
#   - MAX_ANSWERS=3 으로 각 면접을 짧게(측정엔 충분, 런타임 절약)
# 평균과 달리 "실제 사용자"가 아니라 "순간 최대 압력"을 본다.

# 1) 앞선 k6(평균 bisect)가 끝날 때까지 대기 — GPU 를 공유하므로 겹치면 둘 다 오염된다.
while (Get-Process k6 -ErrorAction SilentlyContinue) { Start-Sleep -Seconds 10 }
Start-Sleep -Seconds 5

# 2) 토큰 갱신 (120분 만료 대비)
& "C:\Users\main\Desktop\ai-team3\ai_interview-main\back_tooktac\.venv\Scripts\python.exe" `
    "C:\Users\main\Desktop\ai-team3\load_test\seed\seed.py" -n 60 | Out-Null

# 3) 최악 설정으로 램프
$env:PREPARE_SECONDS = "0"
$env:START_JITTER_SECONDS = "0"
$env:FORCE_ANSWER = "90"
$env:MAX_ANSWERS = "3"
Remove-Item Env:\STUB_STT -ErrorAction SilentlyContinue
Set-Location "C:\Users\main\Desktop\ai-team3\load_test"
& ".\run.ps1" -Scenario "10_interview.js" -Levels "5,10,20"
