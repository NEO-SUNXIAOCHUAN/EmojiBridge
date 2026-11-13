# Experimental locator only. No favorite cell is ever invoked, sent or imported.
param([switch]$Server)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'client_compat.ps1')
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class QQReadOnlyGuard {
 [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
 [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h,out uint p);
 [DllImport("user32.dll")] public static extern uint GetDpiForWindow(IntPtr h);
 [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
 [DllImport("user32.dll")] public static extern short GetAsyncKeyState(int key);
}
"@
function Check-Window($request, [bool]$foreground=$false) {
 $handle=[IntPtr][long]$request.window
 $ownerId=[uint32]0
 [void][QQReadOnlyGuard]::GetWindowThreadProcessId($handle,[ref]$ownerId)
 if($ownerId -ne [int]$request.pid){throw 'window_identity_changed'}
 $exe=(Get-Process -Id $ownerId).Path
 if($exe -ne [string]$request.exe -or [IO.Path]::GetFileName($exe) -ne 'QQ.exe'){throw 'process_identity_changed'}
 Confirm-BridgeVersion 'qq' $exe
 if([QQReadOnlyGuard]::GetDpiForWindow($handle) -ne 96){throw 'client_dpi_not_tested'}
 if(-not [QQReadOnlyGuard]::IsWindowVisible($handle)){throw 'window_not_visible'}
 if($foreground -and [QQReadOnlyGuard]::GetForegroundWindow() -ne $handle){throw 'foreground_changed'}
 if(([QQReadOnlyGuard]::GetAsyncKeyState(27) -band 0x8000) -ne 0){throw 'cancelled_escape'}
}
function Find-Visible($root, $property, $value) {
 $condition=[System.Windows.Automation.PropertyCondition]::new($property,$value)
 @($root.FindAll([System.Windows.Automation.TreeScope]::Descendants,$condition)|Where-Object {-not $_.Current.IsOffscreen})
}
function Panel($root) {
 $found=@(Find-Visible $root ([System.Windows.Automation.AutomationElement]::ClassNameProperty) 'sticker-panel')
 if($found.Count -gt 1){throw 'qq_uia_panel_not_unique'}
 if($found.Count -eq 1){return $found[0]}
 return $null
}
function Favorite-Grid($panel) {
 if($null -eq $panel){return $null}
 $found=@(Find-Visible $panel ([System.Windows.Automation.AutomationElement]::ClassNameProperty) 'sticker-container'|
   Where-Object {$_.Current.Name -eq '收藏表情列表'})
 if($found.Count -gt 1){throw 'qq_uia_grid_not_unique'}
 if($found.Count -eq 1){return $found[0]}
 return $null
}
function Bounds($node) {
 $r=$node.Current.BoundingRectangle
 return @($r.Left,$r.Top,$r.Right,$r.Bottom)
}
function Probe($request) {
 if($request.action -notin @('snapshot','open-favorites')){throw 'invalid_readonly_action'}
 Check-Window $request
 $root=[System.Windows.Automation.AutomationElement]::FromHandle([IntPtr][long]$request.window)
 $panel=Panel $root
 $opened=$false; $selected=$false
 if($request.action -eq 'open-favorites') {
  Check-Window $request $true
  if($null -eq $panel) {
   # Restrict the only opening action to the named toolbar button, never a cell.
   $bars=@(Find-Visible $root ([System.Windows.Automation.AutomationElement]::ControlTypeProperty) ([System.Windows.Automation.ControlType]::ToolBar))
   $buttons=@(foreach($bar in $bars){Find-Visible $bar ([System.Windows.Automation.AutomationElement]::NameProperty) '表情'|
     Where-Object {$_.Current.ControlType -eq [System.Windows.Automation.ControlType]::Button}})
   if($buttons.Count -ne 1){throw 'qq_uia_emoji_button_not_unique'}
   $pattern=$buttons[0].GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)
   Check-Window $request $true
   $pattern.Invoke(); $opened=$true
   $deadline=[DateTime]::UtcNow.AddSeconds(2)
   do {$panel=Panel $root; if($null -ne $panel){break}; Start-Sleep -Milliseconds 50} while([DateTime]::UtcNow -lt $deadline)
  }
  if($null -eq $panel){throw 'qq_uia_panel_not_observed_no_retry'}
  if($null -eq (Favorite-Grid $panel)) {
   $tabs=@(Find-Visible $panel ([System.Windows.Automation.AutomationElement]::NameProperty) '我的收藏'|
     Where-Object {$_.Current.ControlType -eq [System.Windows.Automation.ControlType]::Button})
   if($tabs.Count -ne 1){throw 'qq_uia_favorite_tab_not_unique'}
   $toggle=$tabs[0].GetCurrentPattern([System.Windows.Automation.TogglePattern]::Pattern)
   if($toggle.Current.ToggleState -ne [System.Windows.Automation.ToggleState]::Off){throw 'qq_uia_tab_state_unconfirmed'}
   Check-Window $request $true
   $toggle.Toggle(); $selected=$true
   $deadline=[DateTime]::UtcNow.AddSeconds(2)
   do {$panel=Panel $root; if($null -ne (Favorite-Grid $panel)){break}; Start-Sleep -Milliseconds 50} while([DateTime]::UtcNow -lt $deadline)
  }
 }
 if($null -eq $panel){throw 'qq_uia_panel_not_open'}
 $grid=Favorite-Grid $panel
 if($null -eq $grid){throw 'qq_uia_personal_favorites_not_open'}
 $gridRect=Bounds $grid
 $condition=[System.Windows.Automation.PropertyCondition]::new([System.Windows.Automation.AutomationElement]::ClassNameProperty,'collection-sticker')
 $nodes=$grid.FindAll([System.Windows.Automation.TreeScope]::Descendants,$condition)
 $cells=@(); $visible=0
 foreach($node in $nodes) {
  $rect=Bounds $node
  $full=(-not $node.Current.IsOffscreen -and $rect[0] -ge $gridRect[0] -and $rect[1] -ge $gridRect[1] -and
    $rect[2] -le $gridRect[2] -and $rect[3] -le $gridRect[3] -and $rect[2] -gt $rect[0] -and $rect[3] -gt $rect[1])
  if($full){$visible++}
  $cells+=@{rect=$rect; fully_visible=$full; runtime_id=@($node.GetRuntimeId());
            automation_id_present=(-not [string]::IsNullOrEmpty($node.Current.AutomationId))}
 }
 Check-Window $request
 @{ok=$true; panel_rect=(Bounds $panel); grid_rect=$gridRect; loaded_cells=$cells.Count; fully_visible_cells=$visible;
   cells=$cells; original_mapping_proven=$false; enumeration_complete=$false;
   opened_panel=$opened; selected_favorites=$selected; messages_or_favorite_mutations=0}
}
if(-not $Server){throw 'Use bounded project UIAWorker with -Server.'}
[Console]::Out.WriteLine('{"worker_ready":true}')
[Console]::Out.Flush()
while($null -ne ($line=[Console]::In.ReadLine())) {
 try {
  $watch=[Diagnostics.Stopwatch]::StartNew()
  $request=ConvertFrom-Json $line
  $result=Probe $request
  $result.elapsed_seconds=[Math]::Round($watch.Elapsed.TotalSeconds,4)
  $result|ConvertTo-Json -Compress -Depth 7
 } catch { @{ok=$false;reason=$_.Exception.Message}|ConvertTo-Json -Compress }
 [Console]::Out.Flush()
}
