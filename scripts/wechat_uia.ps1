param(
 [long]$WindowHandle,
 [int]$ClientProcessId,
 [string]$Executable,
 [ValidateSet('capabilities','prepare-accessibility','snapshot','own-session-target','own-search-start','own-search-target','message-rows','latest-messages','toggle-panel','open-file','send','send-batch','panel','panel-tab','menu','menu-observe','import-status','clear-staged')][string]$Action='snapshot',
 [long]$ParentHandle=0,
 [switch]$Server
)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'client_compat.ps1')
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class BridgeGuard {
 [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
 [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h,out uint p);
 [DllImport("user32.dll")] public static extern short GetAsyncKeyState(int key);
 [DllImport("user32.dll")] public static extern bool SetProcessDpiAwarenessContext(IntPtr context);
 [DllImport("user32.dll")] public static extern uint GetDpiForWindow(IntPtr h);
 [DllImport("oleacc.dll")] static extern int AccessibleObjectFromWindow(IntPtr h,uint id,ref Guid iid,out IntPtr result);
 public static int RequestClientAccessibility(IntPtr h) {
  Guid iid=new Guid("618736e0-3c3d-11cf-810c-00aa00389b71");
  IntPtr result=IntPtr.Zero;
  try { return AccessibleObjectFromWindow(h,0xfffffffc,ref iid,out result); }
  finally { if(result!=IntPtr.Zero) Marshal.Release(result); }
 }
}
"@
[void][BridgeGuard]::SetProcessDpiAwarenessContext([IntPtr](-4))
function Check-Window {
 $ownerId=[uint32]0
 [void][BridgeGuard]::GetWindowThreadProcessId([IntPtr]$WindowHandle,[ref]$ownerId)
 if($ownerId -ne $ClientProcessId -or (Get-Process -Id $ClientProcessId).Path -ne $Executable){throw 'process_identity_changed'}
 Confirm-BridgeVersion 'wechat' $Executable
 $front=[BridgeGuard]::GetForegroundWindow().ToInt64()
 if($Action -ne 'capabilities' -and $front -ne $WindowHandle -and -not ($Action -in @('menu','menu-observe','own-search-target','import-status') -and $ParentHandle -gt 0 -and $front -eq $ParentHandle)){throw 'foreground_changed'}
 if(([BridgeGuard]::GetAsyncKeyState(27) -band 0x8000) -ne 0){throw 'cancelled_escape'}
}
function Control-Error($role,$count){
 $script:ControlFailure=@{control=$role;matches=$count}
 if($count -eq 0){throw 'wechat_control_missing'}
 throw 'wechat_control_ambiguous'
}
function Find-One($root,$property,$value,$role='other'){
 $cond=[System.Windows.Automation.PropertyCondition]::new($property,$value)
 $found=$root.FindAll([System.Windows.Automation.TreeScope]::Descendants,$cond)
 $visible=@($found|Where-Object {-not $_.Current.IsOffscreen})
 if($visible.Count -ne 1){Control-Error $role $visible.Count}
 return $visible[0]
}
function Rect($element){$b=$element.Current.BoundingRectangle;return @($b.Left,$b.Top,$b.Right,$b.Bottom)}
function Own-Session-Entry($root){
 $sessions=Find-One $root ([System.Windows.Automation.AutomationElement]::AutomationIdProperty) 'session_list' 'sessions'
 $condition=[System.Windows.Automation.PropertyCondition]::new([System.Windows.Automation.AutomationElement]::AutomationIdProperty,'session_item_文件传输助手')
 $entries=$sessions.FindAll([System.Windows.Automation.TreeScope]::Descendants,$condition)
 if($entries.Count -ne 1 -or $entries[0].Current.ControlType -ne [System.Windows.Automation.ControlType]::ListItem){throw 'own_transfer_entry_not_visible'}
 return $entries[0]
}
function Chat-Header($root){
 # Both roles were observed in Qt 4.1. Prefer the leaf; only fall back when
 # absent, never choose one of multiple titles or search message text.
 $prefix='content_view.top_content_view.title_h_view.left_v_view.left_content_v_view.left_ui_.big_title_line_h_view'
 foreach($id in @(($prefix+'.current_chat_name_label'),$prefix)){
  $condition=[System.Windows.Automation.PropertyCondition]::new([System.Windows.Automation.AutomationElement]::AutomationIdProperty,$id)
  $nodes=@($root.FindAll([System.Windows.Automation.TreeScope]::Descendants,$condition)|Where-Object {-not $_.Current.IsOffscreen -and $_.Current.ControlType -eq [System.Windows.Automation.ControlType]::Text})
  if($nodes.Count -gt 1){Control-Error 'header' $nodes.Count}
  if($nodes.Count -eq 1){$script:HeaderMode='exact_id';return $nodes[0]}
 }
 return Header-ByStructure $root
}
function Header-Ancestor($ancestor,$node){
 $walker=[System.Windows.Automation.TreeWalker]::ControlViewWalker
 for($i=0;$i -lt 20;$i++){
  $node=$walker.GetParent($node)
  if($null -eq $node){return $false}
  if([System.Windows.Automation.Automation]::Compare($ancestor,$node)){return $true}
 }
 return $false
}
function Header-ByStructure($root){
 # The title's complete AutomationId includes Qt's internal layout hierarchy.
 # Anchor a fallback to the real chat column, outside both lists/composer.
 $messages=Find-One $root ([System.Windows.Automation.AutomationElement]::AutomationIdProperty) 'chat_message_list' 'messages'
 $composer=Find-One $root ([System.Windows.Automation.AutomationElement]::AutomationIdProperty) 'chat_input_field' 'composer'
 $sessions=Find-One $root ([System.Windows.Automation.AutomationElement]::AutomationIdProperty) 'session_list' 'sessions'
 $m=$messages.Current.BoundingRectangle;$c=$composer.Current.BoundingRectangle
 $s=$sessions.Current.BoundingRectangle;$r=$root.Current.BoundingRectangle
 if($m.Width -le 0 -or $m.Height -le 0 -or $c.Width -le 0 -or $c.Height -le 0 -or $s.Width -le 0 -or $s.Height -le 0 -or
    $m.Left -lt $s.Right-4 -or $m.Top -le $r.Top -or $m.Bottom -gt $c.Top+4 -or
    $m.Left -lt $r.Left -or $m.Right -gt $r.Right -or $c.Bottom -gt $r.Bottom){throw 'wechat_header_layout_unsupported'}
 $condition=[System.Windows.Automation.PropertyCondition]::new([System.Windows.Automation.AutomationElement]::ControlTypeProperty,[System.Windows.Automation.ControlType]::Text)
 $scale=[BridgeGuard]::GetDpiForWindow([IntPtr]$WindowHandle)/96.0
 $bandTop=[Math]::Max($r.Top,$m.Top-96*$scale)
 $texts=@($root.FindAll([System.Windows.Automation.TreeScope]::Descendants,$condition)|Where-Object {
  $b=$_.Current.BoundingRectangle
  -not $_.Current.IsOffscreen -and $b.Width -gt 0 -and $b.Height -gt 0 -and
  $b.Left -ge $m.Left -and $b.Right -le $m.Right -and $b.Top -ge $bandTop -and $b.Bottom -le $m.Top
 })
 $script:HeaderProbe=@{header_region_texts=$texts.Count}
 # Stable leaf role, regardless of the number/names of its layout parents.
 foreach($role in @('current_chat_name_label','big_title_line_h_view')){
  $matches=@($texts|Where-Object {($_.Current.AutomationId -split '\.')[-1] -eq $role})
  $script:HeaderProbe.header_semantic_matches=$matches.Count
  if($matches.Count -gt 1){Control-Error 'header' $matches.Count}
  if($matches.Count -eq 1){$script:HeaderMode='chat_header_role';return $matches[0]}
 }
 # Last fallback is still native text in the HEADER ONLY. Never match a name
 # in a message, session list, search result or composer. Own-Chat additionally
 # requires the exact helper session to be selected for this fallback.
 $matches=@($texts|Where-Object {$_.Current.Name -eq '文件传输助手'})
 $script:HeaderProbe.header_helper_matches=$matches.Count
 $leaves=@($matches|Where-Object {
  $candidate=$_;$hasChild=$false
  foreach($other in $matches){if(Header-Ancestor $candidate $other){$hasChild=$true;break}}
  -not $hasChild
 })
 if($leaves.Count -ne 1){Control-Error 'header' $leaves.Count}
 $script:HeaderMode='chat_header_region'
 return $leaves[0]
}
function Own-Chat($root){
 $header=Chat-Header $root
 $inputBox=Find-One $root ([System.Windows.Automation.AutomationElement]::AutomationIdProperty) 'chat_input_field' 'composer'
 if($header.Current.Name -ne '文件传输助手'){throw 'own_transfer_session_not_confirmed'}
 # Qt can decorate the input's accessible name. Require a second independent
 # native witness when its name is not the historical exact helper name.
 if($inputBox.Current.Name -ne '文件传输助手' -or $script:HeaderMode -eq 'chat_header_region'){
  try{$entry=Own-Session-Entry $root}
  catch {if($_.Exception.Message -eq 'own_transfer_entry_not_visible'){throw 'own_transfer_session_not_confirmed'};throw}
  $selection=$null
  if(-not $entry.TryGetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern,[ref]$selection) -or -not $selection.Current.IsSelected){throw 'own_transfer_session_not_confirmed'}
 }
 return @($header,$inputBox)
}
function Search-Box($root){
 $search=Named-Control $root '搜索' ([System.Windows.Automation.ControlType]::Edit)
 $sessions=Find-One $root ([System.Windows.Automation.AutomationElement]::AutomationIdProperty) 'session_list' 'sessions'
 $s=$search.Current.BoundingRectangle;$b=$sessions.Current.BoundingRectangle
 if($s.Width -le 0 -or $s.Height -le 0 -or $s.Left -lt $b.Left -or $s.Right -gt $b.Right -or $s.Bottom -gt $b.Top){throw 'own_transfer_search_layout_unsupported'}
 return $search
}
function Start-Own-Search($root){
 $search=Search-Box $root
 $value=$search.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern)
 if($value.Current.IsReadOnly){throw 'own_transfer_search_not_empty'}
 # A paused startup may leave this exact native helper query behind. Reuse
 # it without editing it; arbitrary user searches remain untouched.
 if($value.Current.Value -eq '文件传输助手'){Check-Window;return}
 if(-not [string]::IsNullOrEmpty($value.Current.Value)){throw 'own_transfer_search_not_empty'}
 Check-Window
 $value.SetValue('文件传输助手')
}
function Search-Result($list){
 $cond=[System.Windows.Automation.PropertyCondition]::new([System.Windows.Automation.AutomationElement]::AutomationIdProperty,'search_item_function_文件传输助手')
 $items=@($list.FindAll([System.Windows.Automation.TreeScope]::Descendants,$cond)|Where-Object {-not $_.Current.IsOffscreen})
 if($items.Count -eq 0){return $null}
 if($items.Count -ne 1){Control-Error 'helper_function' $items.Count}
 $item=$items[0]
 if($item.Current.Name -ne '文件传输助手' -or $item.Current.ControlType -ne [System.Windows.Automation.ControlType]::ListItem -or -not $item.Current.IsEnabled){throw 'own_transfer_search_result_unsupported'}
 return $item
}
function Named-Control($root,$name,$type){
 $condition=[System.Windows.Automation.AndCondition]::new(
  [System.Windows.Automation.PropertyCondition]::new([System.Windows.Automation.AutomationElement]::ControlTypeProperty,$type),
  [System.Windows.Automation.PropertyCondition]::new([System.Windows.Automation.AutomationElement]::NameProperty,$name))
 $found=@($root.FindAll([System.Windows.Automation.TreeScope]::Descendants,$condition)|Where-Object {-not $_.Current.IsOffscreen})
 if($found.Count -ne 1){throw 'uia_button_not_unique'}
 return $found[0]
}
function Button($root,$name){return Named-Control $root $name ([System.Windows.Automation.ControlType]::Button)}
function Invoke-Request {
try {
 $script:ControlFailure=$null
 $script:HeaderProbe=$null;$script:HeaderMode=$null
 Check-Window
 $root=[System.Windows.Automation.AutomationElement]::FromHandle([IntPtr]$WindowHandle)
 if($Action -eq 'prepare-accessibility'){
  # Startup only: request the standard client accessibility object once when
  # Qt exposes only a shell. Never invoke a control or change client settings.
  # This runs in the cancellable, time-bounded helper, not the desktop thread.
  # Match the standalone probe: count descendants, excluding the root window.
  # Two shell descendants must not become three and skip the recovery request.
  $nodes=$root.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition).Count
  $requested=$false;$hr=$null
  if($nodes -le 2){
   Check-Window
   $hr=[BridgeGuard]::RequestClientAccessibility([IntPtr]$WindowHandle)
   $requested=$true
  }
  Check-Window
  @{ok=$true;requested=$requested;nodes_before=$nodes;hresult=$hr;read_only=$true}|ConvertTo-Json -Compress
  return
 }
 if($Action -eq 'capabilities'){
  # Read only structural booleans. Never fetch composer values, enumerate
  # messages, switch sessions, open a menu, scroll or invoke a control.
  $ready=$false
  try {
   $null=Own-Chat $root
   $null=Button $root '发送'
   $null=Button $root '发送文件'
   $null=Button $root '发送表情(Alt+E)'
   $ready=$true
  } catch { }
  @{ok=$true;send_ready=$ready;read_only=$true}|ConvertTo-Json -Compress
  return
 }
 if($Action -in @('panel','panel-tab','menu','menu-observe','import-status')){
  $parentId=[uint32]0
  [void][BridgeGuard]::GetWindowThreadProcessId([IntPtr]$ParentHandle,[ref]$parentId)
  if($parentId -ne $ClientProcessId){throw 'popup_parent_mismatch'}
  if($Action -eq 'import-status'){
   # The add command has already verified File Transfer Assistant. This is a
   # read-only toast observation: do not enumerate the growing chat tree on
   # every poll. Every subsequent input command rechecks the chat identity.
   if($root.Current.ClassName -ne 'mmui::XToast'){
    # This application's own add rejection is a separate modal window,
    # not XToast and not a change to another application. Read only exact
    # known failure text plus its acknowledgement; never dismiss other dialogs.
    $texts=@($root.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.PropertyCondition]::new([System.Windows.Automation.AutomationElement]::ControlTypeProperty,[System.Windows.Automation.ControlType]::Text))|Where-Object {-not $_.Current.IsOffscreen}|ForEach-Object {$_.Current.Name})
    $failed=@($texts|Where-Object {$_ -match '^表情添加失败[，,] ?请稍后再试[。.]?$'}).Count -eq 1
    $ack=@($root.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.PropertyCondition]::new([System.Windows.Automation.AutomationElement]::NameProperty,'我知道了'))|Where-Object {-not $_.Current.IsOffscreen -and $_.Current.ControlType -eq [System.Windows.Automation.ControlType]::Button})
    Check-Window
    $result=@{ok=$true;state=$(if($failed -and $ack.Count -eq 1){'failed'}else{'unknown'});read_only=$true}
    if($failed -and $ack.Count -eq 1 -and $ack[0].Current.IsEnabled){$result.ack_target=Rect $ack[0]}
    $result|ConvertTo-Json -Compress;return
   }
   $cond=[System.Windows.Automation.PropertyCondition]::new([System.Windows.Automation.AutomationElement]::AutomationIdProperty,'xtoast.xtoast_container.xtoast_label')
   $labels=@($root.FindAll([System.Windows.Automation.TreeScope]::Descendants,$cond)|Where-Object {-not $_.Current.IsOffscreen -and $_.Current.ControlType -eq [System.Windows.Automation.ControlType]::Text}|ForEach-Object {$_.Current.Name})
   $state='unknown'
   if(@($labels|Where-Object {$_ -in @('正在添加','正在添加…','正在添加...')}).Count -eq 1){$state='adding'}
   if(@($labels|Where-Object {$_ -eq '已添加'}).Count -eq 1){$state='acknowledged'}
   if(@($labels|Where-Object {$_ -in @('添加失败','表情添加失败','添加失败，请重试')}).Count -gt 0){$state='failed'}
   Check-Window
   @{ok=$true;state=$state;read_only=$true}|ConvertTo-Json -Compress
   return
  }
  # Visual navigation already verified the assistant before this read-only popup probe.
  # Do not walk the unavailable main tree again; normal native menu retains that check.
  if($Action -ne 'menu-observe'){$null=Own-Chat ([System.Windows.Automation.AutomationElement]::FromHandle([IntPtr]$ParentHandle))}
  if($Action -in @('panel','panel-tab')){
   $tab=Named-Control $root '自定义表情' ([System.Windows.Automation.ControlType]::TabItem)
   if($Action -eq 'panel-tab'){
    Check-Window
    @{ok=$true;tab=(Rect $tab)}|ConvertTo-Json -Compress
    return
   }
   $list=Find-One $root ([System.Windows.Automation.AutomationElement]::ControlTypeProperty) ([System.Windows.Automation.ControlType]::List) 'favorites_grid'
   $cells=@()
   $buttons=$list.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.PropertyCondition]::new([System.Windows.Automation.AutomationElement]::ControlTypeProperty,[System.Windows.Automation.ControlType]::Button))
   foreach($button in $buttons){
    if(-not $button.Current.IsOffscreen){$cells+=@{rect=(Rect $button)}}
   }
   @{ok=$true;tab=(Rect $tab);grid=(Rect $list);cells=$cells}|ConvertTo-Json -Compress -Depth 6
  } else {
   $cond=[System.Windows.Automation.PropertyCondition]::new([System.Windows.Automation.AutomationElement]::NameProperty,'添加到表情')
   $items=@($root.FindAll([System.Windows.Automation.TreeScope]::Descendants,$cond)|Where-Object {-not $_.Current.IsOffscreen})
   if($items.Count -gt 1){throw 'uia_control_not_unique'}
   Check-Window
   $out=@{ok=$true;available=($items.Count -eq 1 -and $items[0].Current.IsEnabled)}
   if($items.Count -eq 1){$out.target=Rect $items[0]}
   $out|ConvertTo-Json -Compress
  }
  return
 }
 if($Action -eq 'own-session-target'){
  # Only the exact session-list identity is eligible, never search results or
  # another contact sharing text in a message. No composer value is changed.
  $entry=Own-Session-Entry $root
  if($entry.Current.IsOffscreen){
   $scrollItem=$null
   if(-not $entry.TryGetCurrentPattern([System.Windows.Automation.ScrollItemPattern]::Pattern,[ref]$scrollItem)){throw 'own_transfer_entry_not_visible'}
   Check-Window
   $scrollItem.ScrollIntoView()
   $entry=Own-Session-Entry $root
  }
  if($entry.Current.IsOffscreen -or -not $entry.Current.IsEnabled){throw 'own_transfer_entry_not_visible'}
  Check-Window
  @{ok=$true;target=(Rect $entry);destination='文件传输助手'}|ConvertTo-Json -Compress
  return
 }
 if($Action -eq 'own-search-start'){
  # Set ONLY an empty native search field, not a chat composer or clipboard.
  Start-Own-Search $root
  @{ok=$true;search_started=$true}|ConvertTo-Json -Compress
  return
 }
 if($Action -eq 'own-search-target'){
  $parentId=[uint32]0
  [void][BridgeGuard]::GetWindowThreadProcessId([IntPtr]$ParentHandle,[ref]$parentId)
  if($parentId -ne $ClientProcessId){throw 'popup_parent_mismatch'}
  $main=[System.Windows.Automation.AutomationElement]::FromHandle([IntPtr]$ParentHandle)
  $search=Search-Box $main
  $value=$search.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern)
  if($value.Current.Value -ne '文件传输助手'){throw 'own_transfer_search_changed'}
  $list=Find-One $root ([System.Windows.Automation.AutomationElement]::AutomationIdProperty) 'search_list' 'search_results'
  # This is the built-in function, NOT an exact-name contact or search history.
  $item=Search-Result $list
  if($null -eq $item){@{ok=$true;available=$false}|ConvertTo-Json -Compress;return}
  Check-Window
  @{ok=$true;available=$true;target=(Rect $item);destination='文件传输助手'}|ConvertTo-Json -Compress
  return
 }
 $chat=Own-Chat $root
 if($Action -in @('message-rows','latest-messages')){
  # Expose geometry/runtime identity only, never message text or sender names.
  $list=Find-One $root ([System.Windows.Automation.AutomationElement]::AutomationIdProperty) 'chat_message_list' 'messages'
  $scrollPattern=$null; $scrollInfo=@{supported=$false}
  if($list.TryGetCurrentPattern([System.Windows.Automation.ScrollPattern]::Pattern,[ref]$scrollPattern)){
   if($Action -eq 'latest-messages'){
    Check-Window
    $null=Own-Chat $root
    if($scrollPattern.Current.VerticallyScrollable){$scrollPattern.SetScrollPercent(-1,100)}
   }
   $scrollInfo=@{supported=$true;vertical=$scrollPattern.Current.VerticalScrollPercent}
  }
  $rows=@(); $allIds=@()
  $items=$list.FindAll([System.Windows.Automation.TreeScope]::Children,[System.Windows.Automation.PropertyCondition]::new([System.Windows.Automation.AutomationElement]::ControlTypeProperty,[System.Windows.Automation.ControlType]::ListItem))
  foreach($item in $items){
   $allIds+=,@($item.GetRuntimeId())
   if(-not $item.Current.IsOffscreen){$rows+=@{rect=(Rect $item);identity=@($item.GetRuntimeId())}}
  }
  Check-Window
  $null=Own-Chat $root
  @{ok=$true;list=(Rect $list);rows=$rows;all_row_ids=$allIds;scroll=$scrollInfo}|ConvertTo-Json -Compress -Depth 6
  return
 }
 $value=$chat[1].GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern).Current.Value
 $sendButton=Button $root '发送'
 $out=@{ok=$true;own_session='文件传输助手';header=(Rect $chat[0]);header_mode=$script:HeaderMode;input=(Rect $chat[1]);input_empty=([string]::IsNullOrEmpty($value));send_enabled=$sendButton.Current.IsEnabled;root=(Rect $root)}
 $out.input_length=$value.Length
 $out.input_only_object=($value.Trim() -eq [string][char]0xfffc)
 $mediaOnly=$value -replace '[\s\ufffc]',''
 $out.media_object_count=([regex]::Matches($value,'\ufffc')).Count
 $out.input_only_media_objects=($mediaOnly.Length -eq 0 -and $out.media_object_count -ge 1)
 $out.input_known_label=($value.Trim() -in @('[动画表情]','[表情]','[图片]'))
 if($Action -eq 'clear-staged'){
  if(-not $out.input_only_object){throw 'composer_not_one_media_object'}
  Check-Window
  $null=Own-Chat $root
  $pattern=$chat[1].GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern)
  if($pattern.Current.IsReadOnly){throw 'composer_read_only'}
  $pattern.SetValue('')
  if(-not [string]::IsNullOrEmpty($pattern.Current.Value)){throw 'composer_clear_not_confirmed'}
  @{ok=$true;input_empty=$true}|ConvertTo-Json -Compress
  return
 }
 if($Action -ne 'snapshot'){
  $name=switch($Action){'toggle-panel'{'发送表情(Alt+E)'} 'open-file'{'发送文件'} 'send'{'发送'} 'send-batch'{'发送'}}
  if($Action -eq 'open-file' -and -not $out.input_empty){throw 'composer_not_empty'}
  if($Action -eq 'send' -and -not $out.input_only_object){throw 'composer_not_one_media_object'}
  if($Action -eq 'send-batch' -and -not $out.input_only_media_objects){throw 'composer_not_expected_media_batch'}
  $button=Button $root $name
  if(-not $button.Current.IsEnabled){throw 'uia_button_disabled'}
  Check-Window
  $null=Own-Chat $root
  # Qt exposes InvokePattern here but did not change the observed panel in our
  # probe. Return an identified target for guarded Win32 input, never success.
  $out.target=Rect $button
  $out.action=$Action
 }
 $out|ConvertTo-Json -Compress -Depth 5
} catch {
 @{ok=$false;reason=$_.Exception.Message;control_failure=$script:ControlFailure;header_probe=$script:HeaderProbe}|ConvertTo-Json -Compress
}
}
if($Server){
 [Console]::Out.WriteLine('{"worker_ready":true}')
[Console]::Out.Flush()
while($null -ne ($line=[Console]::In.ReadLine())){
  try {
   $request=ConvertFrom-Json $line
   if($request.action -notin @('capabilities','prepare-accessibility','snapshot','own-session-target','own-search-start','own-search-target','message-rows','latest-messages','toggle-panel','open-file','send','send-batch','panel','panel-tab','menu','menu-observe','import-status','clear-staged')){throw 'invalid_uia_action'}
   $WindowHandle=[long]$request.window; $ClientProcessId=[int]$request.pid
   $Executable=[string]$request.exe; $ParentHandle=[long]$request.parent; $Action=[string]$request.action
   Invoke-Request
  } catch { @{ok=$false;reason=$_.Exception.Message}|ConvertTo-Json -Compress }
  [Console]::Out.Flush()
 }
} else { Invoke-Request }
