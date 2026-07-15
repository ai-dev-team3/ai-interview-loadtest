# uvicorn 서버의 스레드 수 / 메모리 / GPU 를 2초마다 샘플, 피크와 시계열을 남긴다.
param([int]$Seconds = 600)
$out = "C:\Users\main\Desktop\ai-team3\load_test\out\threads.log"
"" | Out-File $out
$maxT = 0; $maxM = 0
$end = (Get-Date).AddSeconds($Seconds)
while ((Get-Date) -lt $end) {
    $proc = Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -match 'serve_mocked' }
    if ($proc) {
        $p = Get-Process -Id $proc.ProcessId -ErrorAction SilentlyContinue
        if ($p) {
            $t = $p.Threads.Count
            $m = [int]($p.WorkingSet64 / 1MB)
            $maxT = [Math]::Max($maxT, $t)
            $maxM = [Math]::Max($maxM, $m)
            $gpu = (& nvidia-smi --query-gpu=utilization.gpu,memory.used --format=csv,noheader,nounits) 2>$null
            "$(Get-Date -Format HH:mm:ss) threads=$t mem=${m}MB gpu=$gpu" | Out-File $out -Append
        }
    }
    Start-Sleep -Milliseconds 2000
}
"PEAK threads=$maxT mem=${maxM}MB" | Out-File $out -Append
