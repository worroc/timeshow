$ErrorActionPreference = 'Stop'

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    $uvDir = Join-Path $env:LOCALAPPDATA 'Programs\uv'
    $installer = Join-Path ([IO.Path]::GetTempPath()) ('timeshow-uv-' + [Guid]::NewGuid() + '.ps1')
    $previousInstallPath = $env:UV_UNMANAGED_INSTALL
    try {
        Invoke-WebRequest -Uri 'https://astral.sh/uv/install.ps1' -OutFile $installer
        $env:UV_UNMANAGED_INSTALL = $uvDir
        & powershell -NoProfile -ExecutionPolicy Bypass -File $installer
        if ($LASTEXITCODE -ne 0) { throw 'uv installation failed.' }
        $env:PATH = "$uvDir;$env:PATH"
    } finally {
        $env:UV_UNMANAGED_INSTALL = $previousInstallPath
        Remove-Item -LiteralPath $installer -ErrorAction SilentlyContinue
    }
}

$projectDir = $PSScriptRoot
Push-Location $projectDir
try {
    & uv sync --python 3.12 --extra gui
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
    $programs = [Environment]::GetFolderPath('Programs')
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut((Join-Path $programs 'Timeshow.lnk'))
    $shortcut.TargetPath = Join-Path $projectDir '.venv\Scripts\timeshow-gui.exe'
    $shortcut.WorkingDirectory = $projectDir
    $shortcut.Description = 'Rotate photos from your selected albums'
    $shortcut.Save()
    $startup = [Environment]::GetFolderPath('Startup')
    $trayShortcut = $shell.CreateShortcut((Join-Path $startup 'Timeshow tray.lnk'))
    $trayShortcut.TargetPath = Join-Path $projectDir '.venv\Scripts\timeshow-tray.exe'
    $trayShortcut.WorkingDirectory = $projectDir
    $trayShortcut.Save()
    Write-Host 'Installed. Open Timeshow from the Start menu.'
} finally {
    Pop-Location
}
