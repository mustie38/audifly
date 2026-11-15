; ============================================================================
;  Audifly - Inno Setup Kurulum Betiği
; ============================================================================
;  Bu betik, PyInstaller ile üretilmiş "dist\Audifly\" klasörünü tek bir
;  "AudiflySetup.exe" kurulum dosyasına dönüştürür.
;
;  Önkoşul (önce bunu yap):
;    1) cd <mustiefly_qt'nin bir üst dizini>
;    2) pyinstaller mustiefly_qt\packaging\audifly.spec
;       -> çıktı: dist\Audifly\Audifly.exe ve yanındaki dosyalar
;
;  Sonra bu betiği derle:
;    Inno Setup Compiler (ISCC.exe) ile aç / derle:
;    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" packaging\audifly.iss
;    -> çıktı: packaging\Output\AudiflySetup.exe
;
;  NOT: Bu dosyanın "dist\Audifly" klasörünü bulabilmesi için, bu .iss
;  dosyasının mustiefly_qt\packaging\ altında, dist\ klasörünün de aynı üst
;  dizinde (mustiefly_qt ile kardeş) olması varsayılıyor. Kendi klasör
;  yapına göre aşağıdaki #define DistDir satırını güncelle.
; ============================================================================

#define MyAppName "Audifly"
#ifndef MyAppVersion
  #define MyAppVersion "0.4.3"   ; pyproject.toml ile aynı tut (release.yml /DMyAppVersion=... ile ezer)
#endif
#define MyAppPublisher "Audifly"
#define MyAppExeName "Audifly.exe"
#define MyAppURL "https://github.com/mustie38/audifly"

; PyInstaller çıktısının bulunduğu klasör (bu .iss dosyasına göre GÖRELİ yol)
#define DistDir "..\..\dist\Audifly"

[Setup]
AppId={{9F1E7C3A-6B2D-4E8F-9A1C-3D5E7F9B2C4A}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
; Varsayılan: kullanıcı klasörüne kurulum (yönetici izni gerekmez); kurulum sihirbazı
; isterse yönetici seçeneğini sunar.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog   ; kullanıcı isterse tüm kullanıcılar için (yönetici) kurabilir
OutputDir=Output
OutputBaseFilename=AudiflySetup
; Kurulum sihirbazı ikonu (python mustiefly_qt/packaging/make_icon.py ile üretilir):
SetupIconFile=audifly.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; Güncelleme sırasında çalışan Audifly varsa kurulum onu kapatmayı önerir
CloseApplications=yes
RestartApplications=no
UninstallDisplayIcon={app}\{#MyAppExeName}
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "turkish"; MessagesFile: "compiler:Languages\Turkish.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Geliştirme sırasında dist klasörüne yazılmış kullanıcı verisi (users.json vb.) pakete
; GİRMEZ (Excludes): aksi halde her kurulumda geliştiricinin ayarları kullanıcıya
; kopyalanır ya da kullanıcının ayarları sıfırlanırdı.
; PyInstaller'ın COLLECT ile ürettiği TÜM klasörü (exe + dll'ler + veri
; dosyaları) olduğu gibi kopyala.
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "users.json,last_session.json,users\*,logs\*,AUDIFLY_TASINDI.txt,*.corrupt-*"

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Uygulamanın çalışırken oluşturduğu log/ayar dosyalarını da temizlemek
; istersen buraya ekleyebilirsin (opsiyonel, varsayılan kapalı bırakıldı
; çünkü kullanıcı playlist/hesap verisini kaybetmek istemeyebilir).
; Type: filesandordirs; Name: "{app}\logs"

[Code]
{ VLC kurulu mu diye basit bir kayıt defteri kontrolü yapıp, yoksa kuruluma
  devam etmeden önce kullanıcıyı bilgilendiriyoruz. Bu bir engel değil,
  sadece uyarı - VLC olmadan program açılır ama oynatma çalışmaz. }
function IsVLCInstalled(): Boolean;
begin
  Result := RegKeyExists(HKLM, 'SOFTWARE\VideoLAN\VLC') or
            RegKeyExists(HKLM, 'SOFTWARE\WOW6432Node\VideoLAN\VLC');
end;

procedure InitializeWizard();
begin
  if not IsVLCInstalled() then
  begin
    MsgBox('VLC Media Player sisteminizde bulunamadı.' + #13#10 + #13#10 +
      'Audifly''nin müzik çalabilmesi için VLC Media Player''ın ayrıca ' +
      'kurulu olması gerekir (64-bit Python/uygulama için 64-bit VLC).' +
      #13#10#13#10 +
      'Kuruluma devam edebilirsiniz, ancak VLC''yi https://www.videolan.org/vlc/ ' +
      'adresinden ayrıca indirip kurmayı unutmayın.',
      mbInformation, MB_OK);
  end;
end;
