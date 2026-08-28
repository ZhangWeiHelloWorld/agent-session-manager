"""
AI Agent 会话管理中心 (Agent Session Manager) 单元测试与接口验证套件
纯 Python 3 标准库，无外部依赖，测试用例 100% 自包含与环境隔离。
"""

import os
import sys
import json
import time
import shutil
import unittest

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(CURRENT_DIR, 'backend'))

from storage_parser import (
    parse_protobuf_wire,
    serialize_protobuf_records,
    decode_varint,
    encode_varint,
    extract_project_name,
    format_bytes,
    format_timestamp,
    clean_human_user_prompt
)
from codex_parser import (
    CodexStorage,
    extract_codex_project,
    clean_human_codex_user_prompt
)
from trash_manager import TrashManager
import sqlite3


class TestProtobufWire(unittest.TestCase):
    def test_varint_roundtrip(self):
        """测试 Varint 编码与解码的完全一致性"""
        test_values = [0, 1, 127, 128, 300, 16384, 2097151, 1000000000]
        for val in test_values:
            encoded = encode_varint(val)
            decoded, idx = decode_varint(encoded, 0)
            self.assertEqual(val, decoded, f"Varint 编解码失败: {val}")
            self.assertEqual(len(encoded), idx)

    def test_protobuf_records_roundtrip(self):
        """测试复杂 Protobuf Record 往返二进制一致性"""
        sample_records = [
            (1, 2, b"conversation-id-test-uuid-12345678"),
            (2, 2, serialize_protobuf_records([
                (1, 2, "测试会话标题".encode('utf-8')),
                (2, 0, 42),
                (3, 2, serialize_protobuf_records([(1, 0, 1718000000)]))
            ])),
            (3, 0, 100)
        ]
        serialized = serialize_protobuf_records(sample_records)
        parsed = parse_protobuf_wire(serialized)
        self.assertEqual(len(parsed), len(sample_records))
        re_serialized = serialize_protobuf_records(parsed)
        self.assertEqual(serialized, re_serialized)


class TestProjectExtractors(unittest.TestCase):
    def test_extract_project_name(self):
        """测试 Antigravity 跨平台路径解析为工程名"""
        self.assertEqual(extract_project_name("/Users/dev/projects/my-web-app"), "my-web-app")
        self.assertEqual(extract_project_name("C:\\Users\\dev\\workspace\\ai-bot\\src"), "ai-bot")
        self.assertEqual(extract_project_name("file:///home/user/code/data-service/"), "data-service")
        self.assertEqual(extract_project_name(""), "💬 独立会话 (未关联工程)")
        self.assertEqual(extract_project_name("/Users/dev/.gemini/antigravity/brain/uuid"), "💬 独立会话 (未关联工程)")

    def test_extract_codex_project(self):
        """测试 Codex 跨平台路径解析为工程名"""
        self.assertEqual(extract_codex_project("/home/ubuntu/repo/backend-server"), "backend-server")
        self.assertEqual(extract_codex_project("C:\\Workspace\\frontend-project\\lib"), "frontend-project")
        self.assertEqual(extract_codex_project("/Users/name/Documents/Codex/temp"), "💬 独立会话 (未关联工程)")
        self.assertEqual(extract_codex_project(""), "💬 独立会话 (未关联工程)")


class TestTextCleaning(unittest.TestCase):
    def test_clean_human_user_prompt(self):
        """测试剥离 Antigravity 内部 XML 标签，提取干净的人类输入"""
        raw_text = "<USER_REQUEST>\n帮我写一个 Python 脚本\n</USER_REQUEST>\n<ADDITIONAL_METADATA>...</ADDITIONAL_METADATA>"
        cleaned = clean_human_user_prompt(raw_text)
        self.assertEqual(cleaned, "帮我写一个 Python 脚本")

    def test_clean_human_codex_user_prompt(self):
        """测试剥离 Codex 内部环境标签"""
        raw_text = "<environment_context>cwd: /test</environment_context>\n请优化这段 SQL 查询"
        cleaned = clean_human_codex_user_prompt(raw_text)
        self.assertEqual(cleaned, "请优化这段 SQL 查询")


class TestFormatters(unittest.TestCase):
    def test_format_bytes(self):
        self.assertEqual(format_bytes(500), "500 B")
        self.assertEqual(format_bytes(2048), "2.0 KB")
        self.assertEqual(format_bytes(1048576 * 5), "5.00 MB")
        self.assertEqual(format_bytes(1073741824 * 2), "2.00 GB")

    def test_format_timestamp(self):
        self.assertIsNone(format_timestamp(None))
        self.assertIsNotNone(format_timestamp(1700000000))


class TestTrashManagerIsolated(unittest.TestCase):
    def setUp(self):
        self.temp_base = os.path.join(CURRENT_DIR, 'temp_test_workspace_trash')
        if os.path.exists(self.temp_base):
            shutil.rmtree(self.temp_base)
        os.makedirs(self.temp_base, exist_ok=True)
        os.makedirs(os.path.join(self.temp_base, 'conversations'), exist_ok=True)
        os.makedirs(os.path.join(self.temp_base, 'brain'), exist_ok=True)
        os.makedirs(os.path.join(self.temp_base, 'annotations'), exist_ok=True)

        # 构造虚拟会话文件
        self.test_cid = 'test-conversation-uuid-9999'
        with open(os.path.join(self.temp_base, 'conversations', f'{self.test_cid}.db'), 'w') as f:
            f.write('fake sqlite db content for testing')
        test_brain = os.path.join(self.temp_base, 'brain', self.test_cid)
        os.makedirs(test_brain, exist_ok=True)
        with open(os.path.join(test_brain, 'artifact_test.txt'), 'w') as f:
            f.write('sample artifact payload')

        self.trash = TrashManager(self.temp_base)

    def tearDown(self):
        if os.path.exists(self.temp_base):
            shutil.rmtree(self.temp_base)

    def test_trash_full_lifecycle(self):
        """测试 移入回收站 -> 查看列表 -> 无损还原 -> 再次删除 -> 彻底粉碎"""
        # 1. 移入回收站
        res = self.trash.move_to_trash([self.test_cid])
        self.assertTrue(res['success'])
        self.assertEqual(res['count'], 1)
        self.assertFalse(os.path.exists(os.path.join(self.temp_base, 'conversations', f'{self.test_cid}.db')))

        # 2. 列出回收站
        items = self.trash.list_trash()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['id'], self.test_cid)
        tkey = items[0]['trash_key']

        # 3. 还原
        rest_res = self.trash.restore_from_trash([tkey])
        self.assertTrue(rest_res['success'])
        self.assertTrue(os.path.exists(os.path.join(self.temp_base, 'conversations', f'{self.test_cid}.db')))
        self.assertEqual(len(self.trash.list_trash()), 0)

        # 4. 再次移入并彻底粉碎
        self.trash.move_to_trash([self.test_cid])
        items2 = self.trash.list_trash()
        tkey2 = items2[0]['trash_key']
        purge_res = self.trash.permanent_delete([tkey2])
        self.assertTrue(purge_res['success'])
        self.assertEqual(len(self.trash.list_trash()), 0)


class TestCodexDockerPathResolution(unittest.TestCase):
    def setUp(self):
        self.temp_codex = os.path.join(CURRENT_DIR, 'temp_test_codex')
        if os.path.exists(self.temp_codex):
            shutil.rmtree(self.temp_codex)
        os.makedirs(self.temp_codex, exist_ok=True)
        
        self.session_rel = os.path.join('2026', '08', '20')
        self.sessions_dir = os.path.join(self.temp_codex, 'sessions', self.session_rel)
        os.makedirs(self.sessions_dir, exist_ok=True)

        self.cid = '01a01d1e-d1ab-7d11-a32e-1e2b2ef56078'
        self.rollout_filename = f'rollout-2026-08-20T11-02-34-{self.cid}.jsonl'
        self.actual_rollout_path = os.path.join(self.sessions_dir, self.rollout_filename)
        
        # 写入模拟的 Codex 对话轮次
        with open(self.actual_rollout_path, 'w', encoding='utf-8') as f:
            f.write(json.dumps({
                "type": "response_item",
                "payload": {"role": "user", "content": [{"text": "<environment_context>cwd: /app</environment_context>\n解决自动序号后端标记缺失"}]}
            }) + "\n")
            f.write(json.dumps({
                "type": "response_item",
                "payload": {"role": "assistant", "content": [{"text": "已成功定位并修复序号后端逻辑！"}]}
            }) + "\n")

        # 模拟在宿主机创建但挂载进 Docker 的 sqlite 数据库，其中存储的是宿主机路径
        self.host_rollout_path = f'/Users/hostuser/.codex/sessions/{self.session_rel}/{self.rollout_filename}'
        self.db_path = os.path.join(self.temp_codex, 'state_5.sqlite')
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE threads (
                id TEXT PRIMARY KEY,
                title TEXT,
                cwd TEXT,
                rollout_path TEXT,
                created_at INTEGER,
                updated_at INTEGER,
                created_at_ms INTEGER,
                updated_at_ms INTEGER,
                first_user_message TEXT,
                model TEXT,
                tokens_used INTEGER,
                archived INTEGER
            )
        """)
        cur.execute("""
            INSERT INTO threads (id, title, cwd, rollout_path, created_at, updated_at, first_user_message, model)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            self.cid,
            '解决自动序号后端标记缺失',
            '/Users/hostuser/projects/my-app',
            self.host_rollout_path,
            1787190000,
            1787190100,
            '解决自动序号后端标记缺失',
            'gpt-5.6-sol'
        ))
        conn.commit()
        conn.close()

        self.storage = CodexStorage(self.temp_codex)

    def tearDown(self):
        if os.path.exists(self.temp_codex):
            shutil.rmtree(self.temp_codex)

    def test_codex_docker_path_resolution(self):
        """测试在 Docker/跨平台路径下，CodexStorage 能自动校准宿主机路径并读取对话"""
        convs = self.storage.get_all_conversations()
        self.assertEqual(len(convs), 1)
        conv = convs[0]
        self.assertEqual(conv['id'], self.cid)
        self.assertTrue(conv['has_rollout'])
        self.assertGreater(conv['total_size'], 0)
        self.assertEqual(conv['rollout_path'], self.actual_rollout_path)

        # 测试详情获取与文本清洗
        details = self.storage.get_conversation_details(self.cid)
        self.assertIsNotNone(details)
        self.assertEqual(details['turns_count'], 2)
        self.assertEqual(details['turns'][0]['role'], 'user')
        self.assertEqual(details['turns'][0]['text'], '解决自动序号后端标记缺失')
        self.assertEqual(details['turns'][1]['role'], 'assistant')
        self.assertIn('已成功定位并修复', details['turns'][1]['text'])

        # 测试 Markdown 导出
        md = self.storage.export_conversation_markdown(self.cid)
        self.assertIn('解决自动序号后端标记缺失', md)
        self.assertIn('已成功定位并修复', md)

        # 测试移入回收站与还原
        del_res = self.storage.move_to_trash([self.cid])
        self.assertTrue(del_res['success'])
        self.assertIn('items', del_res)
        self.assertEqual(len(del_res['items']), 1)
        self.assertEqual(del_res['items'][0]['id'], self.cid)
        self.assertFalse(os.path.exists(self.actual_rollout_path))

        trash_items = self.storage.list_trash()
        self.assertEqual(len(trash_items), 1)
        tkey = trash_items[0]['trash_key']

        restore_res = self.storage.restore_from_trash([tkey])
        self.assertTrue(restore_res['success'])
        self.assertTrue(os.path.exists(self.actual_rollout_path))


class TestTrashManagerBatch(unittest.TestCase):
    def setUp(self):
        self.temp_base = os.path.join(CURRENT_DIR, 'temp_test_workspace_batch_trash')
        if os.path.exists(self.temp_base):
            shutil.rmtree(self.temp_base)
        os.makedirs(self.temp_base, exist_ok=True)
        os.makedirs(os.path.join(self.temp_base, 'conversations'), exist_ok=True)
        os.makedirs(os.path.join(self.temp_base, 'brain'), exist_ok=True)
        os.makedirs(os.path.join(self.temp_base, 'annotations'), exist_ok=True)

        self.cids = [f'test-batch-uuid-{i}' for i in range(5)]
        for cid in self.cids:
            with open(os.path.join(self.temp_base, 'conversations', f'{cid}.db'), 'w') as f:
                f.write(f'fake db {cid}')
            brain_p = os.path.join(self.temp_base, 'brain', cid)
            os.makedirs(brain_p, exist_ok=True)
            with open(os.path.join(brain_p, 'file.txt'), 'w') as f:
                f.write('content')

        self.trash = TrashManager(self.temp_base)

    def tearDown(self):
        if os.path.exists(self.temp_base):
            shutil.rmtree(self.temp_base)

    def test_batch_move_to_trash_and_restore_all(self):
        """测试批量全选移入回收站与批量一键还原"""
        del_res = self.trash.move_to_trash(self.cids)
        self.assertTrue(del_res['success'])
        self.assertEqual(del_res['count'], 5)
        self.assertIn('items', del_res)
        self.assertEqual(len(del_res['items']), 5)

        # 验证回收站列表
        trash_items = self.trash.list_trash()
        self.assertEqual(len(trash_items), 5)
        tkeys = [it['trash_key'] for it in trash_items]

        # 批量一键还原全部
        rest_res = self.trash.restore_from_trash(tkeys)
        self.assertTrue(rest_res['success'])
        self.assertEqual(rest_res['count'], 5)
        self.assertEqual(len(self.trash.list_trash()), 0)

        # 验证文件均已完整还原
        for cid in self.cids:
            self.assertTrue(os.path.exists(os.path.join(self.temp_base, 'conversations', f'{cid}.db')))
            self.assertTrue(os.path.exists(os.path.join(self.temp_base, 'brain', cid, 'file.txt')))


if __name__ == '__main__':
    unittest.main()
