# Pinned Windows OCR installation. Winget verifies the published installer hash.
$ErrorActionPreference = 'Stop'
winget install --id UB-Mannheim.TesseractOCR --exact --version 5.4.0.20240606 --source winget --silent --disable-interactivity --accept-source-agreements --accept-package-agreements
if ($LASTEXITCODE -notin @(0, -1978335189)) { throw 'Tesseract installation failed; inspect winget output' }
$ocrExe = Join-Path $env:ProgramFiles 'Tesseract-OCR\tesseract.exe'
if (!(Test-Path -LiteralPath $ocrExe)) { throw 'Set BIGSTEN_TESSERACT_CMD to the actual executable path' }
& $ocrExe --version
& $ocrExe --list-langs
# SHA256 installer: c885fff6998e0608ba4bb8ab51436e1c6775c2bafc2559a19b423e18678b60c9
# Certification digits and PSA/BGS/CGC labels use eng. Japanese catalog text is independent of OCR.

$tessData = Join-Path $PSScriptRoot 'private\tessdata'
New-Item -ItemType Directory -Force $tessData | Out-Null
$hashes = @{
    eng = '7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2'
    jpn = '1f5de9236d2e85f5fdf4b3c500f2d4926f8d9449f28f5394472d9e8d83b91b4d'
}
foreach ($lang in @('eng', 'jpn')) {
    $target = Join-Path $tessData "$lang.traineddata"
    Invoke-WebRequest "https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/87416418657359cb625c412a48b6e1d6d41c29bd/$lang.traineddata" -OutFile $target
    if ((Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash -ne $hashes[$lang]) { throw 'Language data checksum mismatch' }
}
& $ocrExe --tessdata-dir $tessData --list-langs
