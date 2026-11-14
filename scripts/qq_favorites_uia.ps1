# QQ personal-favorite controls only. No cell Invoke, file picker, chat or send.
param([switch]$Server)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'client_compat.ps1')
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class QQControlGuard {
 [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
 [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h,out uint p);
 [DllImport("user32.dll")] public static extern uint GetDpiForWindow(IntPtr h);
 [DllImport("user32.dll")] public static extern bool SetProcessDpiAwarenessContext(IntPtr context);
 [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
 [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr h);
 [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h,out Rect r);
 [DllImport("user32.dll")] public static extern short GetAsyncKeyState(int k);
 public struct Rect { public int L,T,R,B; }
}
"@
[void][QQControlGuard]::SetProcessDpiAwarenessContext([IntPtr](-4))
function Check($r,[bool]$inputAction=$false) {
 $h=[IntPtr][long]$r.window; $p=[uint32]0
 [void][QQControlGuard]::GetWindowThreadProcessId($h,[ref]$p)
 if($p -ne [int]$r.pid){throw 'window_identity_changed'}
 $exe=(Get-Process -Id $p).Path
 if($exe -ne [string]$r.exe -or [IO.Path]::GetFileName($exe) -ne 'QQ.exe'){throw 'process_identity_changed'}
 Confirm-BridgeVersion 'qq' $exe
 $dpi=[QQControlGuard]::GetDpiForWindow($h)
 if($dpi -notin @(96,120,144)){throw 'client_display_scale_unsupported'}
 if($r.dpi -and $dpi -ne $r.dpi){throw 'client_display_scale_changed'}
 if($r.cancel -and [IO.File]::Exists([string]$r.cancel)){throw 'cancel_requested'}
 if(([QQControlGuard]::GetAsyncKeyState(27) -band 0x8000) -ne 0){throw 'cancelled_escape'}
 if($r.action -ne 'describe') {
  if(-not [QQControlGuard]::IsWindowVisible($h) -or [QQControlGuard]::IsIconic($h)){throw 'window_not_visible'}
  $box=New-Object QQControlGuard+Rect
  [void][QQControlGuard]::GetWindowRect($h,[ref]$box)
  if(($r.rect -join ',') -ne (@($box.L,$box.T,$box.R,$box.B) -join ',')){throw 'window_moved_or_resized'}
 }
 if($inputAction -or $r.foreground) {
  if([QQControlGuard]::GetForegroundWindow() -ne $h){throw 'foreground_changed'}
 }
 if($inputAction) {
  foreach($k in @(1,2,16,17,18,91,92)) {
   if(([QQControlGuard]::GetAsyncKeyState($k) -band 0x8000) -ne 0){throw 'user_input_in_progress'}
  }
 }
}
function Find($root,$property,$value,[bool]$visible=$true) {
 $cond=[System.Windows.Automation.PropertyCondition]::new($property,$value)
 @($root.FindAll([System.Windows.Automation.TreeScope]::Descendants,$cond)|Where-Object {(-not $visible) -or (-not $_.Current.IsOffscreen)})
}
function Unique($nodes,$code) {
 if($nodes.Count -gt 1){throw $code}
 if($nodes.Count -eq 1){return $nodes[0]}
 return $null
}
function Rect($node) {
 $b=$node.Current.BoundingRectangle; @($b.Left,$b.Top,$b.Right,$b.Bottom)
}
function Full($node,$box) {
 $b=Rect $node
 (-not $node.Current.IsOffscreen -and $b[0] -ge $box[0] -and $b[1] -ge $box[1] -and
  $b[2] -le $box[2] -and $b[3] -le $box[3] -and $b[2] -gt $b[0] -and $b[3] -gt $b[1])
}
function FavoriteCells($grid) {
 $property=[System.Windows.Automation.AutomationElement]::ClassNameProperty
 $a=[System.Windows.Automation.PropertyCondition]::new($property,'collection-sticker')
 $b=[System.Windows.Automation.PropertyCondition]::new($property,'sticker-list-item')
 $condition=[System.Windows.Automation.OrCondition]::new($a,$b)
 @($grid.FindAll([System.Windows.Automation.TreeScope]::Descendants,$condition))
}
function CellSnapshots($grid,$box) {
 # Fetch all cell properties together, freshly for THIS request only. This is
 # not a retained UI cache: every request still reacquires and guards the root.
 # https://learn.microsoft.com/dotnet/framework/ui-automation/caching-in-ui-automation-clients
 $cache=[System.Windows.Automation.CacheRequest]::new()
 $cache.TreeScope=[System.Windows.Automation.TreeScope]::Element
 $cache.Add([System.Windows.Automation.AutomationElement]::BoundingRectangleProperty)
 $cache.Add([System.Windows.Automation.AutomationElement]::IsOffscreenProperty)
 $cache.Add([System.Windows.Automation.AutomationElement]::ClassNameProperty)
 # RuntimeIdProperty is included by CacheRequest by default.
 $active=$cache.Activate()
 try {
  foreach($cell in @(FavoriteCells $grid)) {
   $b=$cell.Cached.BoundingRectangle
   $full=(-not $cell.Cached.IsOffscreen -and $b.Left -ge $box[0] -and $b.Top -ge $box[1] -and
          $b.Right -le $box[2] -and $b.Bottom -le $box[3] -and $b.Right -gt $b.Left -and $b.Bottom -gt $b.Top)
   @{rect=@($b.Left,$b.Top,$b.Right,$b.Bottom);class_name=$cell.Cached.ClassName;fully_visible=$full;
     runtime_id=@($cell.GetCachedPropertyValue([System.Windows.Automation.AutomationElement]::RuntimeIdProperty))}
  }
 } finally {$active.Dispose()}
}
function Elements($r) {
 # Always reacquire the root; no reference survives a request or layout change.
 $root=[System.Windows.Automation.AutomationElement]::FromHandle([IntPtr][long]$r.window)
 $visible=$r.action -ne 'describe'
 $bars=@(Find $root ([System.Windows.Automation.AutomationElement]::ControlTypeProperty) ([System.Windows.Automation.ControlType]::ToolBar) $visible)
 # Never read Name/Text/Value of chat rows, contacts or the composer.
 $buttons=@(foreach($bar in $bars){Find $bar ([System.Windows.Automation.AutomationElement]::ControlTypeProperty) ([System.Windows.Automation.ControlType]::Button) $visible|
  Where-Object {$_.Current.Name -eq '表情'}})
 $button=Unique $buttons 'qq_uia_emoji_button_not_unique'
 $panel=Unique @(Find $root ([System.Windows.Automation.AutomationElement]::ClassNameProperty) 'sticker-panel') 'qq_uia_panel_not_unique'
 $grid=$null; $tab=$null
 if($null -ne $panel) {
  $grid=Unique @(Find $panel ([System.Windows.Automation.AutomationElement]::ClassNameProperty) 'sticker-container'|
   Where-Object {$_.Current.Name -eq '收藏表情列表'}) 'qq_uia_grid_not_unique'
  $tab=Unique @(Find $panel ([System.Windows.Automation.AutomationElement]::ControlTypeProperty) ([System.Windows.Automation.ControlType]::Button)|
   Where-Object {$_.Current.Name -eq '我的收藏'}) 'qq_uia_favorite_tab_not_unique'
 }
 @{button=$button;panel=$panel;grid=$grid;tab=$tab}
}
function MsaaElements($r) {
 if(-not ('QQAccessibleTree' -as [type])) {
  Add-Type -AssemblyName Accessibility
  Add-Type -TypeDefinition ([IO.File]::ReadAllText((Join-Path $PSScriptRoot 'qq_accessible.cs'))) -ReferencedAssemblies @('System.dll','Accessibility')
 }
 $tree=[QQAccessibleTree]::new([long]$r.window)
 try {
  $visible=$r.action -ne 'describe'
  $button=Unique @($tree.Buttons('表情',$null,$true,$visible)) 'qq_uia_emoji_button_not_unique'
  $panel=Unique @($tree.Classes('sticker-panel',$null,$true)) 'qq_uia_panel_not_unique'
  $grid=$null;$tab=$null
  if($null -ne $panel) {
   $grid=Unique @($tree.Classes('sticker-container',$panel,$true)|Where-Object {$_.Name -eq '收藏表情列表'}) 'qq_uia_grid_not_unique'
   $tab=Unique @($tree.FavoriteTabs($panel)) 'qq_uia_favorite_tab_not_unique'
  }
  return @{tree=$tree;button=$button;panel=$panel;grid=$grid;tab=$tab}
 } catch {$tree.Dispose();throw}
}
function MsaaFull($node,$box) {
 $b=$node.Rect
 ($node.Visible -and $b[0] -ge $box[0] -and $b[1] -ge $box[1] -and $b[2] -le $box[2] -and $b[3] -le $box[3] -and $b[2] -gt $b[0] -and $b[3] -gt $b[1])
}
function MsaaRun($r) {
 Check $r
 $nodes=MsaaElements $r;$performed=$false;$nativeClick=$null
 try {
  if($r.action -in @('open-panel','close-panel')) {
   $needed=($r.action -eq 'open-panel' -and $null -eq $nodes.panel) -or ($r.action -eq 'close-panel' -and $null -ne $nodes.panel)
   if($needed) {
    if($null -eq $nodes.button){throw 'qq_uia_controls_not_ready'}
    Check $r $true;$nodes.button.InvokeToolbar();$performed=$true
   }
  } elseif($r.action -eq 'select-favorites' -and $null -eq $nodes.grid) {
   if($null -eq $nodes.tab){throw 'qq_uia_favorite_tab_not_ready'}
   Check $r $true
   if($nodes.tab.SelectFavorites()){$performed=$true}else{$nativeClick=$nodes.tab.Rect}
  } elseif($r.action -eq 'reveal-cell') {
   if($null -eq $nodes.grid){throw 'qq_uia_personal_favorites_not_open'}
   if(-not $r.runtime_id -or $r.runtime_id.Count -ne 3 -or $r.runtime_id[0] -ne -161 -or $r.runtime_id[1] -ne [long]$r.window){throw 'qq_uia_cell_identity_required'}
   $cell=Unique @($nodes.tree.FavoriteCells($nodes.grid)|Where-Object {$_.UniqueId -eq $r.runtime_id[2]}) 'qq_uia_cell_changed'
   if($null -eq $cell){throw 'qq_uia_cell_changed'}
   Check $r $true;$cell.RevealCell();$performed=$true
  }
  if($performed){$nodes.tree.Dispose();$nodes=MsaaElements $r}
  $out=@{ok=$true;backend='msaa';toolbar_ready=($null -ne $nodes.button);panel_open=($null -ne $nodes.panel);
   favorites_open=($null -ne $nodes.grid);favorite_tab_ready=($null -ne $nodes.tab);performed=$performed;
   original_mapping_proven=$false;enumeration_complete=$false;messages_or_favorite_mutations=0}
  if($null -ne $nodes.button){$out.toolbar_rect=$nodes.button.Rect}
  if($null -ne $nodes.panel){$out.panel_rect=$nodes.panel.Rect}
  if($null -ne $nodes.tab){$out.favorite_tab_rect=$nodes.tab.Rect}
  if($null -ne $nativeClick){$out.native_click_rect=$nativeClick}
  if($null -ne $nodes.grid) {
   $box=$nodes.grid.Rect;$out.grid_rect=$box
   $cells=@(if($r.action -ne 'panel') {$nodes.tree.Cells($nodes.grid,[long]$r.window)})
   $import=Unique @($nodes.tree.Classes('sticker-list__import',$nodes.grid,$false)) 'qq_uia_import_tile_not_unique'
   $out.import_ready=($null -ne $import -and (MsaaFull $import $box));$out.at_top=$out.import_ready
   if($null -ne $import){$out.import_rect=$import.Rect}
   $out.grid_scroll_pattern=$false;$out.cells=$cells;$out.loaded_cells=$cells.Count
   $out.fully_visible_cells=@($cells|Where-Object {$_.fully_visible}).Count
  }
  Check $r ($r.action -in @('open-panel','select-favorites','close-panel','reveal-cell'))
  return $out
 } finally {$nodes.tree.Dispose()}
}
$script:msaaWindows=@{}
function Run($r) {
 if($r.action -notin @('describe','snapshot','panel','open-panel','select-favorites','close-panel','reveal-cell')){throw 'invalid_readonly_action'}
 Check $r
 # One backend per HWND/PID within this bounded worker; no COM refs are cached.
 # UIA stays the fast default. Only a missing semantic tree triggers fallback,
 # before ANY action. Errors after an attempted action must never be replayed.
 $key=([string]$r.pid)+':'+([string]$r.window)
 if($script:msaaWindows.ContainsKey($key)){
  $ms=MsaaRun $r
  # A usable toolbar does not guarantee that the opened favorites tab is
  # exposed. Check the missing capability through UIA before pixel fallback.
  if($r.action -in @('describe','snapshot','panel') -and $ms.panel_open -and -not $ms.favorite_tab_ready -and -not $ms.favorites_open){
   $other=Elements $r
   if($null -ne $other.tab -or $null -ne $other.grid){$script:msaaWindows.Remove($key);return (Run $r)}
   $ms.visual_fallback_eligible=$true;$ms.visual_fallback_scope='favorite-tab'
  }
  return $ms
 }
 $uiaReadError=$null
 try {$nodes=Elements $r} catch {
  if($_.Exception.GetBaseException().Message -match '^[a-z][a-z0-9_]+$'){throw}
  $uiaReadError=$_;$nodes=@{button=$null;panel=$null;grid=$null;tab=$null}
 }
 $performed=$false
 $bothProvidersEmpty=$false
 $missingTab=($null -ne $nodes.panel -and $null -eq $nodes.tab -and $null -eq $nodes.grid)
 if(($null -eq $nodes.button -and $null -eq $nodes.panel) -or ($missingTab -and $r.action -in @('describe','snapshot','panel'))) {
  $probe=$null
  try {$probe=MsaaRun ([pscustomobject]@{window=$r.window;pid=$r.pid;exe=$r.exe;dpi=$r.dpi;rect=$r.rect;cancel=$r.cancel;action='describe';foreground=$false})}
  catch {
   # An unrelated native/auxiliary window can have no MSAA provider. Do not
   # hide semantic ambiguity, cancellation or an identity change, however.
   $reason=$_.Exception.GetBaseException().Message
   if($r.action -ne 'describe' -or $reason -match '^[a-z][a-z0-9_]+$'){throw}
  }
  if($null -ne $probe -and $probe.toolbar_ready -and (-not $missingTab -or $probe.favorite_tab_ready -or $probe.favorites_open)) {
   $script:msaaWindows[$key]=$true
   if($r.action -eq 'describe'){return $probe}
   return (MsaaRun $r)
  }
  $bothProvidersEmpty=($null -ne $probe -and -not $probe.toolbar_ready -and -not $probe.panel_open)
  if($missingTab -and $null -ne $probe -and -not $probe.favorite_tab_ready -and -not $probe.favorites_open){$bothProvidersEmpty=$true}
 }
 if($null -ne $uiaReadError){throw $uiaReadError}
 if($r.action -in @('open-panel','close-panel')) {
  $needed=($r.action -eq 'open-panel' -and $null -eq $nodes.panel) -or ($r.action -eq 'close-panel' -and $null -ne $nodes.panel)
  if($needed) {
   if($null -eq $nodes.button){throw 'qq_uia_controls_not_ready'}
   $pattern=$nodes.button.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)
   Check $r $true; $pattern.Invoke(); $performed=$true
  }
 } elseif($r.action -eq 'reveal-cell') {
  if($null -eq $nodes.grid){throw 'qq_uia_personal_favorites_not_open'}
  if(-not $r.runtime_id -or $r.runtime_id.Count -gt 16){throw 'qq_uia_cell_identity_required'}
  $cellsFound=@(FavoriteCells $nodes.grid|
   Where-Object {($_.GetRuntimeId() -join ',') -eq ($r.runtime_id -join ',')})
  if($cellsFound.Count -ne 1){throw 'qq_uia_cell_changed'}
  # ScrollIntoView only reveals a freshly reidentified cell. NEVER Invoke it.
  $pattern=$cellsFound[0].GetCurrentPattern([System.Windows.Automation.ScrollItemPattern]::Pattern)
  Check $r $true; $pattern.ScrollIntoView(); $performed=$true
 } elseif($r.action -eq 'select-favorites' -and $null -eq $nodes.grid) {
  if($null -eq $nodes.tab){throw 'qq_uia_favorite_tab_not_ready'}
  $pattern=$nodes.tab.GetCurrentPattern([System.Windows.Automation.TogglePattern]::Pattern)
  if($pattern.Current.ToggleState -eq [System.Windows.Automation.ToggleState]::Off) {
   Check $r $true; $pattern.Toggle(); $performed=$true
  } elseif($pattern.Current.ToggleState -ne [System.Windows.Automation.ToggleState]::On){throw 'qq_uia_tab_state_unconfirmed'}
 }
 if($performed){$nodes=Elements $r}
 $out=@{ok=$true;backend='uia';toolbar_ready=($null -ne $nodes.button);panel_open=($null -ne $nodes.panel);
  favorites_open=($null -ne $nodes.grid);favorite_tab_ready=($null -ne $nodes.tab);performed=$performed;
  original_mapping_proven=$false;enumeration_complete=$false;messages_or_favorite_mutations=0}
 $out.visual_fallback_eligible=$bothProvidersEmpty
 if($bothProvidersEmpty -and $missingTab){$out.visual_fallback_scope='favorite-tab'}
 if($null -ne $nodes.button){$out.toolbar_rect=Rect $nodes.button}
 if($null -ne $nodes.panel){$out.panel_rect=Rect $nodes.panel}
 if($null -ne $nodes.tab){$out.favorite_tab_rect=Rect $nodes.tab}
 if($null -ne $nodes.grid) {
  $box=Rect $nodes.grid; $out.grid_rect=$box; $cells=@()
  if($r.action -ne 'panel'){$cells=@(CellSnapshots $nodes.grid $box)}
  $imports=@(Find $nodes.grid ([System.Windows.Automation.AutomationElement]::ClassNameProperty) 'sticker-list__import' $false)
  $import=Unique $imports 'qq_uia_import_tile_not_unique'
  $out.import_ready=($null -ne $import -and (Full $import $box))
  if($null -ne $import){$out.import_rect=Rect $import}
  $out.at_top=($null -ne $import -and (Full $import $box))
  $out.grid_scroll_pattern=$nodes.grid.GetCurrentPropertyValue([System.Windows.Automation.AutomationElement]::IsScrollPatternAvailableProperty)
  $out.cells=$cells; $out.loaded_cells=$cells.Count; $out.fully_visible_cells=@($cells|Where-Object {$_.fully_visible}).Count
 }
 Check $r ($r.action -in @('open-panel','select-favorites','close-panel','reveal-cell'))
 return $out
}
if(-not $Server){throw 'Use bounded project UIAWorker with -Server.'}
[Console]::Out.WriteLine('{"worker_ready":true}')
[Console]::Out.Flush()
while($null -ne ($line=[Console]::In.ReadLine())) {
 try {$watch=[Diagnostics.Stopwatch]::StartNew();$r=ConvertFrom-Json $line;$out=Run $r
  $out.elapsed_seconds=[Math]::Round($watch.Elapsed.TotalSeconds,4);$out|ConvertTo-Json -Depth 7 -Compress
 } catch {
  $code=$_.Exception.GetBaseException().Message
  if($code -notmatch '^[a-z][a-z0-9_]+$'){$code='qq_uia_provider_error'}
  @{ok=$false;reason=$code}|ConvertTo-Json -Compress
 }
 [Console]::Out.Flush()
}
