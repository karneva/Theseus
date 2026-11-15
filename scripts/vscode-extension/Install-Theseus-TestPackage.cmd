@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%.") do set "SCRIPT_DIR=%%~fI"
for %%I in ("%SCRIPT_DIR%\..\..") do set "REPO_DIR=%%~fI"

rem Test package layout: this wrapper sits at the package root next to scripts\install-test-package.ps1.
set "PACKAGE_DIR=%SCRIPT_DIR%"
set "INSTALLER=%PACKAGE_DIR%\scripts\install-test-package.ps1"
if exist "%INSTALLER%" goto :installer_found

rem Repository layout: this wrapper lives in scripts\vscode-extension\, so the package root is the repository root.
set "PACKAGE_DIR=%REPO_DIR%"
set "INSTALLER=%PACKAGE_DIR%\backend\theseus-core-server\scripts\install-test-package.ps1"
if exist "%INSTALLER%" goto :installer_found

echo Theseus test package installer was not found.
echo.
echo Expected one of:
echo   %SCRIPT_DIR%\scripts\install-test-package.ps1
echo   %REPO_DIR%\backend\theseus-core-server\scripts\install-test-package.ps1
echo.
echo Put this file next to the package scripts folder, or keep it in scripts\vscode-extension\ of the repository.
pause
exit /b 1

:installer_found

echo Theseus test package setup
echo Package : %PACKAGE_DIR%
echo Installer: %INSTALLER%
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%INSTALLER%" -PackagePath "%PACKAGE_DIR%" %*
set "EXIT_CODE=%ERRORLEVEL%"

echo.
if not "%EXIT_CODE%"=="0" (
    echo Theseus test package setup failed with exit code %EXIT_CODE%.
    pause
    exit /b %EXIT_CODE%
)

echo Theseus test package setup complete.
pause
exit /b 0
