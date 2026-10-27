param([string]$Dir, [string]$OutDir)

Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Storage.StorageFile, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Globalization.Language, Windows.Foundation, ContentType = WindowsRuntime]

$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
  $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
})[0]

function Await($op, $type) {
  $task = $asTask.MakeGenericMethod($type).Invoke($null, @($op))
  $task.Wait(-1) | Out-Null
  $task.Result
}

$engine = $null
foreach ($lang in @("en-US", "en-GB")) {
  try {
    $langObj = [Windows.Globalization.Language]::new($lang)
    $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($langObj)
    if ($engine) { Write-Output "engine=$lang"; break }
  } catch { }
}
if (-not $engine) {
  $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
  Write-Output "engine=profile"
}
if (-not $engine) { Write-Output "NO_ENGINE"; exit 1 }

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

foreach ($img in Get-ChildItem -Path $Dir -Filter *.png | Sort-Object Name) {
  $dest = Join-Path $OutDir ($img.BaseName + ".json")
  if (Test-Path $dest) { continue }
  try {
    $file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($img.FullName)) ([Windows.Storage.StorageFile])
    $stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
    $decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
    $bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
    $result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])

    $lines = New-Object System.Collections.ArrayList
    foreach ($line in $result.Lines) {
      $words = New-Object System.Collections.ArrayList
      foreach ($w in $line.Words) {
        [void]$words.Add([ordered]@{
            t = $w.Text
            x = [math]::Round($w.BoundingRect.X, 1)
            y = [math]::Round($w.BoundingRect.Y, 1)
            w = [math]::Round($w.BoundingRect.Width, 1)
            h = [math]::Round($w.BoundingRect.Height, 1)
          })
      }
      [void]$lines.Add($words)
    }

    $payload = [ordered]@{ width = $bitmap.PixelWidth; height = $bitmap.PixelHeight; lines = $lines }
    [System.IO.File]::WriteAllText($dest, ($payload | ConvertTo-Json -Depth 8 -Compress), [System.Text.UTF8Encoding]::new($false))
    $stream.Dispose()
    Write-Output ("ok " + $img.BaseName)
  } catch {
    Write-Output ("fail " + $img.BaseName + " " + $_.Exception.Message)
  }
}
