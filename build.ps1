<#
.SYNOPSIS
    Builds dist\IdleRig-<version>.exe (single file, no console window) with Nuitka.

.EXAMPLE
    .\build.ps1
    .\build.ps1 -PfxPath cert.pfx -PfxPassword (Read-Host -AsSecureString)
#>
param(
    [string] $OutDir = "dist",
    [string] $PfxPath = "",
    [securestring] $PfxPassword
)

# "Continue": Windows PowerShell 5.1 turns any stderr output of native tools (Nuitka prints
# progress there) into a terminating error under "Stop". Failures are detected via $LASTEXITCODE.
$ErrorActionPreference = "Continue"
Set-Location $PSScriptRoot

$python = if (Test-Path ".venv\Scripts\python.exe") { ".venv\Scripts\python.exe" } else { "python" }
$version = & $python -c "import idlerig; print(idlerig.__version__)"
if ($LASTEXITCODE -ne 0) { throw "Could not read the version from idlerig/__init__.py" }
$exeName = "IdleRig-$version.exe"

Write-Host "Running tests..."
& $python -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "Tests failed; not building." }

New-Item -ItemType Directory -Force build | Out-Null
$ico = "build\idlerig.ico"
& $python -m idlerig.icon $ico
if ($LASTEXITCODE -ne 0) { throw "Could not generate $ico (is Pillow installed?)" }

Write-Host "Building $exeName with Nuitka..."
$nuitkaArgs = @(
    "-m", "nuitka",
    "--onefile",
    "--assume-yes-for-downloads",
    "--mingw64",
    "--windows-console-mode=disable",
    "--onefile-tempdir-spec={CACHE_DIR}/IdleRig/$version",
    "--include-package=idlerig",
    "--include-data-dir=idlerig/web=idlerig/web",
    "--enable-plugin=no-qt",
    "--windows-icon-from-ico=$ico",
    "--product-name=IdleRig",
    "--file-version=$version",
    "--product-version=$version",
    "--file-description=IdleRig - activity-aware XMRig controller",
    "--output-dir=$OutDir",
    "--output-filename=$exeName",
    "run.py"
)
& $python @nuitkaArgs
if ($LASTEXITCODE -ne 0) { throw "Nuitka build failed." }

$exe = Join-Path $OutDir $exeName
if (-not (Test-Path $exe)) { throw "Build finished but $exe was not found." }

if ($PfxPath) {
    $signtool = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin\*\x64\signtool.exe" -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending | Select-Object -First 1
    if (-not $signtool) { throw "signtool.exe not found (install the Windows SDK)." }
    $plain = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
        [Runtime.InteropServices.Marshal]::SecureStringToBSTR($PfxPassword))
    & $signtool.FullName sign /f $PfxPath /p $plain /fd SHA256 /td SHA256 /tr "http://timestamp.digicert.com" $exe
    if ($LASTEXITCODE -ne 0) { throw "Signing failed." }
}

$hash = (Get-FileHash $exe -Algorithm SHA256).Hash
"$hash  $exeName" | Set-Content -Encoding ascii (Join-Path $OutDir "CHECKSUMS.txt")
Write-Host "Done: $exe"
Write-Host "SHA256: $hash"
