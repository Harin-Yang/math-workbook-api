# docx.ps1 - 추출한 문제를 좌우 2단 워드 문서로 만든다. Mathpix 호출 없음 = 무료.
#
# 사용법 (mathocr 폴더에서):
#   .\win\docx.ps1 기하 "기하 문제집" 3
#   .\win\docx.ps1 확률과통계 "확률과 통계 문제집" 5
#
# 처음 한 번만:
#   Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
#   python -m pip install python-docx pymupdf

param(
    [Parameter(Mandatory = $true)][string]$Filter,
    [string]$Title = "추출 문제집",
    [int]$AnswerLines = 3
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"

Set-Location $PSScriptRoot\..

if (-not (Test-Path "stage0_out\runs")) {
    Write-Host "stage0_out\runs 가 없습니다. 서버에서 받아오세요:"
    Write-Host "  scp -r root@158.247.240.59:'~/mathocr/stage0_out' ."
    exit 1
}

$name = $Title -replace ' ', '_'
$out = "out\$name.docx"
New-Item -ItemType Directory -Force -Path out | Out-Null

$args = @("scripts\make_docx.py", "--out", $out, "--title", $Title,
          "--answer-lines", "$AnswerLines")
foreach ($part in $Filter -split ',') {
    $part = $part.Trim()
    if ($part) { $args += @("--file", $part) }
}

python @args
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host ""
Write-Host "만들어진 파일: $((Resolve-Path $out).Path)"
Write-Host "열려면:  ii `"$out`""
