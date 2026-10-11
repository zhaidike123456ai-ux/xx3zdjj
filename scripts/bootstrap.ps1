# Windows bootstrap. Does not change ExecutionPolicy or persistent PATH.
$ErrorActionPreference = 'Stop'
$ManagerArgs = @($args)
if ($ManagerArgs.Count -eq 0) { $ManagerArgs = @('check') }
$RuntimeRoot = Join-Path $env:LOCALAPPDATA 'xx3zdjj\runtime'
$AllowInstall = $false
$ChosenPython = $null
for ($i = 0; $i -lt $ManagerArgs.Count; $i++) {
    switch -Regex ($ManagerArgs[$i]) {
        '^--allow-install$' { $AllowInstall = $true }
        '^--runtime-root$' { $i++; $RuntimeRoot = $ManagerArgs[$i] }
        '^--runtime-root=(.*)$' { $RuntimeRoot = $Matches[1] }
        '^--python$' { $i++; $ChosenPython = $ManagerArgs[$i] }
        '^--python=(.*)$' { $ChosenPython = $Matches[1] }
    }
}
function Test-Python([string]$Path) {
    try {
        & $Path -B -c 'import sys;sys.exit(0 if (3,9)<=sys.version_info[:2]<(3,14) else 1)' 2>$null | Out-Null
        return ($LASTEXITCODE -eq 0)
    } catch { return $false }
}
if ($ChosenPython -and !(Test-Python $ChosenPython)) { throw 'Specified Python is unavailable/incompatible (requires 3.9-3.13).' }
if (!$ChosenPython) {
    foreach ($Name in @('python3','python','python3.13','python3.12','python3.11')) {
        $Command = Get-Command $Name -ErrorAction SilentlyContinue
        if ($Command -and (Test-Python $Command.Source)) { $ChosenPython = $Command.Source; break }
    }
}
if (!$ChosenPython) {
    $Launcher = Get-Command py -ErrorAction SilentlyContinue
    if ($Launcher) {
        foreach ($Version in @('-3.13','-3.12','-3.11','-3.10','-3.9')) {
            try {
                $Candidate = (& $Launcher.Source $Version -c 'import sys;print(sys.executable)' 2>$null | Select-Object -First 1)
                if ($Candidate -and (Test-Python $Candidate)) { $ChosenPython = $Candidate; break }
            } catch { }
        }
    }
}
if (!$ChosenPython -and (Test-Path (Join-Path $RuntimeRoot 'bootstrap-python'))) {
    foreach ($Candidate in Get-ChildItem (Join-Path $RuntimeRoot 'bootstrap-python') -Filter python.exe -File -Recurse) {
        if (Test-Python $Candidate.FullName) { $ChosenPython = $Candidate.FullName; break }
    }
}
if ($ChosenPython) {
    & $ChosenPython -B (Join-Path $PSScriptRoot 'runtime_manager.py') @ManagerArgs
    exit $LASTEXITCODE
}
if (!$AllowInstall) {
    Write-Error "No compatible Python found. Read-only: no download. Authorized installation needs --allow-install (about 120 MB; Astral verified uv/Python; $RuntimeRoot\bootstrap-python)."
    exit 2
}
$Arch = [System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString()
if ($Arch -eq 'Arm64') { throw 'Windows ARM64 has no verified native CTranslate2 wheel combination. Adopt an already validated environment; no silent x64 emulation.' }
if ($Arch -ne 'X64') { throw 'Windows bootstrap supports x64 only.' }
$ArchiveName = 'uv-x86_64-pc-windows-msvc.zip'
$ExpectedHash = '5049375aa2a5162f132b2c1cb992e25d42d47d934cab8c174dbe6f60973dcc12'
$Cache = Join-Path $RuntimeRoot 'cache'
New-Item -ItemType Directory -Force $Cache | Out-Null
$Lock = Join-Path $RuntimeRoot 'bootstrap.lock'
# FileMode.CreateNew is atomic; Directory.CreateDirectory is not an exclusive lock.
try { $LockHandle = [IO.File]::Open($Lock, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None) }
catch { throw 'Another bootstrap holds bootstrap.lock; do not remove it until its process has ended.' }
$Stage = Join-Path $Cache ('bootstrap-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory $Stage | Out-Null
try {
    $Archive = Join-Path $Stage $ArchiveName
    Invoke-WebRequest -UseBasicParsing -Uri ("https://github.com/astral-sh/uv/releases/download/0.8.22/" + $ArchiveName) -OutFile $Archive
    if ((Get-FileHash $Archive -Algorithm SHA256).Hash.ToLower() -ne $ExpectedHash) { throw 'uv SHA256 mismatch; not executed.' }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $Zip = [IO.Compression.ZipFile]::OpenRead($Archive)
    try {
        foreach ($Entry in $Zip.Entries) {
            $Target = [IO.Path]::GetFullPath((Join-Path $Stage $Entry.FullName))
            if (!$Target.StartsWith(($Stage + [IO.Path]::DirectorySeparatorChar), [StringComparison]::OrdinalIgnoreCase)) { throw 'Archive path traversal blocked.' }
            if (($Entry.ExternalAttributes -shr 16 -band 61440) -eq 40960) { throw 'Archive symlink blocked.' }
        }
    } finally { $Zip.Dispose() }
    [IO.Compression.ZipFile]::ExtractToDirectory($Archive, $Stage)
    $Uv = (Get-ChildItem $Stage -Filter uv.exe -File -Recurse | Select-Object -First 1).FullName
    if (!$Uv) { throw 'uv binary missing.' }
    $OldCache = $env:UV_CACHE_DIR
    $env:UV_CACHE_DIR = Join-Path $Cache 'uv'
    try {
        & $Uv python install 3.11.13 --install-dir (Join-Path $RuntimeRoot 'bootstrap-python') --no-bin
        if ($LASTEXITCODE -ne 0) { throw 'Managed Python installation failed.' }
    } finally { $env:UV_CACHE_DIR = $OldCache }
    $ChosenPython = (Get-ChildItem (Join-Path $RuntimeRoot 'bootstrap-python') -Filter python.exe -File -Recurse | Select-Object -First 1).FullName
    if (!$ChosenPython -or !(Test-Python $ChosenPython)) { throw 'Installed Python is not runnable; prior environment was not modified.' }
} finally {
    Remove-Item $Stage -Force -Recurse -ErrorAction SilentlyContinue
    $LockHandle.Dispose()
    Remove-Item $Lock -Force
}
& $ChosenPython -B (Join-Path $PSScriptRoot 'runtime_manager.py') --python $ChosenPython @ManagerArgs
exit $LASTEXITCODE
