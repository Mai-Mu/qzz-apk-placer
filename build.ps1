$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
python -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }
python -m pip install 'pyinstaller==6.22.3'
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller installation failed' }
# Generate the native type-library wrappers before freezing. Package the generated
# modules so the executable does not need Python or a writable comtypes directory.
python -c "import comtypes.client as c; c.GetModule('PortableDeviceApi.dll'); c.GetModule('PortableDeviceTypes.dll')"
if ($LASTEXITCODE -ne 0) { throw 'Type-library generation failed' }
$buildPreviousPath = $env:Path
$pythonExecutable = (Get-Command python).Source
$pythonDirectory = Split-Path -Parent $pythonExecutable
try {
    # Keep DLLs belonging to unrelated desktop tools out of the distribution.
    $env:Path = "$pythonDirectory;$pythonDirectory\Scripts;$env:SystemRoot\System32;$env:SystemRoot"
    & $pythonExecutable -m PyInstaller --noconfirm --clean --windowed --onedir --name QzzApkPlacer --exclude-module numpy --collect-submodules comtypes.gen --icon assets/app.ico main.py
    if ($LASTEXITCODE -ne 0) { throw 'Executable build failed' }
} finally {
    $env:Path = $buildPreviousPath
}
Write-Host 'Ready: dist\QzzApkPlacer\QzzApkPlacer.exe'
