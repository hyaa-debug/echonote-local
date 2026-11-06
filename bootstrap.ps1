param([switch]$PrepareAI)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'Continue'
$ProjectRoot = $PSScriptRoot
Set-Location -LiteralPath $ProjectRoot
$RuntimeDir = Join-Path $ProjectRoot '.runtime'
$DownloadDir = Join-Path $ProjectRoot '.downloads'
$LogDir = Join-Path $ProjectRoot 'data\logs'
New-Item -ItemType Directory -Force -Path $RuntimeDir,$DownloadDir,$LogDir | Out-Null
$TranscriptStarted = $false
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
function Download-File([string]$Url,[string]$Destination) {
    $Temporary = $Destination + '.part'
    for ($Attempt=1; $Attempt -le 3; $Attempt++) {
        try {
            Write-Host "Downloading: $Url (attempt $Attempt)"
            Invoke-WebRequest -Uri $Url -OutFile $Temporary -UseBasicParsing -TimeoutSec 900
            Move-Item -LiteralPath $Temporary -Destination $Destination -Force
            return
        } catch {
            if ($Attempt -eq 3) { throw }
            Start-Sleep -Seconds 2
        }
    }
}
function Find-Ollama {
    $Candidates = @(
      (Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'),
      (Join-Path $env:ProgramFiles 'Ollama\ollama.exe')
    )
    $Command = Get-Command ollama.exe -ErrorAction SilentlyContinue
    if ($Command) { return $Command.Source }
    foreach ($Candidate in $Candidates) { if (Test-Path -LiteralPath $Candidate) { return $Candidate } }
    return $null
}
function Ollama-Ready {
    try {
        $Response=Invoke-RestMethod 'http://127.0.0.1:11434/api/version' -TimeoutSec 2
        return [bool]$Response.version
    } catch { return $false }
}
try {
    if (-not [Environment]::Is64BitOperatingSystem) { throw 'Windows 64-bit is required.' }
    if (-not $PrepareAI) {
        try {
            $Running = Invoke-RestMethod 'http://127.0.0.1:8765/api/health' -TimeoutSec 2
            if ($Running.app -eq 'echonote-local') {
                Start-Process 'http://127.0.0.1:8765'; exit 0
            }
        } catch {}
    }
    Start-Transcript -Path (Join-Path $LogDir 'setup.log') -Append | Out-Null
    $TranscriptStarted = $true
    $Python = Join-Path $RuntimeDir 'python.exe'
    if (-not (Test-Path -LiteralPath $Python)) {
        Write-Host '[1/4] Preparing private Python 3.12. Your installed Python will not be changed.'
        $PythonZip = Join-Path $DownloadDir 'python-3.12.10-embed-amd64.zip'
        if (-not (Test-Path -LiteralPath $PythonZip)) {
            Download-File 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip' $PythonZip
        }
        Expand-Archive -LiteralPath $PythonZip -DestinationPath $RuntimeDir -Force
    }
    # Embedded Python uses only this application and its private dependencies.
    @('python312.zip','.','Lib\site-packages','..','import site') | Set-Content -LiteralPath (Join-Path $RuntimeDir 'python312._pth') -Encoding ASCII
    & $Python (Join-Path $ProjectRoot 'ensure_compat.py')
    if ($LASTEXITCODE -ne 0) { throw 'Offline compatibility repair failed. Please use the repair package.' }
    $SavedPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    & $Python -m pip --version *> $null
    $PipCheck = $LASTEXITCODE
    $ErrorActionPreference = $SavedPreference
    if ($PipCheck -ne 0) {
        $GetPip = Join-Path $DownloadDir 'get-pip.py'
        Download-File 'https://bootstrap.pypa.io/get-pip.py' $GetPip
        & $Python $GetPip --disable-pip-version-check
        if ($LASTEXITCODE -ne 0) { throw 'Could not prepare pip. Check network access to pypi.org.' }
    }
    $Requirements = Join-Path $ProjectRoot 'requirements-lock-windows.txt'
    if (-not (Test-Path -LiteralPath $Requirements)) { $Requirements=Join-Path $ProjectRoot 'requirements.txt' }
    $Stamp = Join-Path $RuntimeDir 'requirements.sha256'
    $Hash = (Get-FileHash -LiteralPath $Requirements -Algorithm SHA256).Hash
    $Previous = if (Test-Path -LiteralPath $Stamp) { (Get-Content -LiteralPath $Stamp -Raw).Trim() } else { '' }
    if ($Previous -ne $Hash) {
        Write-Host '[2/4] Installing private audio dependencies (first run only).'
        & $Python -m pip install '--only-binary=:all:' --disable-pip-version-check --timeout 120 --retries 3 -r $Requirements
        if ($LASTEXITCODE -ne 0) { throw 'Dependencies did not install. Check network access and retry START.cmd.' }
    }
    $SavedPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    & $Python (Join-Path $ProjectRoot 'check_audio.py')
    $EngineCheck = $LASTEXITCODE
    $ErrorActionPreference = $SavedPreference
    if ($EngineCheck -eq 20) {
        Write-Host 'Private Python dependencies are incomplete; restoring pinned packages.'
        & $Python -m pip install '--only-binary=:all:' --disable-pip-version-check --timeout 120 --retries 3 -r $Requirements
        if ($LASTEXITCODE -ne 0) { throw 'Dependency restoration failed. See setup.log.' }
        & $Python (Join-Path $ProjectRoot 'check_audio.py')
        $EngineCheck=$LASTEXITCODE
    }
    if ($EngineCheck -eq 21) {
        Write-Host 'Preparing Microsoft Visual C++ runtime. Windows may ask for permission.'
        $VCRuntime=Join-Path $DownloadDir 'vc_redist.x64.exe'
        Download-File 'https://aka.ms/vc14/vc_redist.x64.exe' $VCRuntime
        $InstallVC=Start-Process -FilePath $VCRuntime -ArgumentList '/install','/passive','/norestart' -Wait -PassThru
        if ($InstallVC.ExitCode -notin 0,1638,3010) { throw 'Microsoft runtime installation did not finish.' }
        & $Python (Join-Path $ProjectRoot 'check_audio.py')
        if ($LASTEXITCODE -ne 0) { throw 'Audio engine could not load. See setup.log.' }
        $EngineCheck=0
    }
    if ($EngineCheck -notin 0,21) { throw 'Audio engine import failed. See the specific error above.' }
    $Hash | Set-Content -LiteralPath $Stamp -Encoding ASCII
    Write-Host '[3/4] Checking local AI service.'
    if (-not (Ollama-Ready)) {
        $Ollama=Find-Ollama
        if (-not $Ollama) {
            Write-Host 'First run: opening the official Ollama installer. Finish installation to enable local AI summaries.'
            $Installer=Join-Path $DownloadDir 'OllamaSetup.exe'
            if (-not (Test-Path -LiteralPath $Installer)) { Download-File 'https://ollama.com/download/OllamaSetup.exe' $Installer }
            $SetupProcess=Start-Process -FilePath $Installer -PassThru
            $SetupProcess.WaitForExit()
            $Ollama=Find-Ollama
        }
        if ($Ollama -and -not (Ollama-Ready)) {
            Start-Process -FilePath $Ollama -ArgumentList 'serve' -WindowStyle Hidden -RedirectStandardOutput (Join-Path $LogDir 'ollama-out.log') -RedirectStandardError (Join-Path $LogDir 'ollama-error.log')
            for ($Try=0; $Try -lt 30; $Try++) {
                if (Ollama-Ready) { break }
                Start-Sleep -Seconds 1
            }
        }
    }
    if ($PrepareAI) {
        if (-not (Ollama-Ready)) { throw 'Ollama is not running. Finish the Ollama installation and retry.' }
        $Ollama=Find-Ollama
        if ($Ollama) { & $Ollama pull qwen2.5:3b; if ($LASTEXITCODE -ne 0) { throw 'AI model download did not finish.' } }
        else {
            $Body=@{model='qwen2.5:3b';stream=$false}|ConvertTo-Json
            Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:11434/api/pull' -Body $Body -ContentType 'application/json' -TimeoutSec 7200 | Out-Null
        }
        Write-Host 'AI model ready. Open START.cmd.'
    } else {
        if (-not (Ollama-Ready)) { Write-Warning 'AI is not ready; transcription still works. Later run PREPARE_AI.cmd.' }
        Write-Host '[4/4] Opening EchoNote. Keep this window open while using the app.'
        & $Python (Join-Path $ProjectRoot 'run.py')
        if ($LASTEXITCODE -ne 0) { throw 'EchoNote stopped unexpectedly. See data\logs\app.log.' }
    }
    if ($TranscriptStarted) { Stop-Transcript | Out-Null }
} catch {
    Write-Host ("ERROR: " + $_.Exception.Message) -ForegroundColor Red
    Write-Host 'Your recordings and notes are kept in data. See the specific error above and data\logs\setup.log.'
    if ($TranscriptStarted) { Stop-Transcript | Out-Null }
    exit 1
}
