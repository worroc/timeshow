; The Python builder passes all paths and the version from pyproject.toml.
#ifndef AppVersion
  #error Run src/build_windows_installer.py to supply the project version.
#endif

[Setup]
AppId=Timeshow
AppName=Timeshow
AppVersion={#AppVersion}
AppPublisher=Timeshow contributors
AppPublisherURL=https://github.com/worroc/timeshow
DefaultDirName={localappdata}\Programs\Timeshow
DefaultGroupName=Timeshow
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
OutputDir={#InstallerOutputDir}
OutputBaseFilename=Timeshow-{#AppVersion}-Setup
SetupIconFile={#ProjectDir}\src\timeshow\assets\timeshow.ico
UninstallDisplayIcon={app}\Timeshow.exe
LicenseFile={#ProjectDir}\LICENSE
Compression=lzma2/fast
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: desktopicon; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "{#BundleDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{userprograms}\Timeshow"; Filename: "{app}\Timeshow.exe"; Parameters: "--mode gui"; WorkingDir: "{app}"
Name: "{userstartup}\Timeshow tray"; Filename: "{app}\Timeshow.exe"; Parameters: "--mode tray"; WorkingDir: "{app}"
Name: "{userdesktop}\Timeshow"; Filename: "{app}\Timeshow.exe"; Parameters: "--mode gui"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\Timeshow.exe"; Parameters: "--mode gui"; Description: "Open Timeshow"; Flags: nowait postinstall skipifsilent

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  ResultCode: Integer;
  Cleaned: Boolean;
begin
  if CurUninstallStep <> usUninstall then
    Exit;
  Cleaned := Exec(ExpandConstant('{app}\Timeshow.exe'), '--mode uninstall', '',
    SW_HIDE, ewWaitUntilTerminated, ResultCode);
  if (not Cleaned) or (ResultCode <> 0) then begin
    SuppressibleMsgBox('Close Timeshow and its tray, wait for the current wallpaper change to finish, then retry uninstall. Check Task Scheduler access if cleanup still fails.',
      mbError, MB_OK, IDOK);
    Abort;
  end;
  { Only installer-owned files and shortcuts are removed. User data stays. }
end;
