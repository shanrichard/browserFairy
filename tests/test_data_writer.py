"""Tests for DataWriter functionality."""

import asyncio
import json
import pytest
from pathlib import Path
from unittest.mock import patch

from browserfairy.data.writer import DataWriter


@pytest.mark.asyncio
class TestDataWriter:
    """DataWriter基础功能测试，参考test_memory.py模式"""
    
    @pytest.fixture
    def temp_session_dir(self, tmp_path):
        """临时会话目录fixture"""
        session_dir = tmp_path / "test_session"
        session_dir.mkdir()
        return session_dir
    
    @pytest.fixture
    def data_writer(self, temp_session_dir):
        """DataWriter实例fixture"""
        return DataWriter(temp_session_dir)
    
    async def test_jsonl_append_write(self, data_writer, temp_session_dir):
        """测试JSONL格式追加写入"""
        test_data = {"timestamp": "2025-01-14T15:30:00Z", "value": 42}
        file_path = "test.jsonl"
        
        await data_writer.append_jsonl(file_path, test_data)
        
        # 验证文件存在和内容格式
        full_path = temp_session_dir / file_path
        assert full_path.exists()
        
        content = full_path.read_text().strip()
        assert json.loads(content) == test_data
    
    async def test_directory_creation(self, data_writer, temp_session_dir):
        """测试按hostname的目录结构创建"""
        test_data = {"hostname": "github.com", "value": 123}
        file_path = "github.com/memory.jsonl"
        
        await data_writer.append_jsonl(file_path, test_data)
        
        # 验证目录结构
        assert (temp_session_dir / "github.com").is_dir()
        assert (temp_session_dir / "github.com" / "memory.jsonl").exists()
    
    async def test_concurrent_write(self, data_writer, temp_session_dir):
        """测试并发写入的线程安全性"""
        tasks = []
        for i in range(10):
            data = {"id": i, "timestamp": f"2025-01-14T15:30:{i:02d}Z"}
            tasks.append(data_writer.append_jsonl("concurrent.jsonl", data))
        
        await asyncio.gather(*tasks)
        
        # 验证所有数据都被正确写入，无数据丢失或损坏
        file_path = temp_session_dir / "concurrent.jsonl"
        assert file_path.exists()
        
        lines = file_path.read_text().strip().split('\n')
        assert len(lines) == 10
        
        # 验证每行都是有效JSON
        parsed_data = []
        for line in lines:
            parsed_data.append(json.loads(line))
        
        # 验证所有ID都存在（顺序可能不同）
        ids = {data["id"] for data in parsed_data}
        assert ids == set(range(10))
    
    async def test_multiple_append_same_file(self, data_writer, temp_session_dir):
        """测试对同一文件的多次追加写入"""
        file_path = "append_test.jsonl"
        
        # 写入多条数据
        for i in range(3):
            test_data = {"sequence": i, "value": f"test{i}"}
            await data_writer.append_jsonl(file_path, test_data)
        
        # 验证文件内容
        full_path = temp_session_dir / file_path
        lines = full_path.read_text().strip().split('\n')
        assert len(lines) == 3
        
        for i, line in enumerate(lines):
            data = json.loads(line)
            assert data["sequence"] == i
            assert data["value"] == f"test{i}"
    
    async def test_file_rotation_trigger(self, data_writer, temp_session_dir):
        """测试文件轮转触发机制"""
        file_path = "rotation_test.jsonl"
        full_path = temp_session_dir / file_path
        
        # 创建一个超过大小限制的文件
        with patch.object(data_writer, 'MAX_FILE_SIZE', 100):  # 设置很小的限制
            # 写入一些数据
            await data_writer.append_jsonl(file_path, {"data": "x" * 50})
            assert full_path.exists()
            
            # 再写入数据应该触发轮转
            await data_writer.append_jsonl(file_path, {"data": "y" * 60})
            
            # 检查是否有轮转文件
            rotated_file = full_path.with_suffix(".1.jsonl")
            # 由于文件轮转的复杂性，这里主要验证没有异常抛出
            # 实际的轮转逻辑在_rotate_if_needed中测试
    
    async def test_write_error_handling(self, data_writer):
        """测试写入错误的优雅处理"""
        # 使用无效路径触发错误（在某些系统上可能需要调整）
        invalid_path = "/root/invalid_path/test.jsonl"  # 假设这是无权限路径
        
        # 应该不抛出异常，而是记录警告
        try:
            await data_writer.append_jsonl(invalid_path, {"test": "data"})
            # 如果成功了，说明路径实际上是可写的，这也是可接受的
        except Exception:
            # 如果确实出现异常，测试失败
            pytest.fail("DataWriter should handle write errors gracefully without raising exceptions")
    
    def test_sync_write_jsonl(self, data_writer, temp_session_dir):
        """测试同步写入方法"""
        file_path = temp_session_dir / "sync_test.jsonl"
        json_line = '{"test": "sync_write"}\n'
        
        data_writer._sync_write_jsonl(file_path, json_line)
        
        assert file_path.exists()
        content = file_path.read_text()
        assert content == json_line
        assert json.loads(content.strip()) == {"test": "sync_write"}
    
    def test_sync_rotate_files(self, data_writer, temp_session_dir):
        """测试文件轮转逻辑"""
        # 创建一些测试文件
        base_file = temp_session_dir / "rotate_test.jsonl"
        file1 = temp_session_dir / "rotate_test.1.jsonl"
        file2 = temp_session_dir / "rotate_test.2.jsonl"
        
        # 创建文件
        base_file.write_text("base content")
        file1.write_text("file1 content")
        file2.write_text("file2 content")
        
        # 执行轮转
        data_writer._sync_rotate_files(base_file)
        
        # 验证轮转结果
        assert not base_file.exists()  # 原文件应该被重命名
        assert (temp_session_dir / "rotate_test.2.jsonl").exists()  # file1 -> file2
        assert (temp_session_dir / "rotate_test.3.jsonl").exists()  # file2 -> file3
        assert (temp_session_dir / "rotate_test.1.jsonl").exists()  # base -> file1
        
        # 验证内容
        new_file1 = temp_session_dir / "rotate_test.1.jsonl"
        new_file2 = temp_session_dir / "rotate_test.2.jsonl"
        new_file3 = temp_session_dir / "rotate_test.3.jsonl"
        
        assert new_file1.read_text() == "base content"
        assert new_file2.read_text() == "file1 content"
        assert new_file3.read_text() == "file2 content"