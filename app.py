#!/usr/bin/env python3
"""
AI Agent 会话管理中心 (Agent Session Manager) - 统一启动器
执行本脚本将启动本地 Web 服务并自动打开浏览器。
"""

import os
import sys
import socket
import webbrowser
import threading
import time

# 导入服务端
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(CURRENT_DIR, 'backend'))

from server import ThreadingHTTPServer, UnifiedAPIHandler, AntigravityAPIHandler


def kill_process_on_port(port: int = 8999):
    """清理占用默认端口的历史遗留服务"""
    try:
        import subprocess
        out = subprocess.check_output(f"lsof -ti :{port}", shell=True).decode().strip()
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


def find_free_port(start_port: int = 8999, max_attempts: int = 20) -> int:
    """自动探测可用端口"""
    kill_process_on_port(start_port)
    for p in range(start_port, start_port + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(('127.0.0.1', p))
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


def main():
    port = 8999
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            pass
    else:
        port = find_free_port(port)

    url = f"http://127.0.0.1:{port}"

    print("=" * 68)
    print("  🚀 AI Agent 会话管理中心 (Agent Session Manager)")
    print("=" * 68)
    print(f"  • 本地管理页面:  \033[1;34m{url}\033[0m")
    print(f"  • 支持平台:      Google Antigravity & OpenAI Codex")
    print("=" * 68)
    print("  ⚡ 正在自动打开浏览器...")
    print("  💡 按 Ctrl + C 可安全停止服务")
    print("=" * 68)

    open_browser_delayed(url)

    server_address = ('127.0.0.1', port)
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
