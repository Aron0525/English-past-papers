$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
[Windows.Media.Ocr.OcrEngine]::AvailableRecognizerLanguages | ForEach-Object { Write-Output $_.LanguageTag }
Write-Output "maxdim=$([Windows.Media.Ocr.OcrEngine]::MaxImageDimension)"
