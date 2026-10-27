@echo off
setlocal
cd /d "%~dp0"

set "PORT=8787"
set "OPEN=1"

rem ---------- 参数 ----------
:parse
if "%~1"=="" goto afterparse
if /i "%~1"=="--no-open" (set "OPEN=0" & shift & goto parse)
if /i "%~1"=="--help" goto usage
if /i "%~1"=="-h" goto usage
if /i "%~1"=="-p" (set "PORT=%~2" & shift & shift & goto parse)
set "PORT=%~1"
shift
goto parse

:usage
echo.
echo   用法: start.bat [端口] [--no-open]
echo   默认端口 8787, 被占用会自动往后找
echo   停止服务: 在这个窗口按 Ctrl+C
echo.
pause
exit /b 0

:afterparse

rem ---------- 找 node ----------
set "NODE="
where node >nul 2>nul
if not errorlevel 1 set "NODE=node"
if not defined NODE if exist "%USERPROFILE%\.workbuddy\binaries\node\versions\24.22.0\node.exe" set "NODE=%USERPROFILE%\.workbuddy\binaries\node\versions\24.22.0\node.exe"
if not defined NODE if exist "%USERPROFILE%\.workbuddy\binaries\node\versions\22.22.2-3\node.exe" set "NODE=%USERPROFILE%\.workbuddy\binaries\node\versions\22.22.2-3\node.exe"
if not defined NODE (
  echo.
  echo   [错误] 没找到 node.exe
  echo   先装 Node 18+, 或者改 start.bat 里的兜底路径, 指到你自己的 node.exe
  echo.
  pause
  exit /b 1
)

rem ---------- 端口被占就顺延到 8799 ----------
:findport
netstat -ano | findstr /r /c:":%PORT% .*LISTENING" >nul
if errorlevel 1 goto portok
echo   端口 %PORT% 已被占用, 试下一个...
set /a PORT+=1
if %PORT% gtr 8799 (
  echo   8787-8799 都被占用了, 先关掉一个再启动
  pause
  exit /b 1
)
goto findport
:portok

echo.
echo   本地真题备考工作台
echo   地址  http://127.0.0.1:%PORT%/
echo   node  %NODE%
echo   停止  在这个窗口按 Ctrl+C
echo   浏览器没自动打开就手动访问上面的地址
echo.

rem ---------- 等两秒再开浏览器, 免得白屏一次 ----------
if "%OPEN%"=="0" goto servestart
start "zhenti-opener" /min cmd /c "ping -n 3 127.0.0.1 >nul & start http://127.0.0.1:%PORT%/index.html"

:servestart
"%NODE%" server.mjs --port %PORT%
if not errorlevel 1 goto done
echo.
echo   服务已停止, 退出码 %errorlevel% 。报错信息往上翻
pause

:done
