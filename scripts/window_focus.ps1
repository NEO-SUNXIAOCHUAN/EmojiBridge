# Task-start root focus only; no chat enumeration or message/favorite actions.
param([switch]$Server)
$ErrorActionPreference='Stop'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type @"
using System;
using System.Runtime.InteropServices;
using System.Text;
public class RootFocusGuard {
 [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
 [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
 [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr h);
 [DllImport("user32.dll")] public static extern uint GetDpiForWindow(IntPtr h);
 [DllImport("user32.dll")] public static extern bool SetProcessDpiAwarenessContext(IntPtr context);
 [DllImport("user32.dll",CharSet=CharSet.Unicode)] public static extern int GetClassNameW(IntPtr h,StringBuilder s,int n);
 [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h,out Rect r);
 [DllImport("user32.dll")] public static extern short GetAsyncKeyState(int k);
 public struct Rect { public int L,T,R,B; }
}
"@
[void][RootFocusGuard]::SetProcessDpiAwarenessContext([IntPtr](-4))
function Check($r,$root) {
 $h=[IntPtr][long]$r.window
 if($root.Current.ProcessId -ne [int]$r.pid -or (Get-Process -Id $r.pid).Path -ne $r.exe){throw 'process_identity_changed'}
 $kind=New-Object Text.StringBuilder 256
 [void][RootFocusGuard]::GetClassNameW($h,$kind,256)
 $clientKinds=@{'QQ.exe'='Chrome_WidgetWin_1';'Weixin.exe'='Qt51514QWindowIcon';'WeChat.exe'='Qt51514QWindowIcon'}
 $expectedKind=$clientKinds[[IO.Path]::GetFileName([string]$r.exe)]
 if(-not $expectedKind -or $r.kind -ne $expectedKind -or $kind.ToString() -ne $expectedKind){throw 'client_window_kind_changed'}
 if(-not [RootFocusGuard]::IsWindowVisible($h) -or [RootFocusGuard]::IsIconic($h)){throw 'window_not_visible'}
 if([RootFocusGuard]::GetDpiForWindow($h) -ne $r.dpi){throw 'client_display_scale_changed'}
 $b=New-Object RootFocusGuard+Rect
 if(-not [RootFocusGuard]::GetWindowRect($h,[ref]$b) -or (@($b.L,$b.T,$b.R,$b.B) -join ',') -ne ($r.rect -join ',')){throw 'window_moved_or_resized'}
 $fg=[RootFocusGuard]::GetForegroundWindow().ToInt64()
 if($fg -ne [long]$r.previous -and $fg -ne [long]$r.window){throw 'foreground_changed'}
 foreach($k in @(1,2,16,17,18,27,91,92)) {
  if(([RootFocusGuard]::GetAsyncKeyState($k) -band 0x8000) -ne 0){throw 'user_input_in_progress'}
 }
}
if(-not $Server){throw 'server_required'}
[Console]::Out.WriteLine('{"worker_ready":true}')
[Console]::Out.Flush()
while($null -ne ($line=[Console]::In.ReadLine())) {
 try {
  $r=ConvertFrom-Json $line
  $root=[System.Windows.Automation.AutomationElement]::FromHandle([IntPtr][long]$r.window)
  Check $r $root
  $method='already_foreground';$focusRect=@();$focusRuntime=@()
  if([RootFocusGuard]::GetForegroundWindow().ToInt64() -ne [long]$r.window){
   $focus=$root;$method='root_set_focus'
   if($r.kind -eq 'Chrome_WidgetWin_1'){
    # QQ's top-level UIA root is not focusable. Focus its unique navigation
    # search edit, without changing text, choosing a contact or touching chat.
    $condition=[System.Windows.Automation.PropertyCondition]::new([System.Windows.Automation.AutomationElement]::ControlTypeProperty,[System.Windows.Automation.ControlType]::Edit)
    $walker=[System.Windows.Automation.TreeWalker]::ControlViewWalker
    $edits=@($root.FindAll([System.Windows.Automation.TreeScope]::Descendants,$condition)|Where-Object {
     $parent=$walker.GetParent($_)
     $parent -and $parent.Current.ClassName -like '*main-search__search-input*' -and -not $_.Current.IsOffscreen -and $_.Current.IsEnabled -and $_.Current.IsKeyboardFocusable
    })
    if($edits.Count -ne 1){throw 'foreground_focus_control_not_unique'}
    $focus=$edits[0];$method='navigation_edit_target'
    $b=$focus.Current.BoundingRectangle
    $focusRect=@($b.Left,$b.Top,$b.Right,$b.Bottom);$focusRuntime=@($focus.GetRuntimeId())
    if($r.action -ne 'prepare'){throw 'foreground_focus_prepare_required'}
   }
   Check $r $root;if($r.kind -ne 'Chrome_WidgetWin_1'){$focus.SetFocus()}
  }
  Check $r $root
  @{ok=$true;method=$method;focus_rect=$focusRect;focus_runtime=$focusRuntime}|ConvertTo-Json -Compress
 } catch {
  $reason=$_.Exception.Message
  if($reason -notmatch '^[a-z][a-z0-9_]+$'){$reason='foreground_switch_denied'}
  @{ok=$false;reason=$reason}|ConvertTo-Json -Compress
 }
 [Console]::Out.Flush()
}
