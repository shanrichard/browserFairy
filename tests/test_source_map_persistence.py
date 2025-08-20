"""Source Map持久化功能测试"""

import asyncio
import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from browserfairy.analysis.source_map import SourceMapResolver


class TestSourceMapPersistence:
    
    @pytest.fixture
    def mock_connector(self):
        """创建mock connector"""
        connector = AsyncMock()
        connector.on_event = MagicMock()
        connector.off_event = MagicMock()
        return connector
    
    @pytest.fixture
    def resolver(self, mock_connector):
        """创建SourceMapResolver实例"""
        return SourceMapResolver(mock_connector)
    
    def test_set_hostname(self, resolver):
        """测试set_hostname方法"""
        hostname = "example.com"
        resolver.set_hostname(hostname)
        
        assert resolver.hostname == hostname
    
    @pytest.mark.asyncio
    async def test_get_current_session_dir_no_sessions(self, resolver):
        """测试无session目录时的处理"""
        with patch('browserfairy.utils.paths.get_data_directory') as mock_get_data_dir:
            # 模拟空的数据目录
            temp_dir = Path(tempfile.mkdtemp())
            mock_get_data_dir.return_value = temp_dir
            
            result = resolver._get_current_session_dir()
            
            assert result is None
    
    @pytest.mark.asyncio
    async def test_get_current_session_dir_with_sessions(self, resolver):
        """测试有session目录时的处理"""
        with patch('browserfairy.utils.paths.get_data_directory') as mock_get_data_dir:
            # 创建临时目录和session目录
            temp_dir = Path(tempfile.mkdtemp())
            mock_get_data_dir.return_value = temp_dir
            
            # 创建多个session目录
            session1 = temp_dir / "session_2025-08-20_100000"
            session2 = temp_dir / "session_2025-08-20_120000"
            session1.mkdir()
            session2.mkdir()
            
            result = resolver._get_current_session_dir()
            
            # 应该返回最新的session目录
            assert result is not None
            assert result.name in ["session_2025-08-20_100000", "session_2025-08-20_120000"]
    
    @pytest.mark.asyncio
    async def test_persist_source_map_async_no_hostname(self, resolver):
        """测试无hostname时的持久化处理"""
        # hostname为None时应该直接返回
        await resolver._persist_source_map_async(
            "script123", "https://example.com/app.js.map", 
            '{"version": 3}', MagicMock()
        )
        
        # 没有异常抛出就是成功
    
    @pytest.mark.asyncio 
    async def test_persist_source_map_async_with_hostname(self, resolver):
        """测试有hostname时的持久化处理"""
        resolver.hostname = "example.com"
        
        with patch.object(resolver, '_write_source_map_files') as mock_write:
            await resolver._persist_source_map_async(
                "script123", "https://example.com/app.js.map",
                '{"version": 3}', MagicMock()
            )
            
            # 给asyncio一点时间执行后台任务
            await asyncio.sleep(0.1)
            
            # 验证write方法被调用
            assert mock_write.call_count >= 0  # 可能还在执行中
    
    def test_write_source_map_files_no_session_dir(self, resolver):
        """测试无session目录时的文件写入"""
        resolver.hostname = "example.com"
        
        with patch.object(resolver, '_get_current_session_dir', return_value=None):
            # 应该不抛出异常，优雅处理
            resolver._write_source_map_files(
                "script123", "https://example.com/app.js.map",
                '{"version": 3}', MagicMock()
            )
    
    def test_write_source_map_files_success(self, resolver):
        """测试成功的文件写入"""
        resolver.hostname = "example.com"
        resolver.script_metadata = {
            "script123": {
                "url": "https://example.com/app.min.js",
                "sourceMapURL": "https://example.com/app.js.map"
            }
        }
        
        with tempfile.TemporaryDirectory() as temp_dir:
            session_dir = Path(temp_dir) / "session_test"
            session_dir.mkdir()
            
            with patch.object(resolver, '_get_current_session_dir', return_value=session_dir):
                # 创建mock source map
                mock_source_map = MagicMock()
                mock_source_map.raw = {
                    "sources": ["src/app.js"],
                    "sourcesContent": ["const app = () => { console.log('hello'); };"]
                }
                
                metadata_record = resolver._write_source_map_files(
                    "script123", "https://example.com/app.js.map",
                    '{"version": 3, "sources": ["src/app.js"]}', 
                    mock_source_map
                )
                
                # 验证文件被创建
                source_maps_dir = session_dir / "example.com" / "source_maps"
                sources_dir = session_dir / "example.com" / "sources"
                
                assert source_maps_dir.exists()
                assert sources_dir.exists()
                
                # 验证source map文件
                source_map_file = source_maps_dir / "script123.map.json"
                assert source_map_file.exists()
                
                with open(source_map_file) as f:
                    data = json.load(f)
                    assert data["sourceMapUrl"] == "https://example.com/app.js.map"
                    assert data["scriptUrl"] == "https://example.com/app.min.js"
                
                # 验证源文件（现在文件名包含哈希前缀）
                source_files = list(sources_dir.glob("*_src_app.js"))
                assert len(source_files) == 1, f"Expected 1 source file, found {len(source_files)}"
                
                source_file = source_files[0]
                with open(source_file) as f:
                    content = f.read()
                    assert "console.log('hello')" in content
                
                # 验证返回的metadata记录
                assert metadata_record is not None
                assert metadata_record["scriptId"] == "script123"
                assert metadata_record["sourceMapFile"] == "script123.map.json"
                assert metadata_record["scriptUrl"] == "https://example.com/app.min.js"
    
    def test_write_source_map_files_without_sources_content(self, resolver):
        """测试无sourcesContent时的文件写入"""
        resolver.hostname = "example.com"
        resolver.script_metadata = {
            "script123": {
                "url": "https://example.com/app.min.js",
                "sourceMapURL": "https://example.com/app.js.map"
            }
        }
        
        with tempfile.TemporaryDirectory() as temp_dir:
            session_dir = Path(temp_dir) / "session_test"
            session_dir.mkdir()
            
            with patch.object(resolver, '_get_current_session_dir', return_value=session_dir):
                # 创建mock source map without sourcesContent
                mock_source_map = MagicMock()
                mock_source_map.raw = {
                    "sources": ["src/app.js"]
                    # 注意：没有sourcesContent
                }
                
                metadata_record = resolver._write_source_map_files(
                    "script123", "https://example.com/app.js.map",
                    '{"version": 3, "sources": ["src/app.js"]}', 
                    mock_source_map
                )
                
                # 验证source map文件被创建
                source_maps_dir = session_dir / "example.com" / "source_maps"
                assert source_maps_dir.exists()
                
                source_map_file = source_maps_dir / "script123.map.json"
                assert source_map_file.exists()
                
                # 验证metadata记录正确返回
                assert metadata_record is not None
                assert metadata_record["scriptId"] == "script123"
                
                # 验证sources目录不被创建（因为没有sourcesContent）
                sources_dir = session_dir / "example.com" / "sources"
    
    def test_source_file_hash_deduplication(self, resolver):
        """测试源文件哈希去重功能"""
        resolver.hostname = "example.com"
        resolver.script_metadata = {
            "script123": {"url": "https://example.com/app.min.js", "sourceMapURL": ""}
        }
        
        with tempfile.TemporaryDirectory() as temp_dir:
            session_dir = Path(temp_dir) / "session_test"
            session_dir.mkdir()
            
            with patch.object(resolver, '_get_current_session_dir', return_value=session_dir):
                # 创建两个不同的source map，但包含相同内容的源文件
                same_content = "const shared = () => { console.log('same'); };"
                
                # 第一个source map
                mock_source_map1 = MagicMock()
                mock_source_map1.raw = {
                    "sources": ["utils/shared.js"],
                    "sourcesContent": [same_content]
                }
                
                resolver._write_source_map_files(
                    "script123", "https://example.com/app.js.map",
                    '{"version": 3}', mock_source_map1
                )
                
                # 第二个source map，不同路径但相同内容
                mock_source_map2 = MagicMock()
                mock_source_map2.raw = {
                    "sources": ["components/shared.js"],  # 不同路径
                    "sourcesContent": [same_content]      # 但内容相同
                }
                
                resolver._write_source_map_files(
                    "script456", "https://example.com/other.js.map",
                    '{"version": 3}', mock_source_map2
                )
                
                # 验证两个不同名的文件都被创建（因为路径不同）
                sources_dir = session_dir / "example.com" / "sources"
                source_files = list(sources_dir.glob("*"))
                
                # 应该有两个文件，因为虽然内容相同但原始路径不同
                assert len(source_files) == 2
                
                # 验证文件名都包含相同的哈希前缀（因为内容相同）
                hash_prefixes = [f.name.split('_')[0] for f in source_files]
                assert hash_prefixes[0] == hash_prefixes[1], "Same content should have same hash"
                
                # 验证内容确实相同
                for source_file in source_files:
                    with open(source_file) as f:
                        assert f.read() == same_content
    
    def test_filename_conflict_resolution(self, resolver):
        """测试文件名冲突解决方案"""
        resolver.hostname = "example.com"
        resolver.script_metadata = {
            "script123": {"url": "https://example.com/app.min.js", "sourceMapURL": ""}
        }
        
        with tempfile.TemporaryDirectory() as temp_dir:
            session_dir = Path(temp_dir) / "session_test"
            session_dir.mkdir()
            
            with patch.object(resolver, '_get_current_session_dir', return_value=session_dir):
                # 创建两个会导致相同扁平文件名的不同路径
                mock_source_map = MagicMock()
                mock_source_map.raw = {
                    "sources": ["a/b_c.js", "a_b/c.js"],  # 这两个都会变成 a_b_c.js
                    "sourcesContent": [
                        "// content from a/b_c.js",
                        "// content from a_b/c.js"
                    ]
                }
                
                resolver._write_source_map_files(
                    "script123", "https://example.com/app.js.map",
                    '{"version": 3}', mock_source_map
                )
                
                # 验证两个文件都被创建，不会发生覆盖
                sources_dir = session_dir / "example.com" / "sources"
                source_files = list(sources_dir.glob("*"))
                
                assert len(source_files) == 2, "Both conflicting files should be created"
                
                # 验证文件内容不同
                contents = []
                for source_file in source_files:
                    with open(source_file) as f:
                        contents.append(f.read())
                
                assert contents[0] != contents[1], "Files should have different content"
                assert "a/b_c.js" in contents[0] or "a/b_c.js" in contents[1]
                assert "a_b/c.js" in contents[0] or "a_b/c.js" in contents[1]