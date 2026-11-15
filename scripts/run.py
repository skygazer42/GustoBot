#!/usr/bin/env python
"""GustoBot 后端服务的启动、检查与诊断命令。"""

import argparse
import subprocess
import sys
from importlib import import_module
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def check_requirements() -> bool:
    if sys.version_info < (3, 9):
        print("需要 Python 3.9 或更高版本")
        return False
    print(f"Python 版本: {sys.version.split()[0]}")

    if not (PROJECT_ROOT / ".env").is_file():
        print(".env 文件不存在，也可以通过环境变量配置服务")
        if input("是否从 .env.example 创建 .env? (y/n): ").strip().lower() == "y":
            create_env_example()

    try:
        import_module("fastapi")
        import_module("uvicorn")
    except ImportError:
        print("缺少核心依赖，请运行: pip install -r requirements.txt")
        return False
    print("核心依赖已安装")
    return True


def create_env_example() -> None:
    template = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")
    with (PROJECT_ROOT / ".env").open("x", encoding="utf-8") as env_file:
        env_file.write(template)
    print("已从 .env.example 创建 .env，请按实际环境编辑配置")


def start_server(mode: str) -> None:
    command = [
        sys.executable,
        "-m",
        "uvicorn",
        "gustobot.main:application",
        "--host",
        "0.0.0.0",
        "--port",
        "8000",
    ]
    if mode == "dev":
        command.append("--reload")
    else:
        command.extend(["--workers", "4"])

    print(f"启动 GustoBot 后端，模式: {mode}")
    print("服务地址: http://localhost:8000")
    print("API 文档: http://localhost:8000/docs")
    print("按 Ctrl+C 停止服务")
    try:
        subprocess.run(command, cwd=PROJECT_ROOT, check=True)
    except KeyboardInterrupt:
        print("服务已停止")


def start_docker() -> None:
    compose_file = PROJECT_ROOT / "docker-compose.yml"
    if not compose_file.is_file():
        raise FileNotFoundError(f"Docker Compose 配置不存在: {compose_file}")

    print("构建 Docker 镜像...")
    subprocess.run(["docker-compose", "build"], cwd=PROJECT_ROOT, check=True)
    try:
        print("启动 Docker 服务...")
        subprocess.run(["docker-compose", "up"], cwd=PROJECT_ROOT, check=True)
    except KeyboardInterrupt:
        print("正在停止 Docker 服务...")
        subprocess.run(["docker-compose", "down"], cwd=PROJECT_ROOT, check=True)


def test_api() -> None:
    # 帮助与依赖检查命令需要在 HTTP 客户端尚未安装时也能运行。
    import httpx

    with httpx.Client(timeout=15.0, trust_env=False) as client:
        response = client.get("http://localhost:8000/health")
        response.raise_for_status()
        health = response.json()
        print(f"健康检查通过，版本: {health['version']}")

        response = client.post(
            "http://localhost:8000/api/v1/chat/",
            json={"message": "你好", "session_id": None, "user_id": "tester"},
        )
        response.raise_for_status()
        chat = response.json()
        print("聊天 API 测试通过")
        print(f"路由: {chat.get('route')}")
        print(f"回复: {chat['message'][:50]}...")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="GustoBot 后端服务管理工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python run.py start       # 开发模式启动
  python run.py start prod  # 生产模式启动
  python run.py docker      # Docker 启动
  python run.py test        # 测试 API
        """,
    )
    subparsers = parser.add_subparsers(dest="command", help="可用命令")
    start_parser = subparsers.add_parser("start", help="启动服务器")
    start_parser.add_argument(
        "mode", nargs="?", default="dev", choices=["dev", "prod"], help="启动模式 (默认: dev)"
    )
    subparsers.add_parser("docker", help="使用 Docker 启动")
    subparsers.add_parser("test", help="测试 API")
    subparsers.add_parser("check", help="检查系统要求")
    args = parser.parse_args()

    if args.command == "start":
        if not check_requirements():
            return 1
        start_server(args.mode)
    elif args.command == "docker":
        start_docker()
    elif args.command == "test":
        test_api()
    elif args.command == "check":
        return 0 if check_requirements() else 1
    else:
        parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
