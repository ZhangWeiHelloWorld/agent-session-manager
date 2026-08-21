"""
Antigravity 会话数据存储与解析引擎
支持：
- Protobuf Wire 格式的高性能无损解码与回写
- SQLite 对话元数据与轨迹解析
- 精确工程归类（与 Antigravity 侧边栏保持 100% 一致）
- Human-Readable 人类可读对话流清洗与工件解析
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

ANTIGRAVITY_DIR = os.environ.get('ANTIGRAVITY_DIR') or os.path.expanduser('~/.gemini/antigravity')
PB_PATH = os.path.join(ANTIGRAVITY_DIR, 'agyhub_summaries_proto.pb')
CONV_DIR = os.path.join(ANTIGRAVITY_DIR, 'conversations')
BRAIN_DIR = os.path.join(ANTIGRAVITY_DIR, 'brain')
ANNOTATIONS_DIR = os.path.join(ANTIGRAVITY_DIR, 'annotations')
BACKUPS_DIR = os.path.join(ANTIGRAVITY_DIR, 'backups')


# ==========================================
# 1. 纯 Python Protobuf Wire 编解码器
# ==========================================

def decode_varint(data: bytes, idx: int) -> Tuple[int, int]:
    val = 0
    shift = 0
    while True:
        if idx >= len(data):
            break
        b = data[idx]
        idx += 1
        val |= (b & 0x7F) << shift
        shift += 7
        if not (b & 0x80):
            break
    return val, idx


def encode_varint(val: int) -> bytes:
    res = bytearray()
    while True:
        b = val & 0x7F
        val >>= 7
        if val:
            res.append(b | 0x80)
        else:
            res.append(b)
            break
    return bytes(res)


def parse_protobuf_wire(data: bytes) -> List[Tuple[int, int, Any]]:
    idx = 0
    items = []
    length_data = len(data)
    while idx < length_data:
        key, idx = decode_varint(data, idx)
        field_num = key >> 3
        wire_type = key & 0x7

        if wire_type == 0:
            val, idx = decode_varint(data, idx)
            items.append((field_num, wire_type, val))
        elif wire_type == 2:
            length, idx = decode_varint(data, idx)
            val_bytes = data[idx:idx + length]
            idx += length
            items.append((field_num, wire_type, val_bytes))
        elif wire_type == 1:
            val_bytes = data[idx:idx + 8]
            idx += 8
            items.append((field_num, wire_type, val_bytes))
        elif wire_type == 5:
            val_bytes = data[idx:idx + 4]
            idx += 4
            items.append((field_num, wire_type, val_bytes))
        else:
            break
    return items


def serialize_protobuf_records(records: List[Tuple[int, int, Any]]) -> bytes:
    out = bytearray()
    for field_num, wire_type, val in records:
        key = (field_num << 3) | wire_type
        out.extend(encode_varint(key))
        if wire_type == 0:
            out.extend(encode_varint(val))
        elif wire_type == 2:
            out.extend(encode_varint(len(val)))
            out.extend(val)
        elif wire_type in (1, 5):
            out.extend(val)
    return bytes(out)


# ==========================================
# 2. 文本清洗与人类可读格式化
# ==========================================

def clean_human_user_prompt(content: str) -> str:
    """提取纯净的用户实际输入内容，剥离系统上下文 XML 标签"""
    if not content:
        return ""
    # 如果包含 <USER_REQUEST>
    if '<USER_REQUEST>' in content:
        parts = re.findall(r'<USER_REQUEST>(.*?)</USER_REQUEST>', content, re.DOTALL)
        if parts:
            return parts[0].strip()
    # 移除各类元数据标签
    cleaned = re.sub(r'<ADDITIONAL_METADATA>.*?</ADDITIONAL_METADATA>', '', content, flags=re.DOTALL)
    cleaned = re.sub(r'<USER_SETTINGS_CHANGE>.*?</USER_SETTINGS_CHANGE>', '', cleaned, flags=re.DOTALL)
    cleaned = re.sub(r'<SYSTEM_MESSAGE>.*?</SYSTEM_MESSAGE>', '', cleaned, flags=re.DOTALL)
    cleaned = re.sub(r'<user_information>.*?</user_information>', '', cleaned, flags=re.DOTALL)
    cleaned = re.sub(r'<environment_context>.*?</environment_context>', '', cleaned, flags=re.DOTALL)
    cleaned = re.sub(r'<permissions instructions>.*?</permissions instructions>', '', cleaned, flags=re.DOTALL)
    cleaned = re.sub(r'<multi_agent_mode>.*?</multi_agent_mode>', '', cleaned, flags=re.DOTALL)
    return cleaned.strip()


def get_dir_size(path: str) -> int:
    if not os.path.exists(path):
        return 0
    if os.path.isfile(path):
        return os.path.getsize(path)
    total = 0
    try:
        for root, _, files in os.walk(path):
            for f in files:
                fp = os.path.join(root, f)
                if not os.path.islink(fp):
                    try:
                        total += os.path.getsize(fp)
                    except OSError:
                        pass
    except OSError:
        pass
    return total


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


def extract_project_name(path: str) -> str:
    """
    根据路径通用提取项目/工程名称 (支持 macOS/Linux/Windows 跨平台)
    """
    if not path:
        return "💬 独立会话 (未关联工程)"
    clean = path.strip("\"' ")
    if clean.startswith("file://"):
        clean = clean[7:]
    clean = clean.replace('\\', '/').rstrip('/')
    if not clean:
        return "💬 独立会话 (未关联工程)"

    # 过滤系统内部和临时缓存目录
    if any(k in clean for k in ['/.gemini/', '/brain/', '/.system_generated/', '/scratch/', '/.tmp/', '/temp/']):
        return "💬 独立会话 (未关联工程)"

    parts = [p for p in clean.split('/') if p and not p.startswith('.')]
    if parts:
        # 如果是常见源码子目录（如 src, lib, app, backend, frontend），向上推一级作为工程名
        if len(parts) >= 2 and parts[-1].lower() in ('src', 'lib', 'frontend', 'backend', 'app', 'dist', 'build', 'docs'):
            return parts[-2]
        return parts[-1]

    return "💬 独立会话 (未关联工程)"


# ==========================================
# 3. 核心会话扫描与聚合
# ==========================================

class AntigravityStorage:
    def __init__(self, base_dir: str = ANTIGRAVITY_DIR):
        self.base_dir = base_dir
        self.pb_path = os.path.join(base_dir, 'agyhub_summaries_proto.pb')
        self.conv_dir = os.path.join(base_dir, 'conversations')
        self.brain_dir = os.path.join(base_dir, 'brain')
        self.annotations_dir = os.path.join(base_dir, 'annotations')
        self.backups_dir = os.path.join(base_dir, 'backups')
        os.makedirs(self.backups_dir, exist_ok=True)

    def load_pb_summaries(self) -> Dict[str, Dict[str, Any]]:
        pb_map = {}
        if not os.path.exists(self.pb_path):
            return pb_map

        try:
            with open(self.pb_path, 'rb') as f:
                pb_data = f.read()

            records = parse_protobuf_wire(pb_data)
            for field_num, wire_type, rec_bytes in records:
                if field_num == 1 and isinstance(rec_bytes, bytes):
                    rec_fields = parse_protobuf_wire(rec_bytes)
                    cid = None
                    title = ''
                    msg_count = 0
                    created_ts = None
                    updated_ts = None
                    workspaces = []

                    for fn, wt, fval in rec_fields:
                        if fn == 1 and isinstance(fval, bytes):
                            cid = fval.decode('utf-8', errors='ignore')
                        elif fn == 2 and isinstance(fval, bytes):
                            meta_fields = parse_protobuf_wire(fval)
                            for mfn, mwt, mval in meta_fields:
                                if mfn == 1 and isinstance(mval, bytes):
                                    title = mval.decode('utf-8', errors='ignore')
                                elif mfn == 2 and mwt == 0:
                                    msg_count = mval
                                elif mfn in (3, 7, 10, 15) and isinstance(mval, bytes):
                                    ts_sub = parse_protobuf_wire(mval)
                                    for tfn, twt, tval in ts_sub:
                                        if tfn == 1 and twt == 0:
                                            if mfn in (3, 7):
                                                if not created_ts or tval < created_ts:
                                                    created_ts = tval
                                            if mfn in (10, 15):
                                                if not updated_ts or tval > updated_ts:
                                                    updated_ts = tval
                                elif mfn == 17 and isinstance(mval, bytes):
                                    ws_sub = parse_protobuf_wire(mval)
                                    for wfn, wwt, wval in ws_sub:
                                        if isinstance(wval, bytes):
                                            try:
                                                txt = wval.decode('utf-8').strip("\"' ")
                                                if txt.startswith('file://'):
                                                    clean_p = txt[7:]
                                                    if clean_p not in workspaces:
                                                        workspaces.append(clean_p)
                                                elif txt.startswith('/') and txt not in workspaces:
                                                    workspaces.append(txt)
                                            except Exception:
                                                pass
                    if cid:
                        pb_map[cid] = {
                            'title': title,
                            'msg_count': msg_count,
                            'created_ts': created_ts,
                            'updated_ts': updated_ts,
                            'workspaces': workspaces,
                            'raw_record_bytes': rec_bytes
                        }
        except Exception as e:
            print(f"[Error] Failed to load pb summaries: {e}", file=sys.stderr)
        return pb_map

    def get_all_conversations(self) -> List[Dict[str, Any]]:
        pb_map = self.load_pb_summaries()

        all_ids = set(pb_map.keys())
        if os.path.exists(self.conv_dir):
            for f in os.listdir(self.conv_dir):
                if f.endswith('.db'):
                    all_ids.add(f[:-3])
        if os.path.exists(self.brain_dir):
            for d in os.listdir(self.brain_dir):
                if os.path.isdir(os.path.join(self.brain_dir, d)):
                    all_ids.add(d)

        conversations = []

        for cid in all_ids:
            pb_info = pb_map.get(cid, {})
            title = pb_info.get('title', '')
            msg_count = pb_info.get('msg_count', 0)
            created_ts = pb_info.get('created_ts')
            updated_ts = pb_info.get('updated_ts')
            workspaces = list(pb_info.get('workspaces', []))
            in_pb = cid in pb_map

            db_file = os.path.join(self.conv_dir, f"{cid}.db")
            brain_path = os.path.join(self.brain_dir, cid)
            ann_file = os.path.join(self.annotations_dir, f"{cid}.pbtxt")

            db_size = os.path.getsize(db_file) if os.path.exists(db_file) else 0
            brain_size = get_dir_size(brain_path)
            ann_size = os.path.getsize(ann_file) if os.path.exists(ann_file) else 0
            total_size = db_size + brain_size + ann_size

            first_prompt = ""
            transcript_file = os.path.join(brain_path, '.system_generated', 'logs', 'transcript.jsonl')

            if os.path.exists(transcript_file):
                try:
                    with open(transcript_file, 'r', encoding='utf-8', errors='ignore') as tf:
                        for line in tf:
                            if line.strip():
                                try:
                                    obj = json.loads(line)
                                    if obj.get('type') == 'USER_INPUT':
                                        raw_content = obj.get('content', '')
                                        first_prompt = clean_human_user_prompt(raw_content)
                                        if not created_ts and 'created_at' in obj:
                                            try:
                                                dt = datetime.datetime.fromisoformat(obj['created_at'].replace('Z', '+00:00'))
                                                created_ts = int(dt.timestamp())
                                            except Exception:
                                                pass
                                        break
                                except Exception:
                                    pass
                except Exception:
                    pass

            if not title:
                if first_prompt:
                    title = first_prompt.replace('\n', ' ')[:60]
                else:
                    title = f"未命名会话 ({cid[:8]})"

            primary_ws = workspaces[0] if workspaces else ""
            project_name = extract_project_name(primary_ws) if primary_ws else "💬 独立会话 (未关联工程)"

            conversations.append({
                'id': cid,
                'platform': 'antigravity',
                'title': title,
                'project': project_name,
                'primary_workspace': primary_ws,
                'workspaces': workspaces,
                'first_prompt': first_prompt,
                'last_message': '',
                'msg_count': msg_count,
                'created_ts': created_ts,
                'updated_ts': updated_ts or created_ts,
                'created_time_str': format_timestamp(created_ts),
                'updated_time_str': format_timestamp(updated_ts or created_ts),
                'total_size': total_size,
                'total_size_str': format_bytes(total_size),
                'db_size': db_size,
                'brain_size': brain_size,
                'ann_size': ann_size,
                'in_pb': in_pb,
                'has_db': os.path.exists(db_file),
                'has_brain': os.path.exists(brain_path),
                'has_transcript': os.path.exists(transcript_file)
            })

        conversations.sort(key=lambda x: x.get('updated_ts') or 0, reverse=True)
        return conversations

    def get_conversation_details(self, cid: str) -> Optional[Dict[str, Any]]:
        """
        以 Antigravity 原生 Chat 交互体验构建人类可读的会话记录流
        """
        brain_path = os.path.join(self.brain_dir, cid)
        transcript_path = os.path.join(brain_path, '.system_generated', 'logs', 'transcript.jsonl')
        
        chat_turns = []
        artifacts = []

        # 扫描工件目录
        if os.path.exists(brain_path):
            try:
                for item in os.listdir(brain_path):
                    if item.startswith('.'):
                        continue
                    ipath = os.path.join(brain_path, item)
                    size = get_dir_size(ipath)
                    artifacts.append({
                        'name': item,
                        'is_dir': os.path.isdir(ipath),
                        'size': size,
                        'size_str': format_bytes(size),
                        'path': ipath
                    })
            except Exception:
                pass

        if os.path.exists(transcript_path):
            try:
                with open(transcript_path, 'r', encoding='utf-8', errors='ignore') as f:
                    current_assistant_turn = None

                    for line in f:
                        if not line.strip():
                            continue
                        try:
                            obj = json.loads(line)
                            stype = obj.get('type')
                            source = obj.get('source')
                            created_at = obj.get('created_at', '')
                            content = obj.get('content', '')
                            tool_calls = obj.get('tool_calls', [])

                            # 1. 用户输入
                            if stype == 'USER_INPUT':
                                if current_assistant_turn:
                                    chat_turns.append(current_assistant_turn)
                                    current_assistant_turn = None

                                clean_text = clean_human_user_prompt(content)
                                if clean_text:
                                    chat_turns.append({
                                        'role': 'user',
                                        'type': 'USER_INPUT',
                                        'time_str': created_at.replace('T', ' ').replace('Z', '')[:19],
                                        'text': clean_text,
                                        'tool_calls': []
                                    })

                            # 2. 助手响应与工具调用
                            elif stype == 'PLANNER_RESPONSE':
                                if not current_assistant_turn:
                                    current_assistant_turn = {
                                        'role': 'assistant',
                                        'type': 'PLANNER_RESPONSE',
                                        'time_str': created_at.replace('T', ' ').replace('Z', '')[:19],
                                        'text': '',
                                        'tool_calls': []
                                    }

                                if content:
                                    if current_assistant_turn['text']:
                                        current_assistant_turn['text'] += "\n\n" + content.strip()
                                    else:
                                        current_assistant_turn['text'] = content.strip()

                                if tool_calls:
                                    for tc in tool_calls:
                                        current_assistant_turn['tool_calls'].append({
                                            'name': tc.get('name', 'tool'),
                                            'action': tc.get('args', {}).get('toolAction', tc.get('name')),
                                            'summary': tc.get('args', {}).get('toolSummary', ''),
                                            'args': tc.get('args', {})
                                        })

                            # 3. 如果是系统检查点，不污染主界面，但记录标记
                            elif stype == 'CHECKPOINT':
                                pass

                        except Exception:
                            pass

                    if current_assistant_turn:
                        chat_turns.append(current_assistant_turn)

            except Exception as e:
                print(f"[Error] Reading transcript for {cid}: {e}", file=sys.stderr)

        return {
            'id': cid,
            'platform': 'antigravity',
            'turns_count': len(chat_turns),
            'turns': chat_turns,
            'artifacts': artifacts
        }

    def export_conversation_markdown(self, cid: str) -> str:
        details = self.get_conversation_details(cid)
        if not details:
            return f"# Antigravity 会话 {cid} (无可用数据)\n"

        lines = [f"# Antigravity 会话导出: {cid}\n", f"导出时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n---\n"]
        for turn in details.get('turns', []):
            role = turn.get('role')
            time_str = turn.get('time_str', '')
            text = turn.get('text', '')
            tool_calls = turn.get('tool_calls', [])

            if role == 'user':
                lines.append(f"### 👤 用户 ({time_str})\n\n{text}\n\n")
            else:
                lines.append(f"### 🤖 助手 ({time_str})\n\n")
                if tool_calls:
                    lines.append(f"**⚡ 执行了 {len(tool_calls)} 个操作:**\n")
                    for tc in tool_calls:
                        lines.append(f"- `{tc.get('name')}` ({tc.get('action', '')})\n")
                    lines.append("\n")
                lines.append(f"{text}\n\n")
            lines.append("---\n\n")
        return "".join(lines)


# ==========================================
# 4. Protobuf 文件安全更新
# ==========================================

def remove_conversations_from_pb(pb_path: str, cids_to_remove: set) -> Tuple[bool, int, str]:
    if not os.path.exists(pb_path):
        return True, 0, "PB file does not exist"

    try:
        ts = int(time.time())
        bak_path = f"{pb_path}.bak.{ts}"
        shutil.copy2(pb_path, bak_path)

        with open(pb_path, 'rb') as f:
            raw_data = f.read()

        top_records = parse_protobuf_wire(raw_data)
        retained_records = []
        removed_count = 0

        for field_num, wire_type, rec_bytes in top_records:
            if field_num == 1 and isinstance(rec_bytes, bytes):
                sub_fields = parse_protobuf_wire(rec_bytes)
                cid = None
                for sfn, swt, sfval in sub_fields:
                    if sfn == 1 and isinstance(sfval, bytes):
                        cid = sfval.decode('utf-8', errors='ignore')
                        break

                if cid and cid in cids_to_remove:
                    removed_count += 1
                    continue

            retained_records.append((field_num, wire_type, rec_bytes))

        new_data = serialize_protobuf_records(retained_records)
        with open(pb_path, 'wb') as f:
            f.write(new_data)

        return True, removed_count, f"成功从 PB 中移除 {removed_count} 条记录"
    except Exception as e:
        return False, 0, f"更新 PB 文件失败: {e}"
