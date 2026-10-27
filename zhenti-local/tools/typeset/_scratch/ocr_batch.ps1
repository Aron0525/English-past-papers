param([string]$Dir, [string]$Out)

# 批量 OCR：对一个目录下所有 png 逐张识别，输出单个 json（页名 -> 行/词 + 包围盒）
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Storage.StorageFile, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Globalization.Language, Windows.Foundation, ContentType = WindowsRuntime]

$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
  $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
})[0]

function Await($op, $type) {
  $m = $asTask.MakeGenericMethod($type)
  $task = $m.Invoke($null, @($op))
  $task.Wait(-1) | Out-Null
  $task.Result
}

$engine = $null
foreach ($tag in @("en-US", "zh-Hans-CN", "zh-CN")) {
  try {
    $lang = New-Object Windows.Globalization.Language($tag)
    $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($lang)
    if ($engine) { Write-Output "engine=$tag"; break }
  } catch {
    Write-Output "lang $tag failed: $($_.Exception.Message)"
  }
}
if (-not $engine) {
  $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
  Write-Output "engine=profile"
}
if (-not $engine) { Write-Output "NO_ENGINE"; exit 1 }

$result = [ordered]@{}
$files = Get-ChildItem -Path $Dir -Filter *.png | Sort-Object Name
foreach ($f in $files) {
  $file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($f.FullName)) ([Windows.Storage.StorageFile])
  $stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
  $decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
  $bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
  $ocr = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
  $lines = @()
  foreach ($line in $ocr.Lines) {
    $words = @()
    foreach ($w in $line.Words) {
      $words += , @([math]::Round($w.BoundingRect.X, 1), [math]::Round($w.BoundingRect.Y, 1),
                    [math]::Round($w.BoundingRect.Width, 1), [math]::Round($w.BoundingRect.Height, 1), $w.Text)
    }
    if ($words.Count -gt 0) { $lines += , $words }
  }
  $result[$f.BaseName] = [ordered]@{ w = $bitmap.PixelWidth; h = $bitmap.PixelHeight; lines = $lines }
  $stream.Dispose()
}
$json = $result | ConvertTo-Json -Depth 10 -Compress
[System.IO.File]::WriteAllText($Out, $json, [System.Text.UTF8Encoding]::new($false))
Write-Output ("pages=" + $files.Count)
