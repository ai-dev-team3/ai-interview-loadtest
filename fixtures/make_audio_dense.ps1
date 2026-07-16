# Build DENSE per-length answer audio (webm) for the "average" scenario.
#
# 기존 make_audio.ps1 은 30/60/90초 3개만 잘랐다. 실제 사용자의 답변 길이는 연속적이라
# 3개 버킷(특히 30%가 90초 최악값에 고정)은 STT 부하의 꼬리를 과장한다. 여기서는
# 30~90초를 2초 간격(31개)으로 촘촘하게 잘라, config.js 의 pickAnswer 가 연속 분포를
# 재현할 수 있게 한다. 나머지는 make_audio.ps1 과 동일(같은 TTS, 무음 금지).

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$wav = Join-Path $here "_full.wav"
$txtPath = Join-Path $here "answer_text.txt"

$para = Get-Content -Raw -Encoding UTF8 $txtPath
$text = $para + "`n" + $para   # repeat to guarantee 100s+ (we cut to 90 max)

Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$synth.SelectVoice("Microsoft Heami Desktop")   # ko-KR
$synth.Rate = 1
$synth.SetOutputToWaveFile($wav)
$synth.Speak($text)
$synth.Dispose()

$full = ffprobe -v error -show_entries format=duration -of csv=p=0 $wav
Write-Output ("synth length: " + $full + "s")

$count = 0
for ($sec = 30; $sec -le 90; $sec += 2) {
    $out = Join-Path $here ("answer_" + $sec + "s.webm")
    ffmpeg -y -loglevel error -t $sec -i $wav -c:a libopus -b:a 32k $out
    $count += 1
}
Write-Output ("wrote " + $count + " files: answer_30s..answer_90s (2s step)")

# Default single-audio (burst / ws scenarios) = 60s copy
Copy-Item (Join-Path $here "answer_60s.webm") (Join-Path $here "answer.webm") -Force
Remove-Item $wav
Write-Output "default answer.webm = 60s copy"
