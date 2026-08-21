"""
Antigravity 会话回收站与数据安全管理器
支持：
- 安全软删除（移动至回收站 + 记录详细元数据快照）
- 原生 Protobuf 记录无损保存与一键还原
- 单个/批量撤销还原
- 彻底粉碎删除与磁盘空间释放
"""

import os
import sys
import json
import time
import shutil
import base64
from typing import Dict, List, Any, Optional, Tuple

from storage_parser import (
    ANTIGRAVITY_DIR,
    PB_PATH,
    CONV_DIR,
    BRAIN_DIR,
    ANNOTATIONS_DIR,
    AntigravityStorage,
    remove_conversations_from_pb,
    parse_protobuf_wire,
    serialize_protobuf_records,
    get_dir_size,
    format_bytes,
    format_timestamp
)

TRASH_DIR = os.path.join(ANTIGRAVITY_DIR, 'trash')


class TrashManager:
    def __init__(self, base_dir: str = ANTIGRAVITY_DIR):
        self.base_dir = base_dir
        self.trash_dir = os.path.join(base_dir, 'trash')
        self.storage = AntigravityStorage(base_dir)
        os.makedirs(self.trash_dir, exist_ok=True)

    def move_to_trash(self, cids: List[str]) -> Dict[str, Any]:
        """
        将一批会话安全移入回收站
        """
        if not cids:
            return {'success': True, 'count': 0, 'freed_bytes': 0, 'message': '未选择任何会话'}

        # 获取现有会话信息
        all_convs = {c['id']: c for c in self.storage.get_all_conversations()}
        pb_summaries = self.storage.load_pb_summaries()

        ts = int(time.time())
        moved_count = 0
        total_freed = 0
        details = []

        # 1. 逐个将文件移动到回收站
        for cid in cids:
            conv_info = all_convs.get(cid, {})
            pb_item = pb_summaries.get(cid)

            trash_item_name = f"{cid}_{ts}"
            trash_item_dir = os.path.join(self.trash_dir, trash_item_name)
            os.makedirs(trash_item_dir, exist_ok=True)

            moved_files = []
            item_freed = 0

            # 移动 DB 文件
            db_file = os.path.join(self.storage.conv_dir, f"{cid}.db")
            if os.path.exists(db_file):
                try:
                    fsize = os.path.getsize(db_file)
                    item_freed += fsize
                    dest = os.path.join(trash_item_dir, f"{cid}.db")
                    shutil.move(db_file, dest)
                    moved_files.append({'type': 'db', 'original': db_file, 'trash': dest})
                except Exception as e:
                    print(f"[Warn] Move DB error {cid}: {e}", file=sys.stderr)

            # 移动 Brain 目录
            brain_path = os.path.join(self.storage.brain_dir, cid)
            if os.path.exists(brain_path):
                try:
                    fsize = get_dir_size(brain_path)
                    item_freed += fsize
                    dest = os.path.join(trash_item_dir, f"brain_{cid}")
                    shutil.move(brain_path, dest)
                    moved_files.append({'type': 'brain', 'original': brain_path, 'trash': dest})
                except Exception as e:
                    print(f"[Warn] Move Brain error {cid}: {e}", file=sys.stderr)

            # 移动 Annotations 文件
            ann_file = os.path.join(self.storage.annotations_dir, f"{cid}.pbtxt")
            if os.path.exists(ann_file):
                try:
                    fsize = os.path.getsize(ann_file)
                    item_freed += fsize
                    dest = os.path.join(trash_item_dir, f"{cid}.pbtxt")
                    shutil.move(ann_file, dest)
                    moved_files.append({'type': 'annotation', 'original': ann_file, 'trash': dest})
                except Exception as e:
                    print(f"[Warn] Move Annotation error {cid}: {e}", file=sys.stderr)

            # 保存原始 PB 记录字节码 (Base64)
            pb_raw_b64 = None
            if pb_item and 'raw_record_bytes' in pb_item:
                pb_raw_b64 = base64.b64encode(pb_item['raw_record_bytes']).decode('utf-8')

            manifest = {
                'id': cid,
                'trash_key': trash_item_name,
                'title': conv_info.get('title', f'会话 {cid[:8]}'),
                'project': conv_info.get('project', '未分类 / 全局会话'),
                'deleted_ts': ts,
                'deleted_time_str': format_timestamp(ts),
                'total_size': item_freed,
                'total_size_str': format_bytes(item_freed),
                'pb_raw_b64': pb_raw_b64,
                'moved_files': moved_files
            }

            with open(os.path.join(trash_item_dir, 'manifest.json'), 'w', encoding='utf-8') as mf:
                json.dump(manifest, mf, ensure_ascii=False, indent=2)

            moved_count += 1
            total_freed += item_freed
            details.append(manifest)

        # 2. 从 PB 索引文件中移除
        pb_success, pb_count, pb_msg = remove_conversations_from_pb(self.storage.pb_path, set(cids))

        return {
            'success': True,
            'count': moved_count,
            'freed_bytes': total_freed,
            'freed_str': format_bytes(total_freed),
            'pb_removed_count': pb_count,
            'message': f"成功移入回收站 {moved_count} 个会话，释放 {format_bytes(total_freed)} 空间",
            'items': details
        }

    def list_trash(self) -> List[Dict[str, Any]]:
        """
        列出回收站中的所有项目
        """
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
                        data['dir_size'] = get_dir_size(item_dir)
                        data['dir_size_str'] = format_bytes(data['dir_size'])
                        items.append(data)
                except Exception as e:
                    print(f"[Error] Reading trash manifest {d}: {e}", file=sys.stderr)
            else:
                # 缺失 manifest 的异常目录
                items.append({
                    'id': d.split('_')[0] if '_' in d else d,
                    'trash_key': d,
                    'title': f"未知项目 ({d})",
                    'project': '未知',
                    'deleted_ts': 0,
                    'deleted_time_str': '未知',
                    'total_size': get_dir_size(item_dir),
                    'total_size_str': format_bytes(get_dir_size(item_dir)),
                    'pb_raw_b64': None,
                    'moved_files': []
                })

        # 按删除时间倒序排列
        items.sort(key=lambda x: x.get('deleted_ts') or 0, reverse=True)
        return items

    def restore_from_trash(self, trash_keys: List[str]) -> Dict[str, Any]:
        """
        从回收站还原会话（恢复文件并写回 PB 索引）
        """
        if not trash_keys:
            return {'success': True, 'count': 0, 'message': '未选择任何还原项'}

        restored_count = 0
        pb_records_to_add = []

        for tkey in trash_keys:
            item_dir = os.path.join(self.trash_dir, tkey)
            if not os.path.exists(item_dir):
                continue
            manifest_file = os.path.join(item_dir, 'manifest.json')
            if not os.path.exists(manifest_file):
                continue

            try:
                with open(manifest_file, 'r', encoding='utf-8') as f:
                    manifest = json.load(f)

                # 1. 还原各文件
                for mf in manifest.get('moved_files', []):
                    trash_f = mf.get('trash')
                    orig_f = mf.get('original')
                    if trash_f and orig_f and os.path.exists(trash_f):
                        os.makedirs(os.path.dirname(orig_f), exist_ok=True)
                        if os.path.exists(orig_f):
                            if os.path.isdir(orig_f):
                                shutil.rmtree(orig_f)
                            else:
                                os.remove(orig_f)
                        shutil.move(trash_f, orig_f)

                # 2. 收集 PB 记录
                pb_b64 = manifest.get('pb_raw_b64')
                if pb_b64:
                    raw_bytes = base64.b64decode(pb_b64)
                    pb_records_to_add.append((1, 2, raw_bytes))

                # 3. 删除回收站目录
                shutil.rmtree(item_dir)
                restored_count += 1
            except Exception as e:
                print(f"[Error] Restoring trash item {tkey}: {e}", file=sys.stderr)

        # 4. 如果有 PB 记录需要还原回 agyhub_summaries_proto.pb
        if pb_records_to_add and os.path.exists(self.storage.pb_path):
            try:
                with open(self.storage.pb_path, 'rb') as f:
                    curr_data = f.read()
                records = parse_protobuf_wire(curr_data)
                # 检查避免重复插入
                existing_cids = set()
                for fn, wt, rbytes in records:
                    if fn == 1 and isinstance(rbytes, bytes):
                        sub = parse_protobuf_wire(rbytes)
                        for sfn, swt, sfval in sub:
                            if sfn == 1 and isinstance(sfval, bytes):
                                existing_cids.add(sfval.decode('utf-8', errors='ignore'))
                                break

                new_additions = []
                for fn, wt, rbytes in pb_records_to_add:
                    sub = parse_protobuf_wire(rbytes)
                    cid = None
                    for sfn, swt, sfval in sub:
                        if sfn == 1 and isinstance(sfval, bytes):
                            cid = sfval.decode('utf-8', errors='ignore')
                            break
                    if cid and cid not in existing_cids:
                        new_additions.append((fn, wt, rbytes))

                if new_additions:
                    records.extend(new_additions)
                    new_pb_bytes = serialize_protobuf_records(records)
                    with open(self.storage.pb_path, 'wb') as f:
                        f.write(new_pb_bytes)
            except Exception as e:
                print(f"[Error] Re-adding restored PB records: {e}", file=sys.stderr)

        return {
            'success': True,
            'count': restored_count,
            'message': f"已成功还原 {restored_count} 个会话"
        }

    def permanent_delete(self, trash_keys: List[str]) -> Dict[str, Any]:
        """
        从回收站彻底粉碎删除
        """
        if not trash_keys:
            return {'success': True, 'count': 0, 'freed_bytes': 0, 'message': '未选择任何彻底删除项'}

        deleted_count = 0
        total_freed = 0

        for tkey in trash_keys:
            item_dir = os.path.join(self.trash_dir, tkey)
            if os.path.exists(item_dir):
                size = get_dir_size(item_dir)
                try:
                    shutil.rmtree(item_dir)
                    deleted_count += 1
                    total_freed += size
                except Exception as e:
                    print(f"[Error] Permanently deleting {tkey}: {e}", file=sys.stderr)

        return {
            'success': True,
            'count': deleted_count,
            'freed_bytes': total_freed,
            'freed_str': format_bytes(total_freed),
            'message': f"已彻底删除 {deleted_count} 个会话，释放 {format_bytes(total_freed)} 空间"
        }
