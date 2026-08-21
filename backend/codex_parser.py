"""
OpenAI Codex 会话数据存储与解析引擎
支持：
- 跨平台精准识别 Codex 侧边栏的实际工作区项目与最近会话
- 纯净的人类可读对话流结构化解析（剥离环境配置与内部指令）
"""

import os
import sys
import json
import time
import shutil
import sqlite3
import datetime
import re
from typing import Dict, List, Any, Optional, Tuple

CODEX_DIR = os.path.expanduser('~/.codex')
STATE_DB_PATH = os.path.join(CODEX_DIR, 'state_5.sqlite')
SESSION_INDEX_PATH = os.path.join(CODEX_DIR, 'session_index.jsonl')
SESSIONS_DIR = os.path.join(CODEX_DIR, 'sessions')


def clean_human_codex_user_prompt(text: str) -> str:
    if not text:
        return ""
    # 移除 <environment_context> ... </environment_context>
    cleaned = re.sub(r'<environment_context>.*?</environment_context>', '', text, flags=re.DOTALL)
    cleaned = re.sub(r'<app-context>.*?</app-context>', '', cleaned, flags=re.DOTALL)
    cleaned = re.sub(r'<permissions instructions>.*?</permissions instructions>', '', cleaned, flags=re.DOTALL)
    cleaned = re.sub(r'<multi_agent_mode>.*?</multi_agent_mode>', '', cleaned, flags=re.DOTALL)
    return cleaned.strip()


def format_bytes(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    elif size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    elif size < 1024 * 1024 * 1024:
        return f"{size / (1024 * 1024):.2f} MB"
    else:
        return f"{size / (1024 * 1024 * 1024):.2f} GB"


def format_timestamp(ts: Optional[int]) -> Optional[str]:
    if not ts:
        return None
    try:
        if ts > 1000000000000:
            ts = ts / 1000.0
        dt = datetime.datetime.fromtimestamp(ts)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def extract_codex_project(cwd: str) -> str:
    """
    根据工作区路径通用提取 Codex 工程名称 (支持 macOS/Linux/Windows 跨平台)
    """
    if not cwd:
        return "💬 独立会话 (未关联工程)"
    clean = cwd.replace('\\', '/').rstrip('/')
    if not clean:
        return "💬 独立会话 (未关联工程)"

    # 临时目录或默认存储目录归为独立会话
    if '/Documents/Codex/' in clean or '/.codex/' in clean or '/temp/' in clean or '/tmp/' in clean:
        return "💬 独立会话 (未关联工程)"

    parts = [p for p in clean.split('/') if p and not p.startswith('.')]
    if parts:
        # 如果是常见源码子目录（如 src, lib, app, backend, frontend），向上推一级
        if len(parts) >= 2 and parts[-1].lower() in ('src', 'lib', 'frontend', 'backend', 'app', 'dist', 'build', 'docs'):
            return parts[-2]
        return parts[-1]

    return "💬 独立会话 (未关联工程)"


class CodexStorage:
    def __init__(self, base_dir: str = CODEX_DIR):
        self.base_dir = base_dir
        self.state_db = os.path.join(base_dir, 'state_5.sqlite')
        self.session_index = os.path.join(base_dir, 'session_index.jsonl')
        self.sessions_dir = os.path.join(base_dir, 'sessions')
        self.trash_dir = os.path.join(base_dir, 'trash')
        os.makedirs(self.trash_dir, exist_ok=True)

    def get_all_conversations(self) -> List[Dict[str, Any]]:
        if not os.path.exists(self.state_db):
            return []

        conversations = []
        try:
            conn = sqlite3.connect(self.state_db)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("""
                SELECT id, title, cwd, rollout_path, created_at, updated_at, 
                       created_at_ms, updated_at_ms, first_user_message, model, tokens_used, archived
                FROM threads
            """)
            rows = cur.fetchall()

            for r in rows:
                cid = r['id']
                title = r['title'] or ''
                cwd = r['cwd'] or ''
                rollout_path = r['rollout_path'] or ''
                first_msg = clean_human_codex_user_prompt(r['first_user_message'] or '')
                model = r['model'] or ''
                tokens_used = r['tokens_used'] or 0

                created_ts = r['created_at']
                updated_ts = r['updated_at']

                rollout_size = 0
                has_rollout = False
                if rollout_path and os.path.exists(rollout_path):
                    has_rollout = True
                    try:
                        rollout_size = os.path.getsize(rollout_path)
                    except Exception:
                        pass

                if not title:
                    title = first_msg[:50] if first_msg else f"Codex 会话 ({cid[:8]})"

                proj_name = extract_codex_project(cwd)

                conversations.append({
                    'id': cid,
                    'platform': 'codex',
                    'title': title,
                    'project': proj_name,
                    'primary_workspace': cwd,
                    'workspaces': [cwd] if cwd else [],
                    'first_prompt': first_msg,
                    'last_message': '',
                    'model': model,
                    'tokens_used': tokens_used,
                    'msg_count': 0,
                    'created_ts': created_ts,
                    'updated_ts': updated_ts or created_ts,
                    'created_time_str': format_timestamp(created_ts),
                    'updated_time_str': format_timestamp(updated_ts or created_ts),
                    'total_size': rollout_size,
                    'total_size_str': format_bytes(rollout_size),
                    'rollout_path': rollout_path,
                    'has_rollout': has_rollout,
                    'in_pb': False
                })
            conn.close()
        except Exception as e:
            print(f"[Error] Reading Codex database: {e}", file=sys.stderr)

        conversations.sort(key=lambda x: x.get('updated_ts') or 0, reverse=True)
        return conversations

    def get_conversation_details(self, cid: str) -> Optional[Dict[str, Any]]:
        convs = {c['id']: c for c in self.get_all_conversations()}
        conv = convs.get(cid)
        if not conv:
            return None

        rollout_path = conv.get('rollout_path')
        chat_turns = []

        if rollout_path and os.path.exists(rollout_path):
            try:
                with open(rollout_path, 'r', encoding='utf-8', errors='ignore') as f:
                    current_assistant_turn = None

                    for line in f:
                        if not line.strip():
                            continue
                        try:
                            obj = json.loads(line)
                            mtype = obj.get('type')
                            payload = obj.get('payload', {})
                            ts = obj.get('timestamp', '')
                            time_str = ts.replace('T', ' ').replace('Z', '')[:19]

                            if mtype == 'response_item':
                                role = payload.get('role')
                                content_list = payload.get('content', [])

                                # 用户输入
                                if role == 'user':
                                    if current_assistant_turn:
                                        chat_turns.append(current_assistant_turn)
                                        current_assistant_turn = None

                                    text_parts = []
                                    for c in content_list:
                                        if isinstance(c, dict) and c.get('text'):
                                            text_parts.append(c.get('text'))
                                    raw_text = "\n".join(text_parts).strip()
                                    clean_text = clean_human_codex_user_prompt(raw_text)
                                    if clean_text:
                                        chat_turns.append({
                                            'role': 'user',
                                            'type': 'USER_INPUT',
                                            'time_str': time_str,
                                            'text': clean_text,
                                            'tool_calls': []
                                        })

                                # 助手回答
                                elif role == 'assistant':
                                    if not current_assistant_turn:
                                        current_assistant_turn = {
                                            'role': 'assistant',
                                            'type': 'PLANNER_RESPONSE',
                                            'time_str': time_str,
                                            'text': '',
                                            'tool_calls': []
                                        }

                                    for c in content_list:
                                        if isinstance(c, dict):
                                            if c.get('text'):
                                                t = c.get('text').strip()
                                                if current_assistant_turn['text']:
                                                    current_assistant_turn['text'] += "\n\n" + t
                                                else:
                                                    current_assistant_turn['text'] = t
                                            elif c.get('type') == 'tool_call':
                                                current_assistant_turn['tool_calls'].append({
                                                    'name': c.get('name', 'tool'),
                                                    'action': c.get('name'),
                                                    'args': c.get('arguments', {})
                                                })

                            elif mtype == 'event_msg':
                                etype = payload.get('type')
                                if etype == 'tool_called':
                                    if not current_assistant_turn:
                                        current_assistant_turn = {
                                            'role': 'assistant',
                                            'type': 'PLANNER_RESPONSE',
                                            'time_str': time_str,
                                            'text': '',
                                            'tool_calls': []
                                        }
                                    tname = payload.get('tool_name', 'tool')
                                    current_assistant_turn['tool_calls'].append({
                                        'name': tname,
                                        'action': tname,
                                        'args': payload.get('arguments', {})
                                    })

                        except Exception:
                            pass

                    if current_assistant_turn:
                        chat_turns.append(current_assistant_turn)

            except Exception as e:
                print(f"[Error] Reading Codex rollout {rollout_path}: {e}", file=sys.stderr)

        return {
            'id': cid,
            'platform': 'codex',
            'title': conv.get('title'),
            'turns_count': len(chat_turns),
            'turns': chat_turns,
            'artifacts': []
        }

    def export_conversation_markdown(self, cid: str) -> str:
        details = self.get_conversation_details(cid)
        if not details:
            return f"# Codex 会话 {cid} (无可用数据)\n"

        lines = [f"# Codex 会话导出: {details.get('title', cid)}\n", f"导出时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n---\n"]
        for turn in details.get('turns', []):
            role = turn.get('role')
            time_str = turn.get('time_str', '')
            text = turn.get('text', '')
            tool_calls = turn.get('tool_calls', [])

            if role == 'user':
                lines.append(f"### 👤 用户 ({time_str})\n\n{text}\n\n")
            else:
                lines.append(f"### 🤖 Codex 助手 ({time_str})\n\n")
                if tool_calls:
                    lines.append(f"**⚡ 执行了 {len(tool_calls)} 个操作:**\n")
                    for tc in tool_calls:
                        lines.append(f"- `{tc.get('name')}`\n")
                    lines.append("\n")
                lines.append(f"{text}\n\n")
            lines.append("---\n\n")
        return "".join(lines)

    def move_to_trash(self, cids: List[str]) -> Dict[str, Any]:
        if not cids:
            return {'success': True, 'count': 0, 'message': '未选择任何会话'}

        ts = int(time.time())
        moved_count = 0
        total_freed = 0
        details = []

        try:
            conn = sqlite3.connect(self.state_db)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()

            bak_db = f"{self.state_db}.bak.{ts}"
            shutil.copy2(self.state_db, bak_db)

            if os.path.exists(self.session_index):
                shutil.copy2(self.session_index, f"{self.session_index}.bak.{ts}")

            for cid in cids:
                cur.execute("SELECT * FROM threads WHERE id = ?", (cid,))
                row = cur.fetchone()
                if not row:
                    continue

                row_dict = dict(row)
                trash_item_name = f"codex_{cid}_{ts}"
                trash_item_dir = os.path.join(self.trash_dir, trash_item_name)
                os.makedirs(trash_item_dir, exist_ok=True)

                rollout_p = row_dict.get('rollout_path')
                item_freed = 0
                moved_files = []

                if rollout_p and os.path.exists(rollout_p):
                    try:
                        fsize = os.path.getsize(rollout_p)
                        item_freed += fsize
                        dest = os.path.join(trash_item_dir, os.path.basename(rollout_p))
                        shutil.move(rollout_p, dest)
                        moved_files.append({'type': 'rollout', 'original': rollout_p, 'trash': dest})
                    except Exception as e:
                        print(f"[Warn] Move rollout {cid}: {e}", file=sys.stderr)

                manifest = {
                    'id': cid,
                    'platform': 'codex',
                    'trash_key': trash_item_name,
                    'title': row_dict.get('title') or f"Codex 会话 {cid[:8]}",
                    'project': extract_codex_project(row_dict.get('cwd')),
                    'deleted_ts': ts,
                    'deleted_time_str': format_timestamp(ts),
                    'total_size': item_freed,
                    'total_size_str': format_bytes(item_freed),
                    'thread_row': row_dict,
                    'moved_files': moved_files
                }

                with open(os.path.join(trash_item_dir, 'manifest.json'), 'w', encoding='utf-8') as mf:
                    json.dump(manifest, mf, ensure_ascii=False, indent=2)

                cur.execute("DELETE FROM threads WHERE id = ?", (cid,))
                moved_count += 1
                total_freed += item_freed
                details.append(manifest)

            conn.commit()
            conn.close()

            if os.path.exists(self.session_index):
                with open(self.session_index, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                new_lines = []
                cids_set = set(cids)
                for l in lines:
                    if l.strip():
                        try:
                            obj = json.loads(l)
                            if obj.get('id') not in cids_set:
                                new_lines.append(l)
                        except Exception:
                            new_lines.append(l)
                with open(self.session_index, 'w', encoding='utf-8') as f:
                    f.writelines(new_lines)

            return {
                'success': True,
                'count': moved_count,
                'freed_bytes': total_freed,
                'freed_str': format_bytes(total_freed),
                'message': f"成功将 {moved_count} 个 Codex 会话移入回收站"
            }
        except Exception as e:
            return {'success': False, 'error': f"删除 Codex 会话失败: {e}"}

    def list_trash(self) -> List[Dict[str, Any]]:
        items = []
        if not os.path.exists(self.trash_dir):
            return items

        for d in os.listdir(self.trash_dir):
            item_dir = os.path.join(self.trash_dir, d)
            if not os.path.isdir(item_dir):
                continue
            manifest_file = os.path.join(item_dir, 'manifest.json')
            if os.path.exists(manifest_file):
                try:
                    with open(manifest_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        items.append(data)
                except Exception:
                    pass
        items.sort(key=lambda x: x.get('deleted_ts') or 0, reverse=True)
        return items

    def restore_from_trash(self, trash_keys: List[str]) -> Dict[str, Any]:
        if not trash_keys:
            return {'success': True, 'count': 0, 'message': '未选择还原项'}

        restored_count = 0
        try:
            conn = sqlite3.connect(self.state_db)
            cur = conn.cursor()

            for tkey in trash_keys:
                item_dir = os.path.join(self.trash_dir, tkey)
                manifest_file = os.path.join(item_dir, 'manifest.json')
                if not os.path.exists(manifest_file):
                    continue

                with open(manifest_file, 'r', encoding='utf-8') as f:
                    manifest = json.load(f)

                for mf in manifest.get('moved_files', []):
                    tf = mf.get('trash')
                    orig = mf.get('original')
                    if tf and orig and os.path.exists(tf):
                        os.makedirs(os.path.dirname(orig), exist_ok=True)
                        shutil.move(tf, orig)

                trow = manifest.get('thread_row')
                if trow:
                    cols = list(trow.keys())
                    placeholders = ','.join(['?'] * len(cols))
                    sql = f"INSERT OR REPLACE INTO threads ({','.join(cols)}) VALUES ({placeholders})"
                    cur.execute(sql, [trow[c] for c in cols])

                shutil.rmtree(item_dir)
                restored_count += 1

            conn.commit()
            conn.close()
            return {'success': True, 'count': restored_count, 'message': f"成功还原 {restored_count} 个 Codex 会话"}
        except Exception as e:
            return {'success': False, 'error': f"还原 Codex 会话失败: {e}"}

    def permanent_delete(self, trash_keys: List[str]) -> Dict[str, Any]:
        deleted_count = 0
        total_freed = 0
        for tkey in trash_keys:
            item_dir = os.path.join(self.trash_dir, tkey)
            if os.path.exists(item_dir):
                size = 0
                for root, _, files in os.walk(item_dir):
                    for f in files:
                        size += os.path.getsize(os.path.join(root, f))
                try:
                    shutil.rmtree(item_dir)
                    deleted_count += 1
                    total_freed += size
                except Exception:
                    pass
        return {
            'success': True,
            'count': deleted_count,
            'freed_bytes': total_freed,
            'freed_str': format_bytes(total_freed),
            'message': f"彻底粉碎 {deleted_count} 个 Codex 会话"
        }
