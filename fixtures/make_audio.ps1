# 부하 테스트용 답변 오디오(webm)를 만든다.
#
# 무음이나 톤 신호를 쓰면 안 된다. STT 가 빈 문자열을 돌려주면 서버는
# save_minimal_result 로 빠져 LLM 평가 경로를 아예 타지 않는다(real_interview.py:137,261).
# 그러면 가장 무거운 구간을 재놓고도 부하가 없는 것처럼 보인다.
# 그래서 실제 발화(한국어 TTS)를 넣는다.

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$wav = Join-Path $here "answer.wav"
$webm = Join-Path $here "answer.webm"

# 실제 답변 길이(준비 10초 / 답변 90초)에 맞춰 60초 안팎이 되도록 분량을 맞췄다.
$text = @"
네, 제가 맡았던 프로젝트에 대해 말씀드리겠습니다.
저는 면접 연습 서비스의 음성 처리 파이프라인을 담당했습니다.
사용자가 답변을 녹음해서 보내면, 서버가 그 음성을 텍스트로 바꾸고 평가하는 구조였습니다.
초기에는 요청이 몇 개만 동시에 들어와도 응답이 크게 느려지는 문제가 있었습니다.
저는 어느 구간에서 시간이 쓰이는지 측정한 뒤, 스레드풀 크기를 조정해서 개선했습니다.
이 경험을 통해 문제를 추측하지 않고 측정해서 좁혀 나가는 방법을 배웠습니다.
"@

Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$synth.SelectVoice("Microsoft Heami Desktop")   # ko-KR
$synth.Rate = 1
$synth.SetOutputToWaveFile($wav)
$synth.Speak($text)
$synth.Dispose()

# 서버가 받는 것과 같은 형식(webm/opus)으로 변환한다.
ffmpeg -y -loglevel error -i $wav -c:a libopus -b:a 32k $webm
Remove-Item $wav

$size = (Get-Item $webm).Length
$dur = (ffprobe -v error -show_entries format=duration -of csv=p=0 $webm)
"생성 완료: $webm ($([math]::Round($size/1KB,1)) KB, ${dur}초)"
