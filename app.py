#!/usr/bin/env python3
"""
AI Agent 会话管理中心 (Agent Session Manager) - 统一启动器
执行本脚本将启动本地 Web 服务并自动打开浏览器。
支持环境变量与命令行参数配置。
"""

import os
import sys
import socket
import webbrowser
import threading
import time
import argparse

# 导入服务端
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(CURRENT_DIR, 'backend'))

from server import ThreadingHTTPServer, UnifiedAPIHandler


def kill_process_on_port(port: int = 8999):
    """清理占用默认端口的历史遗留服务 (仅本地非容器环境执行)"""
    try:
        import subprocess
        out = subprocess.check_output(f"lsof -ti :{port}", shell=True, stderr=subprocess.DEVNULL).decode().strip()
        if out:
            pids = out.split('\n')
            current_pid = str(os.getpid())
            for pid in pids:
                pid = pid.strip()
                if pid and pid != current_pid:
                    try:
                        os.kill(int(pid), 9)
                    except Exception:
                        pass
            time.sleep(0.2)
    except Exception:
        pass


def find_free_port(host: str = '127.0.0.1', start_port: int = 8999, max_attempts: int = 20) -> int:
    """自动探测可用端口"""
    if host in ('127.0.0.1', 'localhost'):
        kill_process_on_port(start_port)
    for p in range(start_port, start_port + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((host, p))
                return p
            except OSError:
                continue
    return start_port


def open_browser_delayed(url: str, delay_seconds: float = 0.6):
    """延迟并在后台自动打开默认浏览器"""
    def _open():
        time.sleep(delay_seconds)
        try:
            webbrowser.open(url)
        except Exception:
            pass
    threading.Thread(target=_open, daemon=True).start()


def parse_args():
    parser = argparse.ArgumentParser(description="AI Agent 会话管理中心 (Agent Session Manager)")
    parser.add_argument("port_positional", nargs="?", type=int, default=None, help="服务端口 (位置参数，兼容旧写法)")
    parser.add_argument("--host", type=str, default=os.environ.get("HOST", "127.0.0.1"), help="监听地址 (默认: 127.0.0.1 或 环境变量 HOST)")
    parser.add_argument("--port", "-p", type=int, default=int(os.environ.get("PORT", 8999)), help="监听端口 (默认: 8999 或 环境变量 PORT)")
    parser.add_argument("--no-browser", action="store_true", default=bool(os.environ.get("NO_BROWSER", False)), help="启动时不自动打开浏览器 (容器环境推荐)")
    parser.add_argument("--antigravity-dir", type=str, default=None, help="Antigravity 数据存储路径 (覆盖默认或环境变量)")
    parser.add_argument("--codex-dir", type=str, default=None, help="OpenAI Codex 数据存储路径 (覆盖默认或环境变量)")
    return parser.parse_args()


def main():
    args = parse_args()

    # 处理参数优先级
    port = args.port_positional if args.port_positional is not None else args.port
    host = args.host
    no_browser = args.no_browser or os.path.exists('/.dockerenv') or host == '0.0.0.0'

    if args.antigravity_dir:
        os.environ['ANTIGRAVITY_DIR'] = args.antigravity_dir
    if args.codex_dir:
        os.environ['CODEX_DIR'] = args.codex_dir

    if port == 8999 and not os.path.exists('/.dockerenv') and host in ('127.0.0.1', 'localhost'):
        port = find_free_port(host, port)

    url_display = f"http://{'127.0.0.1' if host == '0.0.0.0' else host}:{port}"

    print("=" * 68)
    print("  🚀 AI Agent 会话管理中心 (Agent Session Manager)")
    print("=" * 68)
    print(f"  • 本地管理页面:  \033[1;34m{url_display}\033[0m")
    print(f"  • 监听网络地址:  {host}:{port}")
    print(f"  • 支持平台:      Google Antigravity & OpenAI Codex")
    print("=" * 68)
    
    if not no_browser:
        print("  ⚡ 正在自动打开浏览器...")
        open_browser_delayed(url_display)
    else:
        print("  🌐 服务已就绪，请在浏览器中访问上述地址")

    print("  💡 按 Ctrl + C 可安全停止服务")
    print("=" * 68)

    server_address = (host, port)
    ThreadingHTTPServer.allow_reuse_address = True
    httpd = ThreadingHTTPServer(server_address, UnifiedAPIHandler)
    httpd.daemon_threads = True
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n🛑 服务已安全退出。")
        httpd.server_close()


if __name__ == '__main__':
    main()
