param(
    [switch]$InstallTasks
)

$ErrorActionPreference = "Stop"

$ProjectDir = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $ProjectDir
$EnvPath = Join-Path $ProjectDir ".env"

function Read-ExistingEnv {
    $Values = @{}
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
            $Values[$Key.Trim()] = $CleanValue
        }
    }
    return $Values
}

function Prompt-Value {
    param(
        [hashtable]$Values,
        [string]$Key,
        [string]$Prompt,
        [string]$Default = "",
        [switch]$Secret
    )
    $Current = if ($Values.ContainsKey($Key)) { $Values[$Key] } else { $Default }
    $Display = if ($Secret -and $Current) { " [configured]" } elseif ($Current) { " [$Current]" } else { "" }
    if ($Secret) {
        $Secure = Read-Host "$Prompt$Display" -AsSecureString
        if ($Secure.Length -eq 0) {
            return $Current
        }
        $Ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Secure)
        try {
            return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($Ptr)
        }
        finally {
            [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($Ptr)
        }
    }
    $InputValue = Read-Host "$Prompt$Display"
    if ($InputValue) {
        return $InputValue
    }
    return $Current
}

$Values = Read-ExistingEnv

$OrderedKeys = @(
    "FEISHU_WEBHOOK",
    "FEISHU_SECRET",
    "AI_PROVIDER",
    "OPENAI_BASE_URL",
    "OPENAI_API_KEY",
    "OPENAI_MODEL",
    "AI_MAX_TOKENS",
    "ENABLE_AI",
    "COLLECT_LIMIT",
    "PUSH_LIMIT",
    "PYTHON_BIN"
)

$Values["FEISHU_WEBHOOK"] = Prompt-Value $Values "FEISHU_WEBHOOK" "Feishu webhook"
$Values["FEISHU_SECRET"] = Prompt-Value $Values "FEISHU_SECRET" "Feishu signing secret (optional)" "" -Secret
$Values["AI_PROVIDER"] = Prompt-Value $Values "AI_PROVIDER" "AI provider" "openai"
$Values["OPENAI_BASE_URL"] = Prompt-Value $Values "OPENAI_BASE_URL" "AI base URL (optional)" ""
$Values["OPENAI_API_KEY"] = Prompt-Value $Values "OPENAI_API_KEY" "AI API key (optional)" "" -Secret
$Values["OPENAI_MODEL"] = Prompt-Value $Values "OPENAI_MODEL" "AI model" "gpt-4.1-mini"
$Values["AI_MAX_TOKENS"] = Prompt-Value $Values "AI_MAX_TOKENS" "AI max output tokens" "4096"
$DefaultEnableAI = if ($Values["OPENAI_API_KEY"]) { "true" } else { "false" }
$Values["ENABLE_AI"] = Prompt-Value $Values "ENABLE_AI" "Enable AI for scheduled pushes? true/false" $DefaultEnableAI
$Values["COLLECT_LIMIT"] = Prompt-Value $Values "COLLECT_LIMIT" "Collect limit" "30"
$Values["PUSH_LIMIT"] = Prompt-Value $Values "PUSH_LIMIT" "Push limit" "20"
$Values["PYTHON_BIN"] = Prompt-Value $Values "PYTHON_BIN" "Python command" "py"

$Lines = @()
foreach ($Key in $OrderedKeys) {
    if ($Values.ContainsKey($Key) -and $null -ne $Values[$Key] -and $Values[$Key] -ne "") {
        $Lines += "$Key=$($Values[$Key])"
    }
}
Set-Content -Path $EnvPath -Value $Lines -Encoding UTF8
Write-Host "Wrote .env with configured values. Secrets are stored locally in plaintext."

$PythonBin = $Values["PYTHON_BIN"]
Write-Host "Installing Python dependencies..."
& $PythonBin -m pip install "requests>=2.31"

Write-Host "Initializing database..."
& $PythonBin ".\run.py" init-db

if (-not $InstallTasks) {
    $Answer = Read-Host "Install Windows scheduled tasks for 08:00 and 20:00? y/N"
    if ($Answer -match "^(y|yes)$") {
        $InstallTasks = $true
    }
}

if ($InstallTasks) {
    & (Join-Path $ProjectDir "scripts\install_windows_tasks.ps1")
}

Write-Host "Setup complete."
Write-Host "Test push: $PythonBin .\run.py push-feishu --limit 3"
Write-Host "AI workflow: .\scripts\run_feishu.ps1 -Window evening"
