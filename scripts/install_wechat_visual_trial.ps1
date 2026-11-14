param([string]$AppDir,[switch]$CheckOnly,[switch]$Restore,[switch]$NonInteractive)
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
Add-Type -AssemblyName System.Windows.Forms
function ChildPath([string]$root,[string]$relative){
 $base=[IO.Path]::GetFullPath($root).TrimEnd('\')+'\'
 $candidate=[IO.Path]::GetFullPath([IO.Path]::Combine($base,$relative))
 if(-not $candidate.StartsWith($base,[StringComparison]::OrdinalIgnoreCase)){throw '补丁路径不在程序目录内'}
 return $candidate
}
function Digest([string]$path){
 if(-not [IO.File]::Exists($path)){return $null}
 $algorithm=[Security.Cryptography.SHA256]::Create()
 $stream=[IO.File]::OpenRead($path)
 try{return [BitConverter]::ToString($algorithm.ComputeHash($stream)).Replace('-','').ToLowerInvariant()}
 finally{$stream.Dispose();$algorithm.Dispose()}
}
try {
 $manifest=Get-Content -LiteralPath (Join-Path $PSScriptRoot 'patch-manifest.json') -Raw -Encoding UTF8|ConvertFrom-Json
 if(-not $AppDir){
  if($NonInteractive){throw '非交互校验必须指定程序目录'}
  $dialog=New-Object Windows.Forms.FolderBrowserDialog
  $dialog.Description='选择原 S0163 完整包中的 EB 文件夹（里面有 EmojiBridge.exe）'
  if($dialog.ShowDialog() -ne [Windows.Forms.DialogResult]::OK){exit 0}
  $AppDir=$dialog.SelectedPath
 }
 $AppDir=[IO.Path]::GetFullPath($AppDir)
 foreach($required in @('EmojiBridge.exe','runtime/python.exe','runtime/vision/cv2/__init__.py')){
  if(-not [IO.File]::Exists((ChildPath $AppDir $required))){throw '请选择 S0163 完整包的 EB 文件夹；主包缺少视觉组件，请改用完整测试包。'}
 }
 $backup=ChildPath $AppDir '.S0164-before-visual-test'
 foreach($entry in $manifest.files){
  $target=ChildPath $AppDir $entry.path
  $payload=ChildPath (Join-Path $PSScriptRoot 'payload') $entry.path
  if((Digest $payload) -ne $entry.sha256){throw ('补丁校验失败：'+$entry.path)}
  $current=Digest $target
  if($current -ne $entry.old_sha256 -and $current -ne $entry.sha256){throw ('程序文件不是本补丁支持的版本，未覆盖：'+$entry.path)}
  $saved=ChildPath $backup $entry.path
  if([IO.File]::Exists($saved) -and (Digest $saved) -ne $entry.old_sha256){throw ('原文件备份校验失败：'+$entry.path)}
  if($Restore -and $entry.old_sha256 -and $current -ne $entry.old_sha256 -and $current -eq $entry.sha256 -and (Digest $saved) -ne $entry.old_sha256){throw ('缺少可验证的原文件备份：'+$entry.path)}
 }
 if($CheckOnly){@{ok=$true;files=$manifest.files.Count;writes=0}|ConvertTo-Json -Compress;exit 0}
 $prefix=$AppDir.TrimEnd('\')+'\'
 Import-Module (Join-Path $PSHOME 'Modules/CimCmdlets/CimCmdlets.psd1') -ErrorAction Stop
 $running=@(Get-CimInstance Win32_Process | Where-Object {
  $_.ExecutablePath -and $_.ExecutablePath.StartsWith($prefix,[StringComparison]::OrdinalIgnoreCase)
 })
 if($running.Count){throw '请先保存作品，并正常退出此 EB 目录启动的 EmojiBridge，再运行补丁。补丁不会强制关闭任何窗口。'}
 foreach($entry in $manifest.files){
  $target=ChildPath $AppDir $entry.path
  $saved=ChildPath $backup $entry.path
  $current=Digest $target
  if($Restore){
   if($current -eq $entry.old_sha256){continue}
   if($entry.old_sha256){[IO.File]::Copy($saved,$target,$true)}
   elseif($current -eq $entry.sha256){[IO.File]::Delete($target)}
   if((Digest $target) -ne $entry.old_sha256){throw ('恢复校验失败：'+$entry.path)}
  }else{
   if($current -eq $entry.sha256){continue}
   if($entry.old_sha256 -and -not [IO.File]::Exists($saved)){
    $null=[IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($saved))
    [IO.File]::Copy($target,$saved,$false)
   }
   $null=[IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($target))
   [IO.File]::Copy((ChildPath (Join-Path $PSScriptRoot 'payload') $entry.path),$target,$true)
   if((Digest $target) -ne $entry.sha256){throw ('安装校验失败：'+$entry.path)}
  }
 }
 if($Restore){$message='已恢复原程序文件。素材、账号、草稿和传输记录均未删除。'}
 else{$message='视觉兼容测试补丁已安装。请打开 EmojiBridge.exe 测试转到微信。正常控件仍优先使用；控件空缺才切视觉。建议先测一张静图和一张 GIF。'}
 if($NonInteractive){@{ok=$true;restore=[bool]$Restore;files=$manifest.files.Count}|ConvertTo-Json -Compress}
 else{$null=[Windows.Forms.MessageBox]::Show($message,'EmojiBridge S0164 测试补丁')}
}catch{
 if($CheckOnly -or $NonInteractive){Write-Error $_;exit 1}
 $null=[Windows.Forms.MessageBox]::Show($_.Exception.Message,'未完成补丁操作')
 exit 1
}
