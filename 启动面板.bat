@echo off
chcp 65001 >nul
title まあ丸 — 本丸近侍面板 启动器

echo ========================================
echo   🦊 まあ丸 — 近侍面板启动器
echo   刀剑乱舞自动托管引擎
echo ========================================
echo.

:: ── 1. 检查 Python ──
set PYTHON=
where py >nul 2>nul
if %errorlevel% equ 0 (
    for /f "delims=" %%i in ('py -3.12 -c "import sys; print(sys.executable)" 2^>nul') do set PYTHON=%%i
)
if "%PYTHON%"=="" (
    where python >nul 2>nul
    if %errorlevel% equ 0 (
        for /f "delims=" %%i in ('python -c "import sys; print(sys.executable)" 2^>nul') do set PYTHON=%%i
    )
)
if "%PYTHON%"=="" (
    echo ❌ 没找到 Python 3.12+
    echo.
    echo 请先安装 Python 3.12：https://www.python.org/downloads/
    echo 安装时勾选 "Add Python to PATH"
    pause
    exit /b 1
)
echo ✓ Python: %PYTHON%

:: ── 2. 检查版本 ──
"%PYTHON%" -c "import sys; ver=sys.version_info; exit(0 if ver.major==3 and ver.minor>=12 else 1)"
if %errorlevel% neq 0 (
    echo ❌ 需要 Python 3.12+（当前版本过低）
    pause
    exit /b 1
)

:: ── 3. 虚拟环境 ──
if not exist ".venv\Scripts\python.exe" (
    echo 🔧 创建虚拟环境...
    "%PYTHON%" -m venv .venv
    if %errorlevel% neq 0 (
        echo ❌ 虚拟环境创建失败
        pause
        exit /b 1
    )
    echo ✓ 虚拟环境已创建
) else (
    echo ✓ 虚拟环境已存在
)

:: ── 4. 安装依赖 ──
echo 📦 检查依赖...
".venv\Scripts\python.exe" -c "import fastapi, uvicorn, httpx, maa" 2>nul
if %errorlevel% neq 0 (
    echo 📦 安装依赖（首次运行可能需要几分钟）...
    ".venv\Scripts\python.exe" -m pip install -q --upgrade pip
    ".venv\Scripts\python.exe" -m pip install -q -e .
    ".venv\Scripts\python.exe" -m pip install -q fastapi uvicorn httpx
    if %errorlevel% neq 0 (
        echo ⚠️ 部分依赖安装失败，请检查网络
        echo    可能需要配置 pip 镜像：pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple
    )
    echo ✓ 依赖安装完成
) else (
    echo ✓ 依赖已就绪
)

:: ── 5. 检查资源文件 ──
if not exist "resource\base\model\ocr\rec.onnx" (
    echo.
    echo ⚠️ 资源文件缺失（约 33MB）
    echo.
    echo 方式一：自动下载（需要网络）
    set /p DOWNLOAD="   按回车自动下载，或输入 n 跳过自行处理："
    if /i "!DOWNLOAD!" neq "n" (
        echo 📥 正在下载资源包...
        ".venv\Scripts\python.exe" -c "
import urllib.request, zipfile, os, sys
url = 'https://github.com/DbDB68/maamaru-engine/releases/latest/download/resource.zip'
print(f'  从 {url}')
try:
    urllib.request.urlretrieve(url, 'resource.zip')
    with zipfile.ZipFile('resource.zip', 'r') as z:
        z.extractall('.')
    os.remove('resource.zip')
    print('✓ 资源包下载并解压完成')
except Exception as e:
    print(f'❌ 下载失败: {e}')
    print('请手动下载 resource.zip 放到项目根目录解压')
    print('下载地址: https://github.com/DbDB68/maamaru-engine/releases')
    sys.exit(1)
"
    ) else (
        echo 请手动下载 resource.zip 放到项目目录解压
    )
    echo.
) else (
    echo ✓ 资源文件已就绪
)

:: ── 6. 启动面板 ──
echo.
echo ========================================
echo   🚀 启动面板...
echo ========================================
echo.

start "" http://localhost:8080

".venv\Scripts\python.exe" -m panel.server --host 0.0.0.0 --port 8080

if %errorlevel% neq 0 (
    echo.
    echo ❌ 面板意外关闭（错误码：%errorlevel%）
    pause
)
