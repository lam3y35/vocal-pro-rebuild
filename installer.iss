; VocalPro v3.0.0 — Turnkey All-in-One Inno Setup Installer Script
; Bundles:
; 1) Compiled Native Desktop Executable (Rust + Tauri v2)
; 2) Pre-packaged Embedded Python AI Worker (Torch + Demucs + DSP)
; 3) Pre-cached Offline Default Demucs AI Model (htdemucs)
; 4) Native Windows Shell Integration & File Associations

#define MyAppName "VocalPro"
#define MyAppVersion "3.0.0"
#define MyAppPublisher "VocalPro Studio"
#define MyAppURL "https://github.com/lam3y35/vocal-pro-rebuild"
#define MyAppExeName "vocalpro.exe"

[Setup]
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}

OutputDir=dist\installer
OutputBaseFilename=VocalPro-v{#MyAppVersion}-AllInOne-Setup
SetupIconFile=src-tauri\icons\icon.ico
Compression=lzma2/normal
SolidCompression=yes

DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesInstallIn64BitMode=x64compatible
DisableProgramGroupPage=yes
DisableReadyPage=yes

UninstallDisplayIcon={app}\vocalpro.ico
UninstallDisplayName={#MyAppName} v{#MyAppVersion}
CreateUninstallRegKey=yes
MinVersion=10.0

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: checkedonce
Name: "fileassoc"; Description: "Register VocalPro as default stem separator for audio/video files"; GroupDescription: "File associations:"; Flags: checkedonce

[Files]
; 1. Compiled Native Desktop Core Binary
Source: "dist\bundle\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "src-tauri\icons\icon.ico"; DestDir: "{app}"; DestName: "vocalpro.ico"; Flags: ignoreversion

; 2. Static FFmpeg Binary
Source: "dist\bundle\ffmpeg.exe"; DestDir: "{app}"; Flags: ignoreversion

; 3. Embedded Python AI Engine & Dependencies
Source: "dist\bundle\engine\*"; DestDir: "{app}\engine"; Flags: ignoreversion recursesubdirs createallsubdirs

; 4. Python AI Worker Code
Source: "worker\vocalpro_worker\*"; DestDir: "{app}\worker\vocalpro_worker"; Flags: ignoreversion recursesubdirs createallsubdirs

; 5. Preloaded Offline AI Models
Source: "dist\bundle\models\*"; DestDir: "{localappdata}\VocalPro\models"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "dist\bundle\models\*"; DestDir: "{localappdata}\VocalPro\models\checkpoints"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "dist\bundle\models\*"; DestDir: "{app}\models"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\vocalpro.ico"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\vocalpro.ico"; Tasks: desktopicon

[Registry]
; Register VocalPro Media Handler
Root: HKCU; Subkey: "Software\Classes\VocalPro.MediaFile"; ValueType: string; ValueData: "VocalPro Audio/Video Media"; Flags: uninsdeletekey; Tasks: fileassoc
Root: HKCU; Subkey: "Software\Classes\VocalPro.MediaFile\DefaultIcon"; ValueType: string; ValueData: "{app}\vocalpro.ico"; Tasks: fileassoc
Root: HKCU; Subkey: "Software\Classes\VocalPro.MediaFile\shell\open\command"; ValueType: string; ValueData: """{app}\{#MyAppExeName}"" ""%1"""; Tasks: fileassoc

; Associate standard audio & video extensions
Root: HKCU; Subkey: "Software\Classes\.mp3\OpenWithProgids"; ValueType: string; ValueName: "VocalPro.MediaFile"; ValueData: ""; Flags: uninsdeletevalue; Tasks: fileassoc
Root: HKCU; Subkey: "Software\Classes\.wav\OpenWithProgids"; ValueType: string; ValueName: "VocalPro.MediaFile"; ValueData: ""; Flags: uninsdeletevalue; Tasks: fileassoc
Root: HKCU; Subkey: "Software\Classes\.flac\OpenWithProgids"; ValueType: string; ValueName: "VocalPro.MediaFile"; ValueData: ""; Flags: uninsdeletevalue; Tasks: fileassoc
Root: HKCU; Subkey: "Software\Classes\.ogg\OpenWithProgids"; ValueType: string; ValueName: "VocalPro.MediaFile"; ValueData: ""; Flags: uninsdeletevalue; Tasks: fileassoc
Root: HKCU; Subkey: "Software\Classes\.m4a\OpenWithProgids"; ValueType: string; ValueName: "VocalPro.MediaFile"; ValueData: ""; Flags: uninsdeletevalue; Tasks: fileassoc
Root: HKCU; Subkey: "Software\Classes\.mp4\OpenWithProgids"; ValueType: string; ValueName: "VocalPro.MediaFile"; ValueData: ""; Flags: uninsdeletevalue; Tasks: fileassoc
Root: HKCU; Subkey: "Software\Classes\.mkv\OpenWithProgids"; ValueType: string; ValueName: "VocalPro.MediaFile"; ValueData: ""; Flags: uninsdeletevalue; Tasks: fileassoc

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent

[Code]
// Feature 14: Runtime Prerequisite Checks (WebView2 Evergreen + VC++ 2015-2022 x64)

function IsWebView2Installed(): Boolean;
var
  Version: String;
begin
  Result := False;
  // Check 32-bit / WOW6432Node registry key
  if RegQueryStringValue(HKLM, 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-6F3A4A1F3D59}', 'pv', Version) then
  begin
    if (Version <> '') and (Version <> '0.0.0.0') then
    begin
      Result := True;
      Exit;
    end;
  end;

  // Check native 64-bit HKLM
  if RegQueryStringValue(HKLM64, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-6F3A4A1F3D59}', 'pv', Version) then
  begin
    if (Version <> '') and (Version <> '0.0.0.0') then
    begin
      Result := True;
      Exit;
    end;
  end;

  // Check HKCU user-level install
  if RegQueryStringValue(HKCU, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-6F3A4A1F3D59}', 'pv', Version) then
  begin
    if (Version <> '') and (Version <> '0.0.0.0') then
    begin
      Result := True;
      Exit;
    end;
  end;
end;

function IsVCRedistInstalled(): Boolean;
var
  Installed: Cardinal;
begin
  Result := False;
  // 1. Check native 64-bit VC++ 2015-2022 registry key
  if RegQueryDWordValue(HKLM64, 'SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64', 'Installed', Installed) then
  begin
    if Installed = 1 then
    begin
      Result := True;
      Exit;
    end;
  end;

  // 2. Check 32-bit/WOW64 registry key
  if RegQueryDWordValue(HKLM, 'SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64', 'Installed', Installed) then
  begin
    if Installed = 1 then
    begin
      Result := True;
      Exit;
    end;
  end;

  // 3. Fallback: Check System32 for vcruntime140_1.dll
  if FileExists(ExpandConstant('{sys}\vcruntime140_1.dll')) then
  begin
    Result := True;
    Exit;
  end;
end;

function InitializeSetup(): Boolean;
var
  ErrorCode: Integer;
begin
  Result := True;

  // Verify Visual C++ 2015-2022 x64 Redistributable (strictly needed for PyTorch C-extensions)
  if not IsVCRedistInstalled() then
  begin
    if MsgBox('VocalPro requires Microsoft Visual C++ 2015-2022 x64 Redistributable (vcruntime140_1.dll) to run its AI audio processing engine.' + #13#10#13#10 +
              'It was not detected on this system.' + #13#10#13#10 +
              'Would you like to open the official Microsoft download page now?', mbConfirmation, MB_YESNO) = IDYES then
    begin
      ShellExec('open', 'https://aka.ms/vs/17/release/vc_redist.x64.exe', '', '', SW_SHOWNORMAL, ewNoWait, ErrorCode);
    end;
    Result := False;
    Exit;
  end;

  // Verify Microsoft Edge WebView2 Evergreen Runtime (strictly needed for Tauri v2 desktop UI)
  if not IsWebView2Installed() then
  begin
    if MsgBox('VocalPro requires Microsoft Edge WebView2 Runtime to display its desktop user interface.' + #13#10#13#10 +
              'It was not detected on this system.' + #13#10#13#10 +
              'Would you like to open the official Microsoft download page now?', mbConfirmation, MB_YESNO) = IDYES then
    begin
      ShellExec('open', 'https://go.microsoft.com/fwlink/p/?LinkId=2124703', '', '', SW_SHOWNORMAL, ewNoWait, ErrorCode);
    end;
    Result := False;
    Exit;
  end;
end;
