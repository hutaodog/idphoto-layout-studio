; 安装版打包脚本（Inno Setup 6）
; 编译：ISCC.exe packaging\installer.iss
; 产物：dist\证件照排版助手_安装版_v<AppVersion>.exe
;       （文件名由正文的 AppVersion 定义决定，当前 1.6.3；改版本号只需改那一处）
;
; 用 onedir 产物作为安装载荷，而不是单文件 exe：
; 单文件 exe 每次启动都要把 ~300MB 内容解压出来，装到本机后每次开都要等几秒；
; 文件夹形式是秒开。便携版仍然提供那个单文件 exe。

#define AppName "证件照排版助手"
#define AppVersion "1.6.3"
#define AppExe "证件照排版助手.exe"
#define AppPublisher "自用工具"

[Setup]
AppId={{7C3F2A64-9E1B-4D57-8A2C-5F0D6B4E1C93}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=证件照排版助手_安装版_v{#AppVersion}
SetupIconFile=..\app\resources\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; 允许普通用户装到自己目录，不强制管理员
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
VersionInfoVersion=1.6.3.0
VersionInfoDescription={#AppName} 安装程序
VersionInfoProductName={#AppName}
VersionInfoProductVersion={#AppVersion}

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务："; Flags: checkedonce

[Files]
Source: "..\dist_onedir\{#AppName}\*"; DestDir: "{app}"; \
    Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\卸载 {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "立即运行 {#AppName}"; \
    Flags: nowait postinstall skipifsilent

[UninstallDelete]
; 不留垃圾：清掉可能被写进安装目录的缓存
Type: filesandordirs; Name: "{app}\__pycache__"
Type: filesandordirs; Name: "{app}\app\__pycache__"
