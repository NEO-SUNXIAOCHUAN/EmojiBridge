param([switch]$Worker,[switch]$RequestAccessibility,[string]$OutputDirectory=$PSScriptRoot)
# Standalone, bounded read-only probe. No Name/Value/chat text is collected.
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
if(-not $Worker){
 $psi=[Diagnostics.ProcessStartInfo]::new()
 $psi.FileName=Join-Path $PSHOME 'powershell.exe'
 $psi.Arguments='-NoProfile -ExecutionPolicy Bypass -File "'+$PSCommandPath+'" -Worker'
 if($RequestAccessibility){$psi.Arguments+=' -RequestAccessibility'}
 $psi.UseShellExecute=$false;$psi.CreateNoWindow=$true
 $psi.RedirectStandardOutput=$true;$psi.RedirectStandardError=$true
 $psi.StandardOutputEncoding=[Text.UTF8Encoding]::new($false)
 $process=[Diagnostics.Process]::new();$process.StartInfo=$psi
 try{
  [void]$process.Start()
  $out=$process.StandardOutput.ReadToEndAsync();$err=$process.StandardError.ReadToEndAsync()
  if(-not $process.WaitForExit(20000)){
   $process.Kill();$process.WaitForExit()
   $result=@{schema='wechat-controls-readonly-S0085';ok=$false;reason='probe_timeout';client_actions=0}
  }else{
   try{$result=ConvertFrom-Json $out.GetAwaiter().GetResult()}
   catch{$result=@{schema='wechat-controls-readonly-S0085';ok=$false;reason='probe_worker_failed';client_actions=0}}
  }
 }finally{$process.Dispose()}
 $name='表情互通-控件诊断-'+(Get-Date -Format 'yyyyMMdd-HHmmss')+'-'+[guid]::NewGuid().ToString('N').Substring(0,4)+'.json'
 $file=Join-Path $OutputDirectory $name
 [IO.File]::WriteAllText($file,($result|ConvertTo-Json -Depth 9),[Text.UTF8Encoding]::new($false))
 Write-Output ('只读检查结束，结果文件：'+$file)
 Write-Output '没有切换会话、发送、收藏或删除。请把这个 JSON 反馈给邀请你内测的人。'
 exit
}
$report=[ordered]@{schema='wechat-controls-readonly-S0085';ok=$false;client_actions=0;complete=$false}
$stage='windows'
try{
 Add-Type -AssemblyName UIAutomationClient
 Add-Type -AssemblyName UIAutomationTypes
 Add-Type @"
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;
public class EBWechatReadProbe {
 public delegate bool Callback(IntPtr h,IntPtr p);
 [DllImport("user32.dll")] static extern bool EnumWindows(Callback f,IntPtr p);
 [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
 [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr h);
 [DllImport("user32.dll")] public static extern uint GetDpiForWindow(IntPtr h);
 [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h,out uint p);
 [DllImport("user32.dll",CharSet=CharSet.Unicode)] static extern int GetClassName(IntPtr h,StringBuilder s,int n);
 [DllImport("user32.dll")] public static extern bool SetProcessDpiAwarenessContext(IntPtr c);
 [DllImport("oleacc.dll")] static extern int AccessibleObjectFromWindow(IntPtr h,uint id,ref Guid iid,out IntPtr result);
 [DllImport("kernel32.dll")] static extern IntPtr OpenProcess(uint access,bool inherit,uint pid);
 [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr h);
 [DllImport("advapi32.dll")] static extern bool OpenProcessToken(IntPtr p,uint access,out IntPtr token);
 [DllImport("advapi32.dll")] static extern bool GetTokenInformation(IntPtr t,int kind,IntPtr data,int size,out int needed);
 [DllImport("advapi32.dll")] static extern IntPtr GetSidSubAuthorityCount(IntPtr sid);
 [DllImport("advapi32.dll")] static extern IntPtr GetSidSubAuthority(IntPtr sid,uint index);
 public static string Integrity(uint pid){
  IntPtr p=OpenProcess(0x1000,false,pid),t=IntPtr.Zero,data=IntPtr.Zero;
  try{
   if(p==IntPtr.Zero || !OpenProcessToken(p,8,out t))return "unknown";
   int size;GetTokenInformation(t,25,IntPtr.Zero,0,out size);
   if(size<=0 || size>4096)return "unknown";
   data=Marshal.AllocHGlobal(size);
   if(!GetTokenInformation(t,25,data,size,out size))return "unknown";
   IntPtr sid=Marshal.ReadIntPtr(data);byte n=Marshal.ReadByte(GetSidSubAuthorityCount(sid));
   if(n==0)return "unknown";
   int rid=Marshal.ReadInt32(GetSidSubAuthority(sid,(uint)(n-1)));
   return rid>=16384?"system":rid>=12288?"high":rid>=8448?"medium_plus":rid>=8192?"medium":rid>=4096?"low":"untrusted";
  }finally{if(data!=IntPtr.Zero)Marshal.FreeHGlobal(data);if(t!=IntPtr.Zero)CloseHandle(t);if(p!=IntPtr.Zero)CloseHandle(p);}
 }
 public static int Request(IntPtr h){
  Guid iid=new Guid("618736e0-3c3d-11cf-810c-00aa00389b71");IntPtr obj=IntPtr.Zero;
  try{return AccessibleObjectFromWindow(h,0xfffffffc,ref iid,out obj);}
  finally{if(obj!=IntPtr.Zero)Marshal.Release(obj);}
 }
 public static IntPtr[] Windows(){var a=new List<IntPtr>();EnumWindows((h,p)=>{a.Add(h);return true;},IntPtr.Zero);return a.ToArray();}
 public static string Kind(IntPtr h){var s=new StringBuilder(128);GetClassName(h,s,128);return s.ToString();}
}
"@
 $report.dpi_aware=[EBWechatReadProbe]::SetProcessDpiAwarenessContext([IntPtr](-4))
 $clients=@(Get-Process -Name Weixin -ErrorAction SilentlyContinue)
 $windows=@()
 foreach($handle in [EBWechatReadProbe]::Windows()){
  $owner=[uint32]0;[void][EBWechatReadProbe]::GetWindowThreadProcessId($handle,[ref]$owner)
  $client=@($clients|Where-Object {$_.Id -eq $owner})
  if($client.Count -ne 1 -or -not [EBWechatReadProbe]::IsWindowVisible($handle) -or [EBWechatReadProbe]::IsIconic($handle)){continue}
  if([EBWechatReadProbe]::Kind($handle) -notmatch '^Qt[0-9]+QWindowIcon$'){continue}
  $root=[System.Windows.Automation.AutomationElement]::FromHandle($handle)
  $bounds=$root.Current.BoundingRectangle
  if($bounds.Width -lt 500 -or $bounds.Height -lt 400){continue}
  $windows+=@{root=$root;bounds=$bounds;handle=$handle;owner=$owner;dpi=[EBWechatReadProbe]::GetDpiForWindow($handle);version=$client[0].MainModule.FileVersionInfo.FileVersion}
 }
 $report.window_count=$windows.Count
 if($windows.Count -ne 1){$report.reason='wechat_window_missing_or_ambiguous'}
 else{
  $stage='structure';$w=$windows[0];$root=$w.root;$bounds=$w.bounds
  $report.version=$w.version;$report.dpi=$w.dpi
  $report.probe_integrity=[EBWechatReadProbe]::Integrity([uint32]$PID)
  $report.wechat_integrity=[EBWechatReadProbe]::Integrity($w.owner)
  $report.window_size=@([int]$bounds.Width,[int]$bounds.Height)
  $prefix='content_view.top_content_view.title_h_view.left_v_view.left_content_v_view.left_ui_.big_title_line_h_view'
  $specs=[ordered]@{
   messages=@('chat_message_list','chat_message_list')
   composer=@('chat_input_field','chat_input_field')
   sessions=@('session_list','session_list')
   header_leaf=@(($prefix+'.current_chat_name_label'),'current_chat_name_label')
   header_parent=@($prefix,'big_title_line_h_view')
   helper_entry=@('session_item_文件传输助手','session_item_文件传输助手')
  }
  $roles=[ordered]@{}
  foreach($key in $specs.Keys){$roles[$key]=[ordered]@{exact=0;exact_visible=0;leaf=0;leaf_visible=0;matches=@()}}
  $nodes=$root.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)
  $report.nodes_before_request=$nodes.Count
  $report.accessibility_request='not_requested'
  if($RequestAccessibility -and $nodes.Count -le 2){
   $stage='standard_accessibility_request'
   $nowOwner=[uint32]0;[void][EBWechatReadProbe]::GetWindowThreadProcessId($w.handle,[ref]$nowOwner)
   if($nowOwner -ne $w.owner -or -not [EBWechatReadProbe]::IsWindowVisible($w.handle)){throw 'window_changed'}
   # Standard MSAA query only: no text, memory patch, restart or global settings.
   $report.accessibility_hresult=[EBWechatReadProbe]::Request($w.handle)
   $report.accessibility_request='standard_msaa_once'
   Start-Sleep -Milliseconds 250
   $root=[System.Windows.Automation.AutomationElement]::FromHandle($w.handle)
   $nodes=$root.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)
   $stage='structure'
  }elseif($RequestAccessibility){$report.accessibility_request='skipped_tree_present'}
  $report.node_count=$nodes.Count;$candidates=@();$report.complete=($nodes.Count -le 5000)
  function Relative-Box($b){
   if($b.IsEmpty -or [double]::IsInfinity($b.Left) -or [double]::IsNaN($b.Left)){return @()}
   return @([int]($b.Left-$bounds.Left),[int]($b.Top-$bounds.Top),[int]$b.Width,[int]$b.Height)
  }
  for($i=0;$i -lt [Math]::Min(5000,$nodes.Count);$i++){
   $current=$nodes[$i].Current
   $id=$current.AutomationId;$leaf=($id -split '\.')[-1]
   $typeId=$current.ControlType.Id;$visible=-not $current.IsOffscreen
   $matched=@()
   foreach($key in $specs.Keys){
    $exact=$id -ceq $specs[$key][0];$suffix=$leaf -ceq $specs[$key][1]
    if($exact){$roles[$key].exact++;if($visible){$roles[$key].exact_visible++}}
    if($suffix){$roles[$key].leaf++;if($visible){$roles[$key].leaf_visible++}}
    if($exact -or $suffix){
     $matched+=,$key
     if($roles[$key].matches.Count -lt 8){$roles[$key].matches+=@{type=$typeId;visible=$visible;box=(Relative-Box $current.BoundingRectangle)}}
    }
   }
   # Only anonymous List/Edit geometry; no row IDs, text, names, paths or values.
   if($typeId -in @(50004,50008) -and $candidates.Count -lt 40){
    $candidates+=@{type=$typeId;visible=$visible;box=(Relative-Box $current.BoundingRectangle);known_roles=$matched;id_empty=([string]::IsNullOrEmpty($id))}
   }
  }
  $report.roles=$roles;$report.list_edit_geometry=$candidates
  $report.ok=$true
  if($root.Current.BoundingRectangle -ne $bounds){$report.ok=$false;$report.complete=$false;$report.reason='window_changed_during_probe'}
 }
}catch{
 $report.ok=$false;$report.reason='probe_failed';$report.stage=$stage
 $report.error_type=$_.Exception.GetType().Name
}
$report|ConvertTo-Json -Depth 9 -Compress
