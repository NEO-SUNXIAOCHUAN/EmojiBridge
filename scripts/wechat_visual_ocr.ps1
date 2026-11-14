param([Parameter(Mandatory=$true)][string]$ImagePath)
# Windows' installed OCR only. No client process access or global settings.
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
try {
 Add-Type -AssemblyName System.Runtime.WindowsRuntime
 $null=[Windows.Storage.StorageFile,Windows.Storage,ContentType=WindowsRuntime]
 $null=[Windows.Graphics.Imaging.BitmapDecoder,Windows.Graphics.Imaging,ContentType=WindowsRuntime]
 $null=[Windows.Media.Ocr.OcrEngine,Windows.Foundation,ContentType=WindowsRuntime]
 $null=[Windows.Globalization.Language,Windows.Globalization,ContentType=WindowsRuntime]
 $method=[System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
  $_.Name -eq 'AsTask' -and $_.IsGenericMethod -and $_.GetParameters().Count -eq 1 -and
  $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
 } | Select-Object -First 1
 function Await($operation,$type) {
  $task=$method.MakeGenericMethod($type).Invoke($null,@($operation))
  if(-not $task.Wait(10000)){throw 'ocr_operation_timeout'}
  return $task.Result
 }
 $file=Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync([IO.Path]::GetFullPath($ImagePath))) ([Windows.Storage.StorageFile])
 $stream=Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream,Windows.Storage.Streams,ContentType=WindowsRuntime])
 try {
  $decoder=Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
  $bitmap=Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap,Windows.Graphics.Imaging,ContentType=WindowsRuntime])
  try {
   $language=[Windows.Globalization.Language]::new('zh-Hans')
   $engine=[Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($language)
   if($null -eq $engine){throw 'wechat_visual_chinese_ocr_unavailable'}
   $result=Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult,Windows.Foundation,ContentType=WindowsRuntime])
   $rows=@()
   foreach($line in $result.Lines){
    $words=@()
    foreach($word in $line.Words){
     $b=$word.BoundingRect
     $words+=,@{text=$word.Text;rect=@($b.X,$b.Y,($b.X+$b.Width),($b.Y+$b.Height))}
    }
    $rows+=,@{text=$line.Text;words=$words}
   }
   @{ok=$true;lines=$rows}|ConvertTo-Json -Depth 8 -Compress
  }finally{if($bitmap){$bitmap.Dispose()}}
 }finally{if($stream){$stream.Dispose()}}
}catch{
 $reason=if($_.Exception.Message -eq 'wechat_visual_chinese_ocr_unavailable'){'wechat_visual_chinese_ocr_unavailable'}else{'wechat_visual_ocr_failed'}
 @{ok=$false;reason=$reason}|ConvertTo-Json -Compress
 exit 2
}
