"""
Antigravity + OpenAI Codex 统一会话管理本地 Web API 服务端
基于 Python 3 内置 http.server，无需安装任何额外三方包。
"""

import os
import sys
import json
import urllib.parse
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from typing import Dict, Any, List

# 确保能引入同目录模块
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, CURRENT_DIR)

from storage_parser import AntigravityStorage, format_bytes
from trash_manager import TrashManager
from codex_parser import CodexStorage

FRONTEND_DIR = os.path.abspath(os.path.join(CURRENT_DIR, '..', 'frontend'))
CURRENT_CONVERSATION_ID = os.environ.get('ACTIVE_SESSION_ID', '')


class UnifiedAPIHandler(BaseHTTPRequestHandler):
    agy_storage = AntigravityStorage()
    agy_trash = TrashManager()
    codex_storage = CodexStorage()

    def _set_headers(self, status: int = 200, content_type: str = 'application/json; charset=utf-8'):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
        self.end_headers()

    def do_OPTIONS(self):
        self._set_headers(200)

    def _send_json(self, data: Any, status: int = 200):
        self._set_headers(status, 'application/json; charset=utf-8')
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))

    def _read_json_body(self) -> Dict[str, Any]:
        try:
            length = int(self.headers.get('Content-Length', 0))
            if length == 0:
                return {}
            body = self.rfile.read(length).decode('utf-8')
            return json.loads(body)
        except Exception:
            return {}

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)
        platform_req = query.get('platform', ['all'])[0].lower()

        # 1. API: 获取会话列表与工程分组
        if path == '/api/conversations':
            try:
                agy_convs = []
                codex_convs = []

                if platform_req in ('all', 'antigravity'):
                    agy_raw = self.agy_storage.get_all_conversations()
                    for c in agy_raw:
                        c['platform'] = 'antigravity'
                        agy_convs.append(c)

                if platform_req in ('all', 'codex'):
                    codex_convs = self.codex_storage.get_all_conversations()

                all_convs = agy_convs + codex_convs
                all_convs.sort(key=lambda x: x.get('updated_ts') or 0, reverse=True)

                # 统计工程数据
                project_map = {}
                total_bytes = 0
                for c in all_convs:
                    p = c.get('project', '未分类 / 全局会话')
                    size = c.get('total_size', 0)
                    total_bytes += size
                    if p not in project_map:
                        project_map[p] = {
                            'name': p,
                            'count': 0,
                            'total_size': 0,
                            'platforms': set(),
                            'workspaces': set()
                        }
                    project_map[p]['count'] += 1
                    project_map[p]['total_size'] += size
                    project_map[p]['platforms'].add(c.get('platform', 'antigravity'))
                    ws = c.get('primary_workspace')
                    if ws:
                        project_map[p]['workspaces'].add(ws)

                projects_list = []
                for p, pdata in project_map.items():
                    projects_list.append({
                        'name': p,
                        'count': pdata['count'],
                        'total_size': pdata['total_size'],
                        'total_size_str': format_bytes(pdata['total_size']),
                        'platforms': list(pdata['platforms']),
                        'workspaces': list(pdata['workspaces'])
                    })

                projects_list.sort(key=lambda x: x['count'], reverse=True)

                # 统计回收站
                agy_trash_items = self.agy_trash.list_trash()
                codex_trash_items = self.codex_storage.list_trash()
                all_trash = agy_trash_items + codex_trash_items
                trash_total_bytes = sum(item.get('total_size', 0) for item in all_trash)

                self._send_json({
                    'success': True,
                    'platform': platform_req,
                    'conversations': all_convs,
                    'projects': projects_list,
                    'active_session_id': CURRENT_CONVERSATION_ID,
                    'platform_counts': {
                        'antigravity': len(self.agy_storage.get_all_conversations()),
                        'codex': len(self.codex_storage.get_all_conversations()),
                        'all': len(all_convs)
                    },
                    'stats': {
                        'total_conversations': len(all_convs),
                        'total_size': total_bytes,
                        'total_size_str': format_bytes(total_bytes),
                        'total_projects': len(projects_list),
                        'trash_count': len(all_trash),
                        'trash_size': trash_total_bytes,
                        'trash_size_str': format_bytes(trash_total_bytes)
                    }
                })
            except Exception as e:
                self._send_json({'success': False, 'error': str(e)}, status=500)
            return

        # 2. API: 获取单个会话详情与对话记录
        elif path.startswith('/api/conversation/'):
            cid = path[len('/api/conversation/'):].strip()
            if not cid:
                self._send_json({'success': False, 'error': 'Missing conversation ID'}, status=400)
                return
            try:
                details = None
                if platform_req == 'codex':
                    details = self.codex_storage.get_conversation_details(cid)
                elif platform_req == 'antigravity':
                    details = self.agy_storage.get_conversation_details(cid)
                else:
                    # 未显式指定平台时，优先查找包含实际对话轮次的引擎
                    codex_det = self.codex_storage.get_conversation_details(cid)
                    if codex_det and codex_det.get('turns_count', 0) > 0:
                        details = codex_det
                    else:
                        agy_det = self.agy_storage.get_conversation_details(cid)
                        if agy_det and (agy_det.get('turns_count', 0) > 0 or agy_det.get('artifacts')):
                            details = agy_det
                        else:
                            details = codex_det or agy_det

                if details:
                    self._send_json({'success': True, 'data': details})
                else:
                    self._send_json({'success': False, 'error': 'Conversation not found'}, status=404)
            except Exception as e:
                self._send_json({'success': False, 'error': str(e)}, status=500)
            return

        # 3. API: 获取回收站列表
        elif path == '/api/trash':
            try:
                agy_trash_items = self.agy_trash.list_trash()
                for item in agy_trash_items:
                    item['platform'] = 'antigravity'
                codex_trash_items = self.codex_storage.list_trash()
                for item in codex_trash_items:
                    item['platform'] = 'codex'

                all_trash = agy_trash_items + codex_trash_items
                all_trash.sort(key=lambda x: x.get('deleted_ts') or 0, reverse=True)
                total_trash_size = sum(t.get('total_size', 0) for t in all_trash)

                self._send_json({
                    'success': True,
                    'items': all_trash,
                    'count': len(all_trash),
                    'total_size': total_trash_size,
                    'total_size_str': format_bytes(total_trash_size)
                })
            except Exception as e:
                self._send_json({'success': False, 'error': str(e)}, status=500)
            return

        # 4. API: 导出单个会话 Markdown
        elif path.startswith('/api/export/markdown/'):
            cid = path[len('/api/export/markdown/'):].strip()
            try:
                md_content = None
                if platform_req == 'codex':
                    md_content = self.codex_storage.export_conversation_markdown(cid)
                elif platform_req == 'antigravity':
                    md_content = self.agy_storage.export_conversation_markdown(cid)
                else:
                    codex_md = self.codex_storage.export_conversation_markdown(cid)
                    if codex_md and "无可用数据" not in codex_md:
                        md_content = codex_md
                    else:
                        md_content = self.agy_storage.export_conversation_markdown(cid)

                if not md_content:
                    md_content = f"# 会话 {cid} (无可用数据)\n"

                self._set_headers(200, 'text/markdown; charset=utf-8')
                self.send_header('Content-Disposition', f'attachment; filename="chat_export_{cid[:8]}.md"')
                self.wfile.write(md_content.encode('utf-8'))
            except Exception as e:
                self._send_json({'success': False, 'error': str(e)}, status=500)
            return

        # 5. 静态文件前端页面响应
        else:
            file_path = path.lstrip('/')
            if not file_path or file_path == 'index.html':
                full_path = os.path.join(FRONTEND_DIR, 'index.html')
                content_type = 'text/html; charset=utf-8'
            else:
                full_path = os.path.join(FRONTEND_DIR, file_path)
                if full_path.endswith('.css'):
                    content_type = 'text/css; charset=utf-8'
                elif full_path.endswith('.js'):
                    content_type = 'application/javascript; charset=utf-8'
                elif full_path.endswith('.png'):
                    content_type = 'image/png'
                elif full_path.endswith('.svg'):
                    content_type = 'image/svg+xml'
                else:
                    content_type = 'text/plain; charset=utf-8'

            if os.path.exists(full_path) and os.path.isfile(full_path):
                self._set_headers(200, content_type)
                with open(full_path, 'rb') as f:
                    self.wfile.write(f.read())
            else:
                fallback = os.path.join(FRONTEND_DIR, 'index.html')
                if os.path.exists(fallback):
                    self._set_headers(200, 'text/html; charset=utf-8')
                    with open(fallback, 'rb') as f:
                        self.wfile.write(f.read())
                else:
                    self._set_headers(404, 'text/plain; charset=utf-8')
                    self.wfile.write(b'404 Not Found')

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        data = self._read_json_body()

        # 1. 批量移入回收站
        if path == '/api/conversations/delete':
            cids = data.get('cids', [])
            items_meta = data.get('items', []) # [{'id': '...', 'platform': '...'}]
            if not cids and not items_meta:
                self._send_json({'success': False, 'error': '未提供需要删除的会话列表'}, status=400)
                return

            try:
                # 分流处理
                agy_cids = []
                codex_cids = []

                if items_meta:
                    for item in items_meta:
                        if item.get('platform') == 'codex':
                            codex_cids.append(item.get('id'))
                        else:
                            agy_cids.append(item.get('id'))
                else:
                    # 如果只有 cids，查表区分
                    codex_all = {c['id'] for c in self.codex_storage.get_all_conversations()}
                    for cid in cids:
                        if cid in codex_all:
                            codex_cids.append(cid)
                        else:
                            agy_cids.append(cid)

                total_moved = 0
                total_freed = 0
                if agy_cids:
                    res1 = self.agy_trash.move_to_trash(agy_cids)
                    total_moved += res1.get('count', 0)
                    total_freed += res1.get('freed_bytes', 0)

                if codex_cids:
                    res2 = self.codex_storage.move_to_trash(codex_cids)
                    total_moved += res2.get('count', 0)
                    total_freed += res2.get('freed_bytes', 0)

                self._send_json({
                    'success': True,
                    'count': total_moved,
                    'freed_bytes': total_freed,
                    'freed_str': format_bytes(total_freed),
                    'message': f"成功移入回收站 {total_moved} 场会话"
                })
            except Exception as e:
                self._send_json({'success': False, 'error': str(e)}, status=500)
            return

        # 2. 回收站一键还原
        elif path == '/api/trash/restore':
            trash_keys = data.get('trash_keys', [])
            if not trash_keys:
                self._send_json({'success': False, 'error': '未提供还原项'}, status=400)
                return
            try:
                agy_keys = [k for k in trash_keys if not k.startswith('codex_')]
                codex_keys = [k for k in trash_keys if k.startswith('codex_')]

                restored = 0
                if agy_keys:
                    r1 = self.agy_trash.restore_from_trash(agy_keys)
                    restored += r1.get('count', 0)
                if codex_keys:
                    r2 = self.codex_storage.restore_from_trash(codex_keys)
                    restored += r2.get('count', 0)

                self._send_json({'success': True, 'count': restored, 'message': f"成功还原 {restored} 个会话"})
            except Exception as e:
                self._send_json({'success': False, 'error': str(e)}, status=500)
            return

        # 3. 彻底粉碎删除
        elif path == '/api/trash/purge':
            trash_keys = data.get('trash_keys', [])
            try:
                agy_keys = [k for k in trash_keys if not k.startswith('codex_')]
                codex_keys = [k for k in trash_keys if k.startswith('codex_')]

                purged = 0
                freed = 0
                if agy_keys:
                    p1 = self.agy_trash.permanent_delete(agy_keys)
                    purged += p1.get('count', 0)
                    freed += p1.get('freed_bytes', 0)
                if codex_keys:
                    p2 = self.codex_storage.permanent_delete(codex_keys)
                    purged += p2.get('count', 0)
                    freed += p2.get('freed_bytes', 0)

                self._send_json({
                    'success': True,
                    'count': purged,
                    'freed_bytes': freed,
                    'freed_str': format_bytes(freed),
                    'message': f"彻底粉碎 {purged} 场会话"
                })
            except Exception as e:
                self._send_json({'success': False, 'error': str(e)}, status=500)
            return

        # 4. 批量导出 Markdown
        elif path == '/api/conversations/export':
            cids = data.get('cids', [])
            if not cids:
                self._send_json({'success': False, 'error': '未选择要导出的会话'}, status=400)
                return
            try:
                exported_parts = []
                codex_all = {c['id'] for c in self.codex_storage.get_all_conversations()}
                for cid in cids:
                    if cid in codex_all:
                        exported_parts.append(self.codex_storage.export_conversation_markdown(cid))
                    else:
                        exported_parts.append(self.agy_storage.export_conversation_markdown(cid))

                combined = "\n\n" + ("=" * 80) + "\n\n".join(exported_parts)
                self._send_json({'success': True, 'content': combined, 'count': len(cids)})
            except Exception as e:
                self._send_json({'success': False, 'error': str(e)}, status=500)
            return

        else:
            self._send_json({'success': False, 'error': f'Endpoint {path} not found'}, status=404)


AntigravityAPIHandler = UnifiedAPIHandler


def run_server(port: int = 8999, host: str = '127.0.0.1'):
    server_address = (host, port)
    ThreadingHTTPServer.allow_reuse_address = True
    httpd = ThreadingHTTPServer(server_address, UnifiedAPIHandler)
    httpd.daemon_threads = True
    print(f"🚀 Antigravity + Codex 统一会话管理服务已启动: http://{host}:{port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n🛑 服务已停止")
        httpd.server_close()


if __name__ == '__main__':
    port = 8999
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            pass
    run_server(port)
