# grade.ps1 - 기준 파일과 추출 결과를 대조해 점수를 낸다. Mathpix 호출 없음 = 무료.
#
# 사용법 (mathocr 폴더에서):
#   .\win\grade.ps1 -List
#   .\win\grade.ps1 "refs\[기하][신사고][문제편집].pdf" 기하 기하 "메모"
#
# 인자
#   Ref     기준 파일 PDF 경로
#   Filter  run 폴더 이름에 들어 있는 글자. 쉼표로 여러 개
#   Tag     점수 이력에 남길 이름
#   Note    이번 실행이 어떤 룰인지 적어 두는 칸

param(
    [string]$Ref,
    [string]$Filter,
    [string]$Tag,
    [string]$Note = "",
    [switch]$List
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"

Set-Location $PSScriptRoot\..

if ($List) {
    python scripts\grade.py --list
    exit $LASTEXITCODE
}

if (-not $Ref) {
    Write-Host "기준 파일 PDF 경로가 필요합니다."
    Write-Host "  .\win\grade.ps1 -List                       # run 폴더 확인"
    Write-Host "  .\win\grade.ps1 <기준.pdf> <필터> <태그> [메모]"
    exit 1
}
if (-not (Test-Path $Ref)) {
    Write-Host "기준 파일이 없습니다: $Ref"
    exit 1
}

$args = @("scripts\grade.py", "--ref", $Ref)
foreach ($part in $Filter -split ',') {
    $part = $part.Trim()
    if ($part) { $args += @("--file", $part) }
}
if ($Tag)  { $args += @("--tag", $Tag) }
if ($Note) { $args += @("--note", $Note) }

python @args
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$name = if ($Tag) { $Tag } else { [IO.Path]::GetFileNameWithoutExtension($Ref) }
$md = "grade_out\GRADE_$name.md"
if (Test-Path $md) {
    Write-Host ""
    Write-Host "================================================================"
    Write-Host " 아래 전체를 복사해서 전달하세요"
    Write-Host "================================================================"
    Write-Host ""
    Get-Content $md -Encoding UTF8
}
