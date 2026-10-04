param([Parameter(ValueFromRemainingArguments = $true)] [string[]] $Arguments)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$PythonVersion = '3.7.9'
$PackageUrl = "https://api.nuget.org/v3-flatcontainer/python/$PythonVersion/python.$PythonVersion.nupkg"
$PackageSha256 = '029E1EA5BEEB142CD0F2DA4E75C45F49BD7E0C7B48EB5BB6C6947F2D1B665C5E'
$CacheDir = Join-Path $env:LOCALAPPDATA 'Motherlode'
$PrivateDir = Join-Path $CacheDir "python-$PythonVersion"
$PrivatePython = Join-Path $PrivateDir 'tools\python.exe'

function Test-Python37([string[]] $Command) {
    $exe = $Command[0]
    $rest = @($Command | Select-Object -Skip 1)
    try {
        & $exe @rest -c 'import sys; sys.exit(0 if sys.version_info[:2] == (3, 7) else 1)' 2>$null | Out-Null
        return $LASTEXITCODE -eq 0
    } catch {
        return $false
    }
}

function Find-Python37 {
    foreach ($candidate in @(@('py', '-3.7'), @($PrivatePython), @('python3.7'), @('python'))) {
        if (Test-Python37 $candidate) {
            return ,$candidate
        }
    }
    return $null
}

function Install-PrivatePython {
    Write-Host "Python 3.7 isn't installed. Downloading a private copy of Python $PythonVersion (about 15 MB) from nuget.org..."
    New-Item -ItemType Directory -Force -Path $CacheDir | Out-Null
    $package = Join-Path $CacheDir "python-$PythonVersion.zip"
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    $ProgressPreference = 'SilentlyContinue'
    Invoke-WebRequest -Uri $PackageUrl -OutFile $package -UseBasicParsing
    $hash = (Get-FileHash -Path $package -Algorithm SHA256).Hash
    if ($hash -ne $PackageSha256) {
        Remove-Item -Force $package
        throw "The Python download didn't match its expected checksum (got $hash), so it was deleted."
    }
    if (Test-Path $PrivateDir) {
        Remove-Item -Recurse -Force $PrivateDir
    }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [IO.Compression.ZipFile]::ExtractToDirectory($package, $PrivateDir)
    Remove-Item -Force $package
    Write-Host "Python $PythonVersion is ready in $PrivateDir"
}

$python = Find-Python37
if ($null -eq $python) {
    Install-PrivatePython
    $python = @($PrivatePython)
}

$exe = $python[0]
$rest = @($python | Select-Object -Skip 1)
$env:PYTHONPATH = if ($env:PYTHONPATH) { "$Root;$env:PYTHONPATH" } else { $Root }
$output = Join-Path $Root 'decompiled'
& $exe @rest -m motherlode -o $output --open @Arguments
exit $LASTEXITCODE
