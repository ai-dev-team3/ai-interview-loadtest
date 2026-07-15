# Build per-length answer audio (webm) for load tests.
#
# Real users answer for different durations (30s / 60s / 90s max), so STT time must vary
# too. We synthesize one long speech and cut it to 30/60/90s (real speech, exact length).
#
# Korean TTS text lives in answer_text.txt (UTF-8) so this .ps1 stays ASCII — PowerShell 5.1
# mis-parses UTF-8 Korean embedded in a script. Silence/tone is NOT allowed: empty STT makes
# the server skip the LLM eval path (real_interview.py:137,261) and understates load.

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

foreach ($sec in 30, 60, 90) {
    $out = Join-Path $here ("answer_" + $sec + "s.webm")
    ffmpeg -y -loglevel error -t $sec -i $wav -c:a libopus -b:a 32k $out
    $dur = ffprobe -v error -show_entries format=duration -of csv=p=0 $out
    $kb = [math]::Round((Get-Item $out).Length / 1KB, 1)
    Write-Output ("  answer_" + $sec + "s.webm : " + $kb + " KB, " + $dur + "s")
}

# Default single-audio (burst / ws scenarios) = 60s copy
Copy-Item (Join-Path $here "answer_60s.webm") (Join-Path $here "answer.webm") -Force
Remove-Item $wav
Write-Output "default answer.webm = 60s copy"
