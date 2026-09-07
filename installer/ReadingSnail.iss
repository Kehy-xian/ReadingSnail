; 책 읽는 달팽이 — Inno Setup 스크립트
;
;   1) pyinstaller ReadingSnail.spec
;   2) ISCC installer\ReadingSnail.iss
;
; 사용자별 설치다(PrivilegesRequired=lowest). 관리자 권한을 묻지 않는다.
; **삭제할 때 기록을 지우지 않는다** — 그건 사용자 데이터다(CLAUDE.md 제약).

#define AppName "책 읽는 달팽이"
#define AppId "ReadingSnail"
#define AppVersion "0.0.1"
#define AppExe "ReadingSnail.exe"

[Setup]
AppId={{8E2A5C41-4C3B-4B7E-9E4C-READINGSNAIL}}
AppName={#AppName}
AppVersion={#AppVersion}
DefaultDirName={autopf}\{#AppId}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist\installer
OutputBaseFilename=ReadingSnail-{#AppVersion}-setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#AppExe}

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"

[Files]
Source: "..\dist\ReadingSnail\*"; DestDir: "{app}"; \
    Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; \
    Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "바탕화면에 바로가기 만들기"; \
    GroupDescription: "추가 작업:"

[Run]
Filename: "{app}\{#AppExe}"; Description: "지금 실행"; \
    Flags: nowait postinstall skipifsilent

[UninstallDelete]
; 설치 폴더 안에서 앱이 만든 것만 지운다.
Type: filesandordirs; Name: "{app}\__pycache__"

; 기록(%LOCALAPPDATA%\ReadingSnail)은 **지우지 않는다.**
; 다시 설치하면 그대로 이어서 쓴다. 지우고 싶으면 사용자가 직접 지운다.

[Code]
{ 자동 시작을 켠 적이 있으면 지울 때 그 값도 거둔다.

  안 거두면 Windows 가 로그인할 때마다 없어진 exe 를 띄우려 든다.
  설치할 때는 만들지 않는다 — 자동 시작은 **기본이 꺼짐**이고(SPEC 7항),
  사용자가 설정 창에서 켜야 생긴다.

  기록(%LOCALAPPDATA%\ReadingSnail)은 여기서도 손대지 않는다. }
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
    RegDeleteValue(HKEY_CURRENT_USER,
                   'Software\Microsoft\Windows\CurrentVersion\Run',
                   'ReadingSnail');
end;
