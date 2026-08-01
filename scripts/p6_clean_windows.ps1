param(
    [Parameter(Mandatory = $true)]
    [string]$ModelPath,
    [string]$PackageDir = '',
    [string]$DataDir = (Join-Path $env:LOCALAPPDATA 'OfflineCompanion'),
    [int]$Port = 18765
)

$ErrorActionPreference = 'Stop'
if (-not $PackageDir) {
    $PackageDir = Join-Path $PSScriptRoot '..\dist\OfflineCompanion'
}
$package = (Resolve-Path -LiteralPath $PackageDir).Path
$model = (Resolve-Path -LiteralPath $ModelPath).Path
$exe = Join-Path $package 'OfflineCompanion.exe'
$sidecar = Join-Path $package 'llama_server\llama-server.exe'

if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) {
    throw "未找到主程序: $exe"
}
if (-not (Test-Path -LiteralPath $sidecar -PathType Leaf)) {
    throw "未找到 llama-server sidecar: $sidecar"
}

$pythonCommands = Get-Command python, py, conda -ErrorAction SilentlyContinue
if ($pythonCommands) {
    Write-Warning "当前机器可找到 Python/Conda；本次结果不能单独证明干净机无 Python 条件。"
} else {
    Write-Host '[OK] 未发现 Python、py launcher 或 Conda。'
}

Write-Host '[P6.5/6.6] 检查 app-local Runtime、模型加载和真实生成...'
& $exe check-model --model $model --n-ctx 512 --probe-generate
if ($LASTEXITCODE -ne 0) {
    throw "check-model 失败，退出码: $LASTEXITCODE"
}

New-Item -ItemType Directory -Path $DataDir -Force | Out-Null
$stdoutLog = Join-Path $DataDir 'p6-web.stdout.log'
$stderrLog = Join-Path $DataDir 'p6-web.stderr.log'
$baseUrl = "http://127.0.0.1:$Port"

function Start-P6Web {
    $arguments = @(
        'web',
        '--port', "$Port",
        '--model', "`"$model`"",
        '--data-dir', "`"$DataDir`"",
        '--memory', '1',
        '--n-ctx', '2048'
    )
    return Start-Process -FilePath $exe -ArgumentList $arguments -PassThru -WindowStyle Hidden `
        -RedirectStandardOutput $stdoutLog -RedirectStandardError $stderrLog
}

function Wait-P6Web {
    param([System.Diagnostics.Process]$Process)
    $deadline = (Get-Date).AddSeconds(120)
    while ((Get-Date) -lt $deadline) {
        if ($Process.HasExited) {
            throw "Web 进程提前退出，退出码: $($Process.ExitCode)。日志: $stderrLog"
        }
        try {
            Invoke-RestMethod -Uri "$baseUrl/api/status" -TimeoutSec 2 | Out-Null
            return
        } catch {
            Start-Sleep -Milliseconds 500
        }
    }
    throw 'Web 服务 120 秒内未就绪。'
}

function Send-P6Message {
    param([string]$Message)
    $body = @{ message = $Message } | ConvertTo-Json -Compress
    return Invoke-RestMethod -Uri "$baseUrl/api/chat" -Method Post `
        -ContentType 'application/json; charset=utf-8' -Body ([Text.Encoding]::UTF8.GetBytes($body))
}

function Stop-P6Web {
    param([System.Diagnostics.Process]$Process)
    if ($Process -and -not $Process.HasExited) {
        Stop-Process -Id $Process.Id -Force
        $Process.WaitForExit()
    }
}

$webProcess = $null
try {
    Write-Host '[P6.7-P6.9] 启动本地 Web 链路并验证情绪、记忆写入与召回...'
    $webProcess = Start-P6Web
    Wait-P6Web -Process $webProcess

    $save = Send-P6Message -Message '以后你叫立华奏吧'
    if (-not $save.memory_saved -or $save.memory_saved.Count -lt 1) {
        throw '身份记忆未写入。'
    }
    $identity = Send-P6Message -Message '你叫什么'
    if ($identity.reply -notmatch '立华奏') {
        throw "身份召回失败: $($identity.reply)"
    }
    $emotion = Send-P6Message -Message '我今天有点难过，想找人聊聊'
    if (-not $emotion.reply) {
        throw '情绪文本未得到有效回复。'
    }
} finally {
    Stop-P6Web -Process $webProcess
}

try {
    Write-Host '[P6.10] 重启后验证 DB 持久化...'
    $webProcess = Start-P6Web
    Wait-P6Web -Process $webProcess
    $persisted = Send-P6Message -Message '你叫什么'
    if ($persisted.reply -notmatch '立华奏') {
        throw "重启后身份召回失败: $($persisted.reply)"
    }
} finally {
    Stop-P6Web -Process $webProcess
}

$dbPath = Join-Path $DataDir 'companion.db'
if (-not (Test-Path -LiteralPath $dbPath -PathType Leaf)) {
    throw "未在指定数据目录找到 companion.db: $dbPath"
}

Write-Host "[OK] P6 自动化项通过。数据目录: $DataDir"
Write-Host '[MANUAL] 仍需双击 OfflineCompanion.exe，确认桌面窗口和托盘在目标机正常显示。'




