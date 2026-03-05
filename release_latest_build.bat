@echo off
setlocal enabledelayedexpansion

if "%GITHUB_TOKEN%"=="" (
  echo GITHUB_TOKEN is required.
  exit /b 2
)

for /f %%i in ('git status --porcelain') do (
  echo Working tree is not clean. Commit or stash changes before releasing.
  exit /b 2
)

if "%TARGET_COMMITISH%"=="" (
  set "TARGET_COMMITISH=HEAD"
)

set "VERSION_FILE=%~dp0version"
if not exist "%VERSION_FILE%" (
  echo version file not found at %VERSION_FILE%
  exit /b 2
)

set "TAG="
for /f "usebackq delims=" %%i in ("%VERSION_FILE%") do (
  set "TAG=%%i"
  goto :tag_loaded
)

:tag_loaded
if "%TAG%"=="" (
  echo version file is empty. Expected release tag in %VERSION_FILE%
  exit /b 2
)

set "TITLE=%RELEASE_TITLE%"
if "%TITLE%"=="" set "TITLE=ecube %TAG%"

set "PRERELEASE=%PRERELEASE%"
if "%PRERELEASE%"=="" set "PRERELEASE=true"

set "DRAFT_RELEASE=%DRAFT_RELEASE%"
if "%DRAFT_RELEASE%"=="" set "DRAFT_RELEASE=false"

for /f %%i in ('git remote get-url origin') do set "ORIGIN_URL=%%i"

if "%GITHUB_OWNER%"=="" (
  for /f "tokens=2 delims=/" %%i in ('echo %ORIGIN_URL:^:=/%') do set "GITHUB_OWNER=%%i"
)
if "%GITHUB_REPO%"=="" (
  for /f "tokens=3 delims=/" %%i in ('echo %ORIGIN_URL:^:=/%') do set "GITHUB_REPO=%%i"
)
set "GITHUB_REPO=%GITHUB_REPO:.git=%"

if "%GITHUB_OWNER%"=="" (
  echo Could not parse GitHub owner from origin URL: %ORIGIN_URL%
  exit /b 1
)
if "%GITHUB_REPO%"=="" (
  echo Could not parse GitHub repo from origin URL: %ORIGIN_URL%
  exit /b 1
)

set "RELEASE_BY_TAG_URL=https://api.github.com/repos/%GITHUB_OWNER%/%GITHUB_REPO%/releases/tags/%TAG%"
curl -fsS ^
  -H "Accept: application/vnd.github+json" ^
  -H "Authorization: Bearer %GITHUB_TOKEN%" ^
  -H "X-GitHub-Api-Version: 2022-11-28" ^
  "%RELEASE_BY_TAG_URL%" >nul 2>nul
if %errorlevel%==0 (
  echo Release already exists for tag %TAG%
  exit /b 1
)

set "CREATE_URL=https://api.github.com/repos/%GITHUB_OWNER%/%GITHUB_REPO%/releases"
set "PAYLOAD_FILE=%TEMP%\ecube-release-payload-%RANDOM%.json"
set "RESP_FILE=%TEMP%\ecube-release-response-%RANDOM%.json"

(
  echo {
  echo   "tag_name": "%TAG%",
  echo   "target_commitish": "%TARGET_COMMITISH%",
  echo   "name": "%TITLE%",
  echo   "draft": %DRAFT_RELEASE%,
  echo   "prerelease": %PRERELEASE%,
  echo   "generate_release_notes": true
  echo }
) > "%PAYLOAD_FILE%"

for /f %%i in ('curl -sS -o "%RESP_FILE%" -w "%%{http_code}" -X POST "%CREATE_URL%" -H "Accept: application/vnd.github+json" -H "Authorization: Bearer %GITHUB_TOKEN%" -H "X-GitHub-Api-Version: 2022-11-28" -H "Content-Type: application/json" --data-binary @"%PAYLOAD_FILE%"') do set "HTTP_CODE=%%i"

if %HTTP_CODE% LSS 200 (
  echo GitHub API error %HTTP_CODE%:
  type "%RESP_FILE%"
  del /q "%PAYLOAD_FILE%" "%RESP_FILE%" >nul 2>nul
  exit /b 1
)
if %HTTP_CODE% GEQ 300 (
  echo GitHub API error %HTTP_CODE%:
  type "%RESP_FILE%"
  del /q "%PAYLOAD_FILE%" "%RESP_FILE%" >nul 2>nul
  exit /b 1
)

echo Release created: %TAG%
for /f %%i in ('powershell -NoProfile -Command "$j=Get-Content -Raw ''%RESP_FILE%'' ^| ConvertFrom-Json; if($j.html_url){$j.html_url}"') do set "HTML_URL=%%i"
if not "%HTML_URL%"=="" echo URL: %HTML_URL%
echo The release-artifact workflow will publish package assets for this release.

del /q "%PAYLOAD_FILE%" "%RESP_FILE%" >nul 2>nul
exit /b 0
