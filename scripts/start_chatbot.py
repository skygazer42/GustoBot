"""同时启动本地后端 API 和前端 Vite 开发服务器。"""

import os
import shutil
import signal
import subprocess
import sys
import time
from contextlib import ExitStack, suppress
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = PROJECT_ROOT / "web"


def start_backend() -> subprocess.Popen[bytes]:
    """Start the reload-enabled backend in its own process group."""
    print("启动后端服务器...")
    creationflags = 0
    if sys.platform == "win32":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
    command = [
        sys.executable,
        "-m",
        "uvicorn",
        "gustobot.main:application",
        "--reload",
        "--host",
        "0.0.0.0",
        "--port",
        "8000",
    ]
    return subprocess.Popen(
        command,
        cwd=PROJECT_ROOT,
        start_new_session=sys.platform != "win32",
        creationflags=creationflags,
    )


def start_frontend() -> subprocess.Popen[bytes]:
    """Start Vite after checking the web project and npm installation."""
    if not WEB_ROOT.is_dir():
        raise FileNotFoundError(f"web 目录不存在: {WEB_ROOT}")
    npm = shutil.which("npm")
    if npm is None:
        raise FileNotFoundError("找不到 npm，请先安装 Node.js 并将 npm 加入 PATH")

    if not (WEB_ROOT / "node_modules").is_dir():
        print("安装前端依赖...")
        subprocess.run([npm, "install"], cwd=WEB_ROOT, check=True)

    print("启动前端服务器，Vite 将打开实际监听地址...")
    creationflags = 0
    if sys.platform == "win32":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
    command = [npm, "run", "dev", "--", "--host", "0.0.0.0", "--open"]
    return subprocess.Popen(
        command,
        cwd=WEB_ROOT,
        start_new_session=sys.platform != "win32",
        creationflags=creationflags,
    )


def _stop_process(process: subprocess.Popen[bytes]) -> None:
    """Stop a child process tree and wait for termination on each platform."""
    if sys.platform == "win32":
        if process.poll() is None:
            # npm 和 uvicorn reload 都会创建子进程，只终止父进程会留下服务。
            result = subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"], check=False, timeout=10
            )
            if result.returncode != 0 and process.poll() is None:
                result.check_returncode()
        process.wait(timeout=10)
        return

    with suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=10)


def main() -> None:
    """Run both development servers and clean them up if either exits."""
    print("正在启动 GustoBot 开发服务...")
    try:
        with ExitStack() as cleanup:
            backend = start_backend()
            cleanup.callback(_stop_process, backend)
            frontend = start_frontend()
            cleanup.callback(_stop_process, frontend)

            print("服务进程已启动，地址见服务输出。按 Ctrl+C 停止。")
            while True:
                for name, process in (("后端", backend), ("前端", frontend)):
                    returncode = process.poll()
                    if returncode is not None:
                        raise RuntimeError(f"{name}进程已退出，退出码: {returncode}")
                time.sleep(1)
    except KeyboardInterrupt:
        print("服务已停止。")


if __name__ == "__main__":
    main()
