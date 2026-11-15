@echo off
REM GustoBot 开发环境启动脚本 (Windows)

cd /d %~dp0..

echo GustoBot 智能菜谱助手
echo ==========================
echo.

REM 检查 Docker
docker --version >nul 2>&1
if errorlevel 1 (
    echo ��� Docker 未安装，请先安装 Docker Desktop
    pause
    exit /b 1
)

docker-compose --version >nul 2>&1
if errorlevel 1 (
    echo ��� Docker Compose 未安装，请先安装 Docker Compose
    pause
    exit /b 1
)

REM 选择启动方式
echo 请选择启动方式：
echo 1) Docker Compose (推荐)
echo 2) 本地开发
echo 3) 仅后端
echo 4) 仅前端
echo.
set /p choice=请输入选择 (1-4):

if "%choice%"=="1" goto docker
if "%choice%"=="2" goto local
if "%choice%"=="3" goto backend
if "%choice%"=="4" goto frontend
goto invalid

:docker
echo.
echo 使用 Docker Compose 启动默认后端服务...
echo.

REM 检查 .env 文件
if not exist .env (
    echo ��� .env 文件不存在，请先配置 .env 文件
    pause
    exit /b 1
)

REM 启动服务
docker-compose -f docker-compose.yml up -d

echo.
echo ✅ 服务启动成功！
echo.
echo 访问地址：
echo   • 后端: http://localhost:8000
echo   • API文档: http://localhost:8000/docs
echo.
echo 查看日志: docker-compose -f docker-compose.yml logs -f
echo 停止服务: docker-compose -f docker-compose.yml down
pause
exit /b 0

:local
echo.
echo 💻 本地开发模式...
echo.

REM 启动后端
echo 启动后端...
if not exist venv (
    echo 创建虚拟环境...
    python -m venv venv
)

call venv\Scripts\activate
pip install -r requirements.txt

REM 后台启动后端
start /B python run.py start

REM 启动前端
echo 启动前端...
cd web
if not exist node_modules (
    echo 安装前端依赖...
    npm install
)

npm run dev
pause
exit /b 0

:backend
echo.
echo 🔧 仅启动后端...
echo.

if not exist venv (
    python -m venv venv
)

call venv\Scripts\activate
pip install -r requirements.txt
python run.py start
pause
exit /b 0

:frontend
echo.
echo 🎨 仅启动前端...
echo.

cd web
if not exist node_modules (
    npm install
)

npm run dev
pause
exit /b 0

:invalid
echo ❌ 无效选择
pause
exit /b 1
