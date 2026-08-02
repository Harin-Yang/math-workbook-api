# update.ps1 - 저장소에서 최신 코드를 받아온다.
#
# 사용법 (mathocr 폴더에서):
#   .\win\update.ps1
#
# git 으로 받은 폴더면 git pull 을 쓰고,
# 아니면 압축본을 내려받아 scripts 와 win 폴더만 덮어쓴다.
# stage0_out / samples / refs / out 은 건드리지 않는다.

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

Set-Location $PSScriptRoot\..

if (Test-Path ".git") {
    git pull
    exit $LASTEXITCODE
}

$url = "https://codeload.github.com/Harin-Yang/math-workbook-api/zip/refs/heads/main"
$tmp = Join-Path $env:TEMP ("mathocr_" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $tmp | Out-Null
$zip = Join-Path $tmp "repo.zip"

Write-Host "코드 받는 중..."
Invoke-WebRequest -Uri $url -OutFile $zip
Expand-Archive -Path $zip -DestinationPath $tmp -Force

$root = Join-Path $tmp "math-workbook-api-main"
foreach ($d in @("scripts", "win")) {
    $src = Join-Path $root $d
    if (Test-Path $src) {
        New-Item -ItemType Directory -Force -Path $d | Out-Null
        Copy-Item "$src\*" $d -Recurse -Force
        $n = (Get-ChildItem $d -File).Count
        Write-Host "  OK   $d  ($n개)"
    }
}

Remove-Item $tmp -Recurse -Force

Write-Host ""
Write-Host "동기화 완료. 명령:"
Write-Host "  .\win\docx.ps1 기하 `"기하 문제집`" 3     # 2단 워드 문서 만들기"
Write-Host "  .\win\grade.ps1 -List                      # run 폴더 이름 보기"
