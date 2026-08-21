# ==========================================
# AI Agent 会话管理中心 (Agent Session Manager)
# 基于 Python 3.12 官方极简镜像 (纯标准库，零三方依赖)
# ==========================================

FROM python:3.12-alpine

LABEL maintainer="dazhangwei" \
      description="A lightweight, zero-dependency local session manager & workspace cleaner for AI Coding Agents." \
      version="1.0.0"

# 设置工作目录
WORKDIR /app

# 设置环境变量默认值 (支持运行时通过 -e 或 run 参数覆盖)
ENV PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=8999 \
    NO_BROWSER=1 \
    ANTIGRAVITY_DIR=/root/.gemini/antigravity \
    CODEX_DIR=/root/.codex

# 复制工程源码
COPY app.py ./
COPY backend/ ./backend/
COPY frontend/ ./frontend/
COPY LICENSE README.md ./

# 声明持久化数据卷挂载点
VOLUME ["/root/.gemini/antigravity", "/root/.codex"]

# 暴露服务端口
EXPOSE 8999

# 健康检查
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD python3 -c "import urllib.request, os; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('PORT', '8999'))" || exit 1

# 启动入口 (支持追加 CLI 参数如 --port 9000 等)
ENTRYPOINT ["python3", "app.py"]
