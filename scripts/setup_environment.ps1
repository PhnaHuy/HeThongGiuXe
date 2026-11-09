[CmdletBinding()]
param(
    [Parameter()]
    [string]$UvPath,

    [Parameter()]
    [switch]$SkipOcr
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$pythonInstallDirectory = Join-Path $projectRoot '.runtime\python'
$cacheDirectory = Join-Path $projectRoot '.cache\uv'
$alprProjectDirectory = Join-Path $projectRoot 'environments\alpr'
$ocrProjectDirectory = Join-Path $projectRoot 'environments\ocr'

if ([string]::IsNullOrWhiteSpace($UvPath)) {
    $uvCommand = Get-Command -Name 'uv' -CommandType Application -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($null -ne $uvCommand) {
        $UvPath = $uvCommand.Source
    }
    elseif (-not [string]::IsNullOrWhiteSpace($env:USERPROFILE)) {
        $UvPath = Join-Path $env:USERPROFILE '.local\bin\uv.exe'
    }
}

if ([string]::IsNullOrWhiteSpace($UvPath) -or
    -not (Test-Path -LiteralPath $UvPath -PathType Leaf)) {
    throw 'Không tìm thấy uv. Cài theo https://docs.astral.sh/uv/getting-started/installation/ rồi chạy lại, hoặc truyền -UvPath đường_dẫn_uv.exe.'
}
$resolvedUv = (Resolve-Path -LiteralPath $UvPath).Path

# Fail before downloads if the reproducible dependency manifests are missing.
$projectsToCheck = @($projectRoot, $alprProjectDirectory)
if (-not $SkipOcr) {
    $projectsToCheck += $ocrProjectDirectory
}
foreach ($projectDirectory in $projectsToCheck) {
    foreach ($manifestName in @('pyproject.toml', 'uv.lock')) {
        $manifestPath = Join-Path $projectDirectory $manifestName
        if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
            throw "Thiếu $manifestPath. Lấy đủ manifest và uv.lock đã được kiểm chứng của G0 trước khi chạy thiết lập; script không tự tạo hoặc cập nhật lockfile."
        }
    }
}

function Invoke-UvCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    & $resolvedUv @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "uv thất bại với mã thoát $LASTEXITCODE. Dừng thiết lập; xem lỗi của uv ở phía trên."
    }
}

$previousProjectEnvironment = Get-Item -LiteralPath 'Env:UV_PROJECT_ENVIRONMENT' -ErrorAction SilentlyContinue

try {
    Write-Host 'Chuẩn bị Python 3.13 x64 riêng trong dự án...'
    Invoke-UvCommand -Arguments @(
        'python', 'install', '3.13',
        '--install-dir', $pythonInstallDirectory,
        '--no-bin', '--no-registry',
        '--cache-dir', $cacheDirectory
    )

    $pythonDirectories = @(
        Get-ChildItem -LiteralPath $pythonInstallDirectory -Directory |
            Where-Object { $_.Name -match '^cpython-3\.13\.\d+-windows-x86_64-none$' } |
            Sort-Object -Property {
                [version]($_.Name -replace '^cpython-([0-9.]+)-.*$', '$1')
            } -Descending
    )
    $pythonExecutable = $null
    foreach ($pythonDirectory in $pythonDirectories) {
        $candidateExecutable = Join-Path $pythonDirectory.FullName 'python.exe'
        if (Test-Path -LiteralPath $candidateExecutable -PathType Leaf) {
            $pythonExecutable = $candidateExecutable
            break
        }
    }
    if ($null -eq $pythonExecutable) {
        throw "Không tìm thấy python.exe của CPython 3.13 Windows x64 trong $pythonInstallDirectory sau khi cài."
    }

    Write-Host 'Đồng bộ môi trường chính theo uv.lock...'
    $env:UV_PROJECT_ENVIRONMENT = Join-Path $projectRoot '.venv'
    Invoke-UvCommand -Arguments @(
        'sync', '--project', $projectRoot,
        '--python', $pythonExecutable,
        '--locked', '--cache-dir', $cacheDirectory
    )

    Write-Host 'Đồng bộ môi trường nhận diện biển số riêng theo uv.lock...'
    $env:UV_PROJECT_ENVIRONMENT = Join-Path $projectRoot '.venv-alpr'
    Invoke-UvCommand -Arguments @(
        'sync', '--project', $alprProjectDirectory,
        '--python', $pythonExecutable,
        '--locked', '--cache-dir', $cacheDirectory
    )

    if (-not $SkipOcr) {
        Write-Host 'Đồng bộ môi trường OCR riêng theo uv.lock...'
        $env:UV_PROJECT_ENVIRONMENT = Join-Path $projectRoot '.venv-ocr-313'
        Invoke-UvCommand -Arguments @(
            'sync', '--project', $ocrProjectDirectory,
            '--python', $pythonExecutable,
            '--locked', '--cache-dir', $cacheDirectory
        )
    }

    Write-Host 'Đã thiết lập môi trường. Chạy các kiểm tra G0 theo README để xác minh thư viện và suy luận.'
}
finally {
    if ($null -eq $previousProjectEnvironment) {
        Remove-Item -LiteralPath 'Env:UV_PROJECT_ENVIRONMENT' -ErrorAction SilentlyContinue
    }
    else {
        $env:UV_PROJECT_ENVIRONMENT = $previousProjectEnvironment.Value
    }
}
