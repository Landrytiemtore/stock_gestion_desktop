; Inno Setup Script pour GEST-STOCK POS
; Permet de generer un installeur Windows Setup.exe avec raccourci sur le Bureau

[Setup]
AppId={{9B78A1B2-C43D-4D9A-8756-3E2A12345678}
AppName=GEST-STOCK POS
AppVersion=1.0
AppPublisher=Commerce &amp; Solutions
DefaultDirName={autopf}\GestStockPOS
DefaultGroupName=GestStockPOS
OutputDir=dist_installer
OutputBaseFilename=Setup_GestStockPOS
Compression=lzma
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "dist\GestStockPOS.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "data\*"; DestDir: "{app}\data"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "uploads\*"; DestDir: "{app}\uploads"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "recus\*"; DestDir: "{app}\recus"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\GEST-STOCK POS"; Filename: "{app}\GestStockPOS.exe"
Name: "{autodesktop}\GEST-STOCK POS"; Filename: "{app}\GestStockPOS.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\GestStockPOS.exe"; Description: "{cm:LaunchProgram,GEST-STOCK POS}"; Flags: nowait postinstall skipifsilent
