@echo off
setlocal EnableDelayedExpansion
chcp 936 >nul
title AI 训练师工作台 - 一键启动

rem ==================== 路径与配置 ====================
set "ROOT=%~dp0"
set "PROJ=%ROOT%skill-graph-learning"
set "APPDIR=%PROJ%\app"
set "PYEXE=%PROJ%\.venv\Scripts\python.exe"
set "DBPATH=%PROJ%\.mongo-data"
set "APPURL=http://127.0.0.1:5000/"
if not defined MONGO_URI set "MONGO_URI=mongodb://127.0.0.1:27017"

echo.
echo  ====================================================
echo     AI 训练师工作台   ^|   一键启动
echo  ====================================================
echo.

rem ---------- [1/5] 检查项目与 Python ----------
if not exist "%APPDIR%\app.py" (
    echo  [错误] 未找到项目文件：
    echo         %APPDIR%\app.py
    echo         请把本文件放在仓库根目录，与 skill-graph-learning 文件夹同级。
    echo.
    pause
    exit /b 1
)

if exist "%PYEXE%" (
    set "PYTHON=%PYEXE%"
    echo  [1/5] Python：项目虚拟环境 .venv
) else (
    where python >nul 2>nul
    if errorlevel 1 (
        echo  [错误] 未检测到 Python，请安装 Python 3.10 以上版本并勾选 Add to PATH。
        pause
        exit /b 1
    )
    set "PYTHON=python"
    echo  [1/5] Python：系统 Python
)

rem ---------- [2/5] 检查并安装依赖 ----------
"%PYTHON%" -c "import flask,pymongo,requests" >nul 2>nul
if errorlevel 1 (
    echo  [2/5] 首次运行，正在安装依赖，请稍候 ...
    "%PYTHON%" -m pip install -r "%PROJ%\requirements.txt"
    if errorlevel 1 (
        echo  [错误] 依赖安装失败，请检查网络后重试。
        pause
        exit /b 1
    )
    echo        依赖安装完成
) else (
    echo  [2/5] 依赖已就绪
)

rem ---------- [3/5] 检查并启动 MongoDB ----------
set "PING=0"
"%PYTHON%" -c "from pymongo import MongoClient;import os;MongoClient(os.environ['MONGO_URI'],serverSelectionTimeoutMS=1000).admin.command('ping')" >nul 2>nul
if not errorlevel 1 set "PING=1"

if "%PING%"=="1" (
    echo  [3/5] MongoDB 连接正常
) else (
    if /i not "%MONGO_URI%"=="mongodb://127.0.0.1:27017" (
        echo  [错误] 无法连接 MONGO_URI=%MONGO_URI%
        echo         请检查连接串，或确认远程数据库 / Atlas 集群可用。
        pause
        exit /b 1
    )
    echo  [3/5] 正在启动本地 MongoDB ...
    set "MONGOD="
    for %%M in (
        "C:\Program Files\MongoDB\Server\8.3\bin\mongod.exe"
        "C:\Program Files\MongoDB\Server\8.0\bin\mongod.exe"
        "C:\Program Files\MongoDB\Server\7.0\bin\mongod.exe"
        "C:\Program Files\MongoDB\Server\6.0\bin\mongod.exe"
    ) do if not defined MONGOD if exist %%M set "MONGOD=%%~M"
    if not defined MONGOD (
        for /f "delims=" %%M in ('where mongod 2^>nul') do if not defined MONGOD set "MONGOD=%%M"
    )
    if defined MONGOD (
        if not exist "%DBPATH%" mkdir "%DBPATH%" >nul 2>nul
        start "MongoDB - AI 训练师工作台" /min "!MONGOD!" --dbpath "%DBPATH%" --bind_ip 127.0.0.1 --port 27017
    ) else (
        echo        未找到 mongod.exe，尝试 Windows 服务或 Docker ...
        net start MongoDB >nul 2>nul
        where docker >nul 2>nul
        if not errorlevel 1 (
            pushd "%PROJ%"
            docker compose up -d >nul 2>nul
            popd
        )
    )
    set "READY="
    for /L %%i in (1,1,20) do if not defined READY (
        "%PYTHON%" -c "from pymongo import MongoClient;import os;MongoClient(os.environ['MONGO_URI'],serverSelectionTimeoutMS=800).admin.command('ping')" >nul 2>nul
        if not errorlevel 1 set "READY=1"
        if not defined READY ping -n 2 127.0.0.1 >nul
    )
    if not defined READY (
        echo  [错误] MongoDB 启动失败，请参考 README 中的 MongoDB 启动说明。
        pause
        exit /b 1
    )
    echo        MongoDB 已就绪
)

rem ---------- [4/5] 空库时初始化（已有数据绝不清空） ----------
"%PYTHON%" -c "from pymongo import MongoClient;import os,sys;c=MongoClient(os.environ['MONGO_URI'],serverSelectionTimeoutMS=3000);sys.exit(0 if c['trainer'].models.count_documents({})>0 else 1)" >nul 2>nul
if errorlevel 1 (
    echo  [4/5] 数据库为空，正在初始化索引与演示数据 ...
    pushd "%PROJ%"
    "%PYTHON%" init.py
    if errorlevel 1 (
        popd
        echo  [错误] 初始化失败，请检查 MongoDB 连接。
        pause
        exit /b 1
    )
    popd
) else (
    echo  [4/5] 已有数据，跳过初始化（不会清空现有数据）
)

rem ---------- [5/5] 启动网页后台 ----------
set "WEB=0"
"%PYTHON%" -c "import socket,sys;s=socket.socket();s.settimeout(1);sys.exit(0 if s.connect_ex(('127.0.0.1',5000))==0 else 1)" >nul 2>nul
if not errorlevel 1 set "WEB=1"

if "%WEB%"=="1" (
    echo  [5/5] 网页后台已在运行，直接打开浏览器
    if not "%AIWB_NO_BROWSER%"=="1" start "" "%APPURL%"
    echo.
    echo  访问地址：%APPURL%
    echo  按任意键关闭本窗口，不会停止已运行的服务。
    if not "%AIWB_NO_PAUSE%"=="1" pause >nul
    exit /b 0
)

echo  [5/5] 正在启动网页后台 ...
echo.
echo  ----------------------------------------------------
echo    访问地址：%APPURL%
echo    关闭此窗口 = 停止服务
echo    MongoDB 数据目录：%DBPATH%
echo  ----------------------------------------------------
echo.

if not "%AIWB_NO_BROWSER%"=="1" (
    start "打开浏览器" /min cmd /c "timeout /t 4 /nobreak >nul & explorer %APPURL%"
)

cd /d "%APPDIR%"
"%PYTHON%" app.py

echo.
echo  服务已停止。
if not "%AIWB_NO_PAUSE%"=="1" pause
