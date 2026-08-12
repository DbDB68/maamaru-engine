#define AppVersion GetEnv("MAAMARU_VERSION")
#define PackageDir GetEnv("MAAMARU_PACKAGE_DIR")

[Setup]
AppId={{7A640CC8-4574-4B80-9BAA-37DC1A2AD749}
AppName=まあ丸
AppVersion={#AppVersion}
AppPublisher=まあ丸
AppPublisherURL=https://github.com/DbDB68/maamaru-engine
AppSupportURL=https://github.com/DbDB68/maamaru-engine/issues
AppUpdatesURL=https://github.com/DbDB68/maamaru-engine/releases/latest
DefaultDirName={localappdata}\Programs\Maamaru
DefaultGroupName=まあ丸
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
MinVersion=10.0
OutputDir=..\dist
OutputBaseFilename=maamaru-setup-v{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
SetupLogging=yes
CloseApplications=yes
RestartApplications=no
UninstallDisplayIcon={app}\まあ丸启动器.exe
VersionInfoVersion={#AppVersion}
VersionInfoProductName=まあ丸
VersionInfoDescription=まあ丸安装器

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "快捷方式："; Flags: unchecked

[Files]
Source: "{#PackageDir}\まあ丸启动器.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#PackageDir}\manifest.json"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\まあ丸"; Filename: "{app}\まあ丸启动器.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\まあ丸"; Filename: "{app}\まあ丸启动器.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\まあ丸启动器.exe"; Description: "启动まあ丸"; Flags: nowait postinstall skipifsilent

; 用户数据位于 {localappdata}\Maamaru，不属于安装目录。
; 不配置 [UninstallDelete]，卸载时只移除安装器登记的程序文件和快捷方式。
