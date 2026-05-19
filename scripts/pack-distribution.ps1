# Pack EduGenius source for distribution (excludes deps, cache, local data)
param(
    [string]$OutputDir = "",
    [string]$ArchiveName = "EduGenius-distribution"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
if (-not (Test-Path (Join-Path $ProjectRoot "package.json"))) {
    $ProjectRoot = (Get-Location).Path
}

if ([string]::IsNullOrWhiteSpace($OutputDir)) {
    $OutputDir = Split-Path -Parent $ProjectRoot
}

$ExcludeDirNames = @(
    "node_modules", ".next", ".npm-cache", "conda-env", "venv",
    "chroma_db", "uploads", "logs", "tmp", "__pycache__", ".git",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", "dist", "out", "build"
)

$ExcludeFilePatterns = @(
    "*.pyc", "*.pyo", "*.db", "*.sqlite3", ".env", ".env.local",
    "tsconfig.tsbuildinfo", "*.log"
)

$KeepEnvExamples = $true

$StagingName = "${ArchiveName}-staging"
$StagingPath = Join-Path $env:TEMP $StagingName
$DestRoot = Join-Path $StagingPath "EduGenius"

if (Test-Path $StagingPath) {
    Remove-Item -Recurse -Force $StagingPath
}
New-Item -ItemType Directory -Path $DestRoot -Force | Out-Null

function Should-SkipDir([string]$Name) {
    return $ExcludeDirNames -contains $Name
}

function Should-SkipFile([string]$RelativePath, [string]$Name) {
    if ($KeepEnvExamples -and ($Name -eq ".env.example" -or $Name -eq ".env.local.example")) {
        return $false
    }
    if ($RelativePath -match '[\\/]\.env$' -or $RelativePath -match '[\\/]\.env\.local$') {
        return $true
    }
    foreach ($pat in $ExcludeFilePatterns) {
        if ($Name -like $pat) { return $true }
    }
    return $false
}

function Copy-ProjectTree([string]$Source, [string]$Dest) {
    Get-ChildItem -LiteralPath $Source -Force | ForEach-Object {
        $name = $_.Name
        if ($name -eq "scripts" -and $_.PSIsContainer) {
            # include scripts folder but skip pack script recursion issues
        }
        if ($_.PSIsContainer) {
            if (Should-SkipDir $name) { return }
            $targetDir = Join-Path $Dest $name
            New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
            Copy-ProjectTree $_.FullName $targetDir
        } else {
            $rel = $_.FullName.Substring($ProjectRoot.Length).TrimStart('\', '/')
            if (Should-SkipFile $rel $name) { return }
            Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $Dest $name) -Force
        }
    }
}

Write-Host "Source: $ProjectRoot"
Write-Host "Staging: $DestRoot"
Copy-ProjectTree $ProjectRoot $DestRoot

$ZipPath = Join-Path $OutputDir "${ArchiveName}.zip"
if (Test-Path $ZipPath) {
    Remove-Item -Force $ZipPath
}

Compress-Archive -Path $DestRoot -DestinationPath $ZipPath -CompressionLevel Optimal
Remove-Item -Recurse -Force $StagingPath

$sizeMB = [math]::Round((Get-Item $ZipPath).Length / 1MB, 2)
Write-Host ""
Write-Host "Done: $ZipPath ($sizeMB MB)"
Write-Host "Recipient guide: extract and read DISTRIBUTION.md"
