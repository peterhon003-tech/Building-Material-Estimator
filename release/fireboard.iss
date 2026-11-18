; ============================================================
;  防火板計價系統 — Windows 安裝程式（Inno Setup 6）
;  由 build_installer.ps1 編譯，請勿直接執行 ISCC，除非你知道要傳入的參數：
;    /DVersion=2026-11-17_1030  /DStageDir=C:\fireboard_build\stage  /DOutDir=C:\fireboard_release
;  StageDir 內要有 fireboard-base.tar、fireboard-install.run 和 wsl.x64.msi
; ============================================================

#ifndef Version
  #define Version "dev"
#endif
#ifndef StageDir
  #define StageDir "C:\fireboard_build\stage"
#endif
#ifndef OutDir
  #define OutDir "C:\fireboard_release"
#endif
#define AppIdGuid "8F1C2A57-3B4E-4D2A-9C1F-6A2E5B7D9E10"

[Setup]
AppId={{{#AppIdGuid}}
AppName=Fireboard Estimator 防火板計價系統
AppVersion={#Version}
AppPublisher=Easy Smart Engineering
DefaultDirName={commonappdata}\Fireboard
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyMemo=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.19041
OutputDir={#OutDir}
OutputBaseFilename=FireboardSetup-{#Version}
Compression=lzma2/fast
SolidCompression=no
WizardStyle=modern
SetupLogging=yes
UninstallDisplayName=Fireboard Estimator 防火板計價系統
CloseApplications=no
RestartIfNeededByRun=no
UsedUserAreasWarning=no

[Languages]
Name: "en"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "{#StageDir}\fireboard-base.tar";    DestDir: "{app}"; Flags: ignoreversion deleteafterinstall
Source: "{#StageDir}\fireboard-install.run"; DestDir: "{app}"; Flags: ignoreversion deleteafterinstall nocompression
Source: "{#StageDir}\wsl.x64.msi";         Flags: dontcopy
Source: "enable_wsl.ps1";                   Flags: dontcopy
Source: "setup_main.ps1";           DestDir: "{app}"; Flags: ignoreversion
Source: "windows_setup.ps1";        DestDir: "{app}"; Flags: ignoreversion
Source: "uninstall_fireboard.ps1";  DestDir: "{app}"; Flags: ignoreversion
Source: "..\wsl_portproxy.ps1";     DestDir: "{app}"; Flags: ignoreversion

[Run]
Filename: "http://localhost:8000"; Description: "打開防火板計價系統 http://localhost:8000"; Flags: shellexec postinstall nowait skipifsilent runasoriginaluser; Check: InstallOk

[UninstallRun]
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; \
  Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\uninstall_fireboard.ps1"" -Distro Fireboard -KeepOpsDir -Yes"; \
  Flags: runhidden waituntilterminated; RunOnceId: "RemoveFireboard"

[UninstallDelete]
Type: filesandordirs; Name: "{app}"
Type: dirifempty;     Name: "{localappdata}\Fireboard\wsl"
Type: dirifempty;     Name: "{localappdata}\Fireboard"

[Code]
const
  UninstallKey = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{{#AppIdGuid}}_is1';
  RunOnceKey   = 'Software\Microsoft\Windows\CurrentVersion\RunOnce';
  FlagKey      = 'Software\Fireboard';

var
  ModePage: TInputOptionWizardPage;
  BackupPage: TInputDirWizardPage;
  PwPage: TInputQueryWizardPage;
  InstallPage, WslPage: TOutputProgressWizardPage;
  InstallSucceeded: Boolean;
  InstallExitCode: Integer;

function LogonUser(lpszUsername, lpszDomain, lpszPassword: String; dwLogonType, dwLogonProvider: Integer; var phToken: Longword): Boolean;
  external 'LogonUserW@advapi32.dll stdcall';
function CloseHandle(hObject: Longword): Boolean;
  external 'CloseHandle@kernel32.dll stdcall';

function InstallOk: Boolean;
begin
  Result := InstallSucceeded;
end;

function WslPath: String;
begin
  { WSL 套件裝在 Program Files\WSL；System32 內的 wsl.exe 不一定存在 }
  Result := ExpandConstant('{commonpf64}\WSL\wsl.exe');
  if not FileExists(Result) then
    Result := ExpandConstant('{sys}\wsl.exe');
end;

function WslReady: Boolean;
var
  RC: Integer;
begin
  { wsl --version 只在已安裝新版 WSL（2.x）時成功；wsl --status 在沒有任何 Linux 系統時也會失敗，所以不用它 }
  Result := FileExists(WslPath) and Exec(WslPath, '--version', '', SW_HIDE, ewWaitUntilTerminated, RC) and (RC = 0);
end;

function InitializeSetup: Boolean;
begin
  Result := True;
  if RegKeyExists(HKLM, UninstallKey) then
  begin
    MsgBox('這部電腦已經安裝了防火板計價系統。' + #13#10#13#10 +
           '如要重新安裝，請先到「設定 > 應用程式」解除安裝 Fireboard Estimator（數據會被刪除，備份資料夾會保留）。',
           mbInformation, MB_OK);
    Result := False;
  end;
end;

procedure InitializeWizard;
begin
  ModePage := CreateInputOptionPage(wpWelcome,
    '使用範圍', '誰可以打開防火板計價系統？',
    '選擇後按 Next。之後可以用 windows_setup.ps1 更改。', True, False);
  ModePage.Add('只限這部電腦（http://localhost:8000）');
  ModePage.Add('公司網絡內的電腦都可以（http://這部電腦的IP:8000）');
  ModePage.SelectedValueIndex := 0;

  BackupPage := CreateInputDirPage(ModePage.ID,
    '備份資料夾', '每小時自動備份數據庫到哪裡？',
    '安裝後只有你的 Windows 帳戶、SYSTEM 和管理員可以讀取這個資料夾。', False, '');
  BackupPage.Add('');
  BackupPage.Values[0] := 'C:\fireboard_backup';

  PwPage := CreateInputQueryPage(BackupPage.ID,
    'Windows 密碼', '開機自動啟動需要 ' + GetUserNameString + ' 的 Windows 密碼',
    '系統會在開機時（無人登入也可）自動啟動。密碼只交給 Windows 工作排程器保存。' + #13#10 +
    '如用 Microsoft 帳戶登入，請輸入 Microsoft 帳戶的密碼，不是 PIN。');
  PwPage.Add('密碼：', True);
  PwPage.Add('再輸入一次：', True);

  WslPage := CreateOutputProgressPage('正在安裝 WSL', '安裝 Windows 子系統 Linux 版，約 1 至 5 分鐘。');
  InstallPage := CreateOutputProgressPage('正在安裝防火板計價系統', '約 5 至 15 分鐘，請勿關閉這個視窗。');
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  Token: Longword;
begin
  Result := True;
  if CurPageID = BackupPage.ID then
  begin
    if (Length(BackupPage.Values[0]) < 3) or (Pos(':\', BackupPage.Values[0]) <> 2) then
    begin
      MsgBox('請選擇本機硬碟上的資料夾，例如 C:\fireboard_backup。', mbError, MB_OK);
      Result := False;
    end;
  end
  else if CurPageID = PwPage.ID then
  begin
    if PwPage.Values[0] = '' then
    begin
      MsgBox('請輸入 Windows 密碼。', mbError, MB_OK);
      Result := False;
    end
    else if PwPage.Values[0] <> PwPage.Values[1] then
    begin
      MsgBox('兩次輸入的密碼不相同。', mbError, MB_OK);
      Result := False;
    end
    else if LogonUser(GetUserNameString, GetEnv('USERDOMAIN'), PwPage.Values[0], 2, 0, Token) then
      CloseHandle(Token)
    else
      Result := (MsgBox('Windows 未能用這個密碼登入 ' + GetUserNameString + '。密碼可能不正確。' + #13#10#13#10 +
                        '仍然繼續？（密碼不正確的話，開機自動啟動會失敗）', mbConfirmation, MB_YESNO) = IDYES);
  end;
end;

{ 在背景執行 PowerShell 腳本，每半秒讀取進度檔（"<百分比> <步驟>"）更新進度頁。
  腳本最後寫入 "100 done <代碼>" 或 "100 failed <代碼>"。傳回：done 的代碼；failed 的代碼 + 1000000；
  96 = 未能啟動；97 = 60 秒內沒有進度；98 = 超時 }
function StepText(const Step: String): String;
begin
  if Step = 'check_virt' then Result := '檢查電腦是否已開啟虛擬化'
  else if Step = 'wsl_feature' then Result := '開啟 Windows 功能「Windows 子系統 Linux 版」（已開啟會跳過）'
  else if Step = 'vmp_feature' then Result := '開啟 Windows 功能「虛擬機器平台」（已開啟會跳過，最多 15 分鐘）'
  else if Step = 'wsl_package' then Result := '安裝 WSL'
  else if Step = 'check_wsl' then Result := '檢查 WSL'
  else if Step = 'import' then Result := '建立 Linux 系統（Ubuntu + Docker），約 1 至 3 分鐘'
  else if Step = 'start_docker' then Result := '啟動 Linux 和 Docker'
  else if Step = 'extract' then Result := '解壓系統和數據'
  else if Step = 'prepare' then Result := '檢查環境及建立設定'
  else if Step = 'load_images' then Result := '載入網站和數據庫程式，約 1 至 3 分鐘'
  else if Step = 'start_db' then Result := '啟動數據庫'
  else if Step = 'restore' then Result := '還原數據'
  else if Step = 'start_web' then Result := '啟動網站'
  else if Step = 'backup_job' then Result := '設定每小時備份'
  else if Step = 'lock_backup' then Result := '設定備份資料夾權限'
  else if Step = 'tasks' then Result := '設定開機自動啟動'
  else if Step = 'check_site' then Result := '檢查網站'
  else Result := '準備中';
end;

function RunWithProgress(Page: TOutputProgressWizardPage; const Params, WorkDir, ProgFile: String; MaxMinutes: Integer): Integer;
var
  Raw: AnsiString;
  Line, Step, LastStep: String;
  SpacePos, Pct, Ticks, ErrorCode: Integer;
  Done, Seen: Boolean;
begin
  Done := False; Seen := False; Pct := 0; Ticks := 0; LastStep := '';
  Result := 98;
  DeleteFile(ProgFile);
  Page.SetText(StepText('') + '…', '0%');
  Page.SetProgress(0, 100);
  Page.Show;
  try
    if not Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'), Params, WorkDir,
                SW_HIDE, ewNoWait, ErrorCode) then
    begin
      Result := 96;
      Exit;
    end;
    while (not Done) and (Ticks < MaxMinutes * 120) do
    begin
      Sleep(500);
      Ticks := Ticks + 1;
      if LoadStringFromFile(ProgFile, Raw) then
      begin
        Line := Trim(String(Raw));
        SpacePos := Pos(' ', Line);
        if SpacePos > 0 then
        begin
          Seen := True;
          Pct := StrToIntDef(Copy(Line, 1, SpacePos - 1), Pct);
          Step := Trim(Copy(Line, SpacePos + 1, Length(Line)));
          if Copy(Step, 1, 5) = 'done ' then
          begin
            Done := True;
            Result := StrToIntDef(Trim(Copy(Step, 6, 10)), 0);
          end
          else if Copy(Step, 1, 7) = 'failed ' then
          begin
            Done := True;
            Result := 1000000 + StrToIntDef(Trim(Copy(Step, 8, 10)), 1);
          end
          else
            LastStep := Step;
        end;
      end;
      if (not Seen) and (Ticks > 120) then
      begin
        Result := 97;
        Done := True;
      end;
      Page.SetText(StepText(LastStep) + '…',
        IntToStr(Pct) + '%     已用時間 ' + Format('%d:%.2d', [Ticks div 120, (Ticks div 2) mod 60]));
      Page.SetProgress(Pct, 100);
    end;
  finally
    Page.Hide;
  end;
end;

{ 確保 WSL 可以運行（enable_wsl.ps1）：檢查 BIOS 虛擬化、開啟兩個 Windows 功能（已開啟就跳過，
  每步最多等 15 分鐘）、安裝內附的 WSL 套件。需要時重新開機，登入後安裝程式自動再開啟；最多 2 次。 }
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  LogFile, Params: String;
  Attempts: Cardinal;
  Rc: Integer;
begin
  Result := '';
  if WslReady and not RegValueExists(HKLM, FlagKey, 'WslRebootPending') then Exit;

  ForceDirectories(ExpandConstant('{commonappdata}\Fireboard'));
  LogFile := ExpandConstant('{commonappdata}\Fireboard\wsl_install.log');
  if not RegQueryDWordValue(HKLM, FlagKey, 'WslInstallAttempts', Attempts) then Attempts := 0;
  RegDeleteValue(HKLM, FlagKey, 'WslRebootPending');

  ExtractTemporaryFile('wsl.x64.msi');
  ExtractTemporaryFile('enable_wsl.ps1');
  Params := '-NoProfile -ExecutionPolicy Bypass -File "' + ExpandConstant('{tmp}\enable_wsl.ps1') + '"' +
            ' -Msi "' + ExpandConstant('{tmp}\wsl.x64.msi') + '"' +
            ' -Log "' + LogFile + '"' +
            ' -ProgressFile "' + ExpandConstant('{tmp}\wsl_progress.txt') + '"';
  Rc := RunWithProgress(WslPage, Params, ExpandConstant('{tmp}'), ExpandConstant('{tmp}\wsl_progress.txt'), 45);

  if Rc = 0 then Exit;     { WSL 已可使用，不用重新開機 }

  if Rc = 1000023 then
  begin
    Result := '這部電腦未開啟「虛擬化」，WSL 不能運行。' + #13#10#13#10 +
              '這要在電腦的 BIOS / UEFI 設定中開啟，程式無法代為開啟：' + #13#10 +
              '1. 重新開機，開機畫面按 F2 / Del / F10（視乎電腦品牌）進入 BIOS。' + #13#10 +
              '2. 找 Intel Virtualization Technology（VT-x）或 AMD SVM，設為 Enabled。' + #13#10 +
              '3. 儲存並重新開機，再執行本安裝程式。' + #13#10#13#10 +
              '確認方法：工作管理員 > 效能 > CPU，「虛擬化」應顯示「已啟用」。';
    Exit;
  end;
  if Rc = 1000020 then
  begin
    Result := 'Windows 開啟「虛擬機器平台」功能時停住（超過 15 分鐘），已停止。' + #13#10#13#10 +
              '通常是 Windows Update 未完成，或 Windows 元件需要修復。請：' + #13#10 +
              '1. 到「設定 > Windows Update」完成所有更新，並重新開機。' + #13#10 +
              '2. 如仍失敗，以系統管理員身分開 PowerShell，執行：' + #13#10 +
              '     DISM /Online /Cleanup-Image /RestoreHealth' + #13#10 +
              '     sfc /scannow' + #13#10 +
              '   然後重新開機。' + #13#10 +
              '3. 再執行本安裝程式。' + #13#10#13#10 +
              '紀錄：' + LogFile;
    Exit;
  end;
  if Rc <> 3010 then
  begin
    Result := '未能安裝 WSL（代碼 ' + IntToStr(Rc) + '）。' + #13#10#13#10 +
              '請先完成 Windows Update 並重新開機，再執行本安裝程式。' + #13#10#13#10 +
              '紀錄：' + LogFile;
    Exit;
  end;

  { 需要重新開機 }
  if Attempts >= 2 then
  begin
    Result := '已重新開機兩次，WSL 仍未準備好。' + #13#10#13#10 + '紀錄：' + LogFile;
    RegDeleteValue(HKLM, FlagKey, 'WslInstallAttempts');
    Exit;
  end;
  RegWriteDWordValue(HKLM, FlagKey, 'WslInstallAttempts', Attempts + 1);
  RegWriteDWordValue(HKLM, FlagKey, 'WslRebootPending', 1);
  RegWriteStringValue(HKLM, RunOnceKey, 'FireboardSetup', '"' + ExpandConstant('{srcexe}') + '"');
  NeedsRestart := True;
  Result := '已開啟 WSL，需要重新開機。' + #13#10#13#10 +
            '請按下面的選項重新開機。重新開機並登入後，安裝程式會自動再次開啟，' +
            '再輸入一次選項和密碼即可完成安裝。';
end;


procedure CurStepChanged(CurStep: TSetupStep);
var
  AppDir, PwFile, ProgFile, Mode, BackupDir, Params: String;
  Lines: TArrayOfString;
  ErrorCode: Integer;
begin
  if CurStep <> ssPostInstall then Exit;

  AppDir := ExpandConstant('{app}');
  PwFile := ExpandConstant('{tmp}\pw.txt');
  ProgFile := ExpandConstant('{tmp}\progress.txt');
  SetArrayLength(Lines, 1);
  Lines[0] := PwPage.Values[0];
  SaveStringsToUTF8File(PwFile, Lines, False);

  if ModePage.SelectedValueIndex = 0 then Mode := 'Local' else Mode := 'Network';
  BackupDir := RemoveBackslashUnlessRoot(BackupPage.Values[0]);

  Params := '-NoProfile -ExecutionPolicy Bypass -File "' + AppDir + '\setup_main.ps1"' +
            ' -AppDir "' + AppDir + '" -Mode ' + Mode +
            ' -BackupDir "' + BackupDir + '" -PasswordFile "' + PwFile + '"' +
            ' -ProgressFile "' + ProgFile + '"';

  InstallExitCode := RunWithProgress(InstallPage, Params, AppDir, ProgFile, 180);
  if InstallExitCode >= 1000000 then InstallExitCode := InstallExitCode - 1000000;
  InstallSucceeded := (InstallExitCode = 0);
  DeleteFile(PwFile);

  if InstallSucceeded then
  begin
    RegDeleteValue(HKLM, FlagKey, 'WslInstallStarted');
    RegDeleteValue(HKLM, FlagKey, 'WslInstallAttempts');
    RegDeleteValue(HKLM, FlagKey, 'WslRebootPending');
    RegDeleteKeyIfEmpty(HKLM, FlagKey);
    RegDeleteValue(HKLM, RunOnceKey, 'FireboardSetup');
  end
  else
  begin
    MsgBox('安裝未能完成（代碼 ' + IntToStr(InstallExitCode) + '）。' + #13#10#13#10 +
           '按 OK 會打開安裝紀錄 setup.log，最後幾行有原因。' + #13#10 +
           '修正後，請先到「設定 > 應用程式」解除安裝 Fireboard Estimator，再重新執行安裝程式。',
           mbError, MB_OK);
    ShellExec('', 'notepad.exe', '"' + AppDir + '\setup.log"', '', SW_SHOW, ewNoWait, ErrorCode);
  end;
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if CurPageID = wpFinished then
  begin
    if InstallSucceeded then
    begin
      if ModePage.SelectedValueIndex = 0 then
        WizardForm.FinishedLabel.Caption := '防火板計價系統已安裝，只限這部電腦使用：http://localhost:8000' + #13#10#13#10 +
          '帳戶和密碼與原本電腦相同。之後開機會自動啟動，數據每小時備份到 ' + BackupPage.Values[0] + '。'
      else
        WizardForm.FinishedLabel.Caption := '防火板計價系統已安裝。這部電腦：http://localhost:8000；其他電腦：http://這部電腦的IP:8000' + #13#10#13#10 +
          '帳戶和密碼與原本電腦相同。之後開機會自動啟動，數據每小時備份到 ' + BackupPage.Values[0] + '。';
    end
    else
      WizardForm.FinishedLabel.Caption := '安裝未完成。請查看 ' + ExpandConstant('{app}') + '\setup.log。';
  end;
end;

function InitializeUninstall: Boolean;
begin
  Result := MsgBox('解除安裝會刪除防火板計價系統和系統內的全部數據（數據庫、設定）。' + #13#10 +
                   '備份資料夾不會刪除。' + #13#10#13#10 + '確定要解除安裝？',
                   mbConfirmation, MB_YESNO) = IDYES;
end;
