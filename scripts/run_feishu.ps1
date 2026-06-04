param(
    [ValidateSet("latest", "day", "morning", "evening")]
    [string]$Window = "latest",
    [string]$Date = "",
    [int]$CollectLimit = 30,
    [int]$PushLimit = 20
)

$ErrorActionPreference = "Stop"

$ProjectDir = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $ProjectDir

$EnvPath = Join-Path $ProjectDir ".env"
if (Test-Path $EnvPath) {
    Get-Content $EnvPath | ForEach-Object {
        $Line = $_.Trim()
        if (-not $Line -or $Line.StartsWith("#") -or -not $Line.Contains("=")) {
            return
        }
        $Key, $Value = $Line.Split("=", 2)
        $CleanValue = $Value.Trim()
        if (($CleanValue.StartsWith('"') -and $CleanValue.EndsWith('"')) -or ($CleanValue.StartsWith("'") -and $CleanValue.EndsWith("'"))) {
            $CleanValue = $CleanValue.Substring(1, $CleanValue.Length - 2)
        }
        [Environment]::SetEnvironmentVariable($Key.Trim(), $CleanValue, "Process")
    }
}

$PythonBin = if ($env:PYTHON_BIN) { $env:PYTHON_BIN } else { "py" }
$Args = @(
    ".\run.py",
    "feishu-workflow",
    "--window", $Window,
    "--collect-limit", $CollectLimit,
    "--push-limit", $PushLimit
)

if ($Date) {
    $Args += @("--date", $Date)
}

if ($env:ENABLE_AI -match "^(1|true|yes)$") {
    $Args += @("--ai")
}

& $PythonBin @Args
