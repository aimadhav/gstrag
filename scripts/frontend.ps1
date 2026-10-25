param(
    [ValidateSet('install', 'dev', 'build', 'test')][string]$Action = 'dev',
    [int]$Port = 5173
)
$ErrorActionPreference = 'Stop'
$gstFrontendRoot = Join-Path (Split-Path -Parent $PSScriptRoot) 'frontend'
$gstNodeCandidates = @()
$gstInstalledNode = Get-Command node -ErrorAction SilentlyContinue
if ($gstInstalledNode) { $gstNodeCandidates += $gstInstalledNode.Source }
if ($env:USERPROFILE) {
    $gstNodeCandidates += Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe'
}
$gstNode = $null
foreach ($gstCandidate in $gstNodeCandidates) {
    if (Test-Path -LiteralPath $gstCandidate) {
        $gstVersion = [Version]((& $gstCandidate --version).Trim().TrimStart('v'))
        if ($gstVersion -ge [Version]'22.12.0') { $gstNode = $gstCandidate; break }
    }
}
if (-not $gstNode) { throw 'Use Node 22.12+ (or the bundled Node 24 runtime) for this frontend.' }
Write-Output ('Using Node ' + $gstVersion + ' for frontend ' + $Action)
Push-Location $gstFrontendRoot
try {
    switch ($Action) {
        'install' {
            $gstNpmCommand = Get-Command npm.cmd -ErrorAction SilentlyContinue
            if (-not $gstNpmCommand) { throw 'npm is required for installation. Install a supported Node distribution.' }
            $gstNpmCli = Join-Path (Split-Path -Parent $gstNpmCommand.Source) 'node_modules/npm/bin/npm-cli.js'
            if (-not (Test-Path -LiteralPath $gstNpmCli)) { throw 'Cannot locate the installed npm CLI.' }
            & $gstNode $gstNpmCli ci --no-fund
        }
        'dev' { & $gstNode node_modules/vite/bin/vite.js --host 127.0.0.1 --port $Port --strictPort }
        'build' {
            & $gstNode node_modules/typescript/bin/tsc --noEmit
            if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
            & $gstNode node_modules/vite/bin/vite.js build
        }
        'test' { & $gstNode node_modules/vitest/vitest.mjs run }
    }
    $gstExitCode = $LASTEXITCODE
} finally { Pop-Location }
exit $gstExitCode
