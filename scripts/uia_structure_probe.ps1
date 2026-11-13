param([long]$WindowHandle, [int]$ClientProcessId)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$watch = [Diagnostics.Stopwatch]::StartNew()
$root = [System.Windows.Automation.AutomationElement]::FromHandle([IntPtr]$WindowHandle)
if ($root.Current.ProcessId -ne $ClientProcessId) { throw 'window_identity_changed' }
$walker = [System.Windows.Automation.TreeWalker]::RawViewWalker
$queue = [Collections.Generic.Queue[object]]::new()
$queue.Enqueue(@{node=$root; depth=0})
$types = @{}; $patterns = @{}; $count = 0; $errors = 0; $pruned = 0; $truncated = $false
while ($queue.Count -gt 0) {
    if ($count -ge 600 -or $watch.Elapsed.TotalSeconds -gt 8) { $truncated=$true; break }
    $entry = $queue.Dequeue(); $node = $entry.node; $count++
    try {
        $kind = $node.Current.ControlType.Id
        $key = [string]$kind
        $types[$key] = 1 + $types[$key]
        $propertyMap = @{
            invoke=[System.Windows.Automation.AutomationElement]::IsInvokePatternAvailableProperty
            scroll=[System.Windows.Automation.AutomationElement]::IsScrollPatternAvailableProperty
            selection_item=[System.Windows.Automation.AutomationElement]::IsSelectionItemPatternAvailableProperty
        }
        foreach ($label in $propertyMap.Keys) {
            if ($node.GetCurrentPropertyValue($propertyMap[$label])) { $patterns[$label] = 1 + $patterns[$label] }
        }
        if ($kind -eq 50007 -or $entry.depth -ge 48) { $pruned++; continue }
        $child = $walker.GetFirstChild($node)
        while ($null -ne $child) {
            if (($count + $queue.Count) -ge 600 -or $watch.Elapsed.TotalSeconds -gt 8) { $truncated=$true; break }
            $queue.Enqueue(@{node=$child; depth=($entry.depth + 1)})
            $child = $walker.GetNextSibling($child)
        }
    } catch { $errors++ }
}
@{ok=($root.Current.ProcessId -eq $ClientProcessId); backend='dotnet_uia'; nodes=$count;
  types=$types; patterns=$patterns; errors=$errors; pruned_list_items_or_depth=$pruned;
  truncated=$truncated; traversal_seconds=[Math]::Round($watch.Elapsed.TotalSeconds,4)} | ConvertTo-Json -Compress -Depth 5
