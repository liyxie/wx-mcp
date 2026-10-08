[CmdletBinding()]
param(
    [ValidateSet("start", "stop", "status", "restart")]
    [string]$Action = "start",

    [int]$Port = 0,
    [string]$HostAddr = ""
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$RunDir = Join-Path $ProjectRoot "run"
$LogDir = Join-Path $ProjectRoot "logs"
$PidFile = Join-Path $RunDir "wx-mcp.pid"
$OutLog = Join-Path $LogDir "wx-mcp.out.log"
$ErrLog = Join-Path $LogDir "wx-mcp.err.log"

if (-not (Test-Path -LiteralPath $Python)) {
    Write-Error "Python not found: $Python"
}

if ($Port -eq 0) {
    if ([string]::IsNullOrWhiteSpace($env:WX_MCP_PORT)) {
        $Port = 18080
    }
    else {
        $Port = [int]$env:WX_MCP_PORT
    }
}

if ([string]::IsNullOrWhiteSpace($HostAddr)) {
    if ([string]::IsNullOrWhiteSpace($env:WX_MCP_HOST)) {
        $HostAddr = "0.0.0.0"
    }
    else {
        $HostAddr = $env:WX_MCP_HOST
    }
}

New-Item -ItemType Directory -Force -Path $RunDir | Out-Null
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Get-RunningProcess {
    if (-not (Test-Path -LiteralPath $PidFile)) {
        return $null
    }

    $savedPid = [int](Get-Content -LiteralPath $PidFile -Raw)
    if ($savedPid -le 0) {
        return $null
    }

    try {
        $process = Get-Process -Id $savedPid -ErrorAction Stop
        return $process
    }
    catch {
        return $null
    }
}

function Start-WxMcp {
    $existing = Get-RunningProcess
    if ($null -ne $existing) {
        Write-Host "wx-mcp is already running (PID $($existing.Id))."
        return
    }

    $arguments = @(
        "-m", "wx_mcp",
        "--transport", "http",
        "--host", $HostAddr,
        "--port", $Port
    )

    $process = Start-Process `
        -FilePath $Python `
        -ArgumentList $arguments `
        -WorkingDirectory $ProjectRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput $OutLog `
        -RedirectStandardError $ErrLog `
        -PassThru

    Set-Content -LiteralPath $PidFile -Value $process.Id
    Start-Sleep -Seconds 1

    if ($process.HasExited) {
        Write-Error "wx-mcp exited immediately. See $ErrLog"
    }

    Write-Host "wx-mcp started (PID $($process.Id), http://${HostAddr}:${Port})."
}

function Stop-WxMcp {
    $process = Get-RunningProcess
    if ($null -eq $process) {
        Write-Host "wx-mcp is not running."
    }
    else {
        Stop-Process -Id $process.Id -Force
        Write-Host "wx-mcp stopped (PID $($process.Id))."
    }

    if (Test-Path -LiteralPath $PidFile) {
        Remove-Item -LiteralPath $PidFile -Force
    }
}

function Test-WxMcpHealth {
    $process = Get-RunningProcess
    if ($null -eq $process) {
        Write-Host "wx-mcp is not running."
        return
    }

    Write-Host "wx-mcp is running (PID $($process.Id))."
    try {
        $health = Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:${Port}/health" -TimeoutSec 3
        Write-Host "health: $($health | ConvertTo-Json -Compress)"
    }
    catch {
        Write-Host "health check failed: $($_.Exception.Message)"
    }
}

switch ($Action) {
    "start" {
        Start-WxMcp
    }
    "stop" {
        Stop-WxMcp
    }
    "restart" {
        Stop-WxMcp
        Start-Sleep -Seconds 1
        Start-WxMcp
    }
    "status" {
        Test-WxMcpHealth
    }
}
