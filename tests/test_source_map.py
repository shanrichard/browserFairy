"""Source Map解析器的测试"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from browserfairy.analysis.source_map import SourceMapResolver


class TestSourceMapResolver:
    
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
    
    @pytest.mark.asyncio
    async def test_initialization(self, resolver, mock_connector):
        """测试初始化和事件监听（不主动启用Debugger）"""
        result = await resolver.initialize("test_session")
        
        # 验证不主动调用Debugger.enable
        mock_connector.call.assert_not_called()
        # 验证注册了scriptParsed事件监听
        mock_connector.on_event.assert_called_with(
            "Debugger.scriptParsed",
            resolver._on_script_parsed
        )
        assert resolver.initialized is True
        assert result is True
    
    @pytest.mark.asyncio
    async def test_initialization_failure(self, resolver, mock_connector):
        """测试初始化失败时的优雅降级"""
        mock_connector.on_event.side_effect = Exception("Event registration failed")
        
        result = await resolver.initialize("test_session")
        
        assert resolver.initialized is False
        assert result is False
    
    @pytest.mark.asyncio
    async def test_script_parsed_event(self, resolver):
        """测试脚本解析事件处理"""
        resolver.session_id = "test_session"
        
        # 模拟scriptParsed事件
        params = {
            "sessionId": "test_session",
            "scriptId": "script123",
            "url": "https://example.com/app.js",
            "sourceMapURL": "app.js.map"
        }
        
        await resolver._on_script_parsed(params)
        
        # 验证脚本元数据被记录
        assert "script123" in resolver.script_metadata
        assert resolver.script_metadata["script123"]["sourceMapURL"] == "app.js.map"
    
    @pytest.mark.asyncio
    async def test_script_parsed_wrong_session(self, resolver):
        """测试错误sessionId的事件被过滤"""
        resolver.session_id = "test_session"
        
        params = {
            "sessionId": "wrong_session",
            "scriptId": "script123",
            "url": "https://example.com/app.js",
            "sourceMapURL": "app.js.map"
        }
        
        await resolver._on_script_parsed(params)
        
        # 不应该记录错误session的脚本
        assert "script123" not in resolver.script_metadata
    
    @pytest.mark.asyncio
    async def test_resolve_frame_without_scriptid(self, resolver):
        """测试没有scriptId的帧保持原样"""
        frame = {
            "function": "myFunction",
            "url": "https://example.com/app.js",
            "line": 10,
            "column": 5
        }
        
        enhanced_frame = await resolver.resolve_frame(frame)
        
        # 应该原样返回，不添加original字段
        assert enhanced_frame == frame
        assert "original" not in enhanced_frame
    
    @pytest.mark.asyncio
    async def test_resolve_frame_with_cache(self, resolver):
        """测试缓存机制"""
        resolver.initialized = True
        
        # 预填充缓存
        cache_key = "script123:10:5"
        cached_info = {
            "file": "source.js",
            "line": 45,
            "column": 12
        }
        resolver.location_cache[cache_key] = cached_info
        
        # 添加脚本元数据
        resolver.script_metadata["script123"] = {
            "url": "https://example.com/app.js",
            "sourceMapURL": None  # 没有source map，但有缓存
        }
        
        frame = {
            "scriptId": "script123",
            "lineNumber": 10,
            "columnNumber": 5
        }
        
        enhanced_frame = await resolver.resolve_frame(frame)
        
        # 应该从缓存返回
        assert enhanced_frame["original"] == cached_info
    
    @pytest.mark.asyncio
    async def test_source_map_download_and_parse(self, resolver):
        """测试Source Map下载和解析"""
        with patch('browserfairy.analysis.source_map.sourcemap') as mock_sourcemap:
            # 模拟Token
            mock_token = MagicMock()
            mock_token.src = "src/app.js"
            mock_token.src_line = 42
            mock_token.src_col = 10
            mock_token.name = "myFunction"
            
            # 模拟Source Map对象
            mock_source_map = MagicMock()
            mock_source_map.lookup.return_value = mock_token
            mock_source_map.sources = ["src/app.js"]
            mock_source_map.raw = {
                "sourcesContent": ["const x = 1;\nconst y = 2;"]
            }
            mock_sourcemap.loads.return_value = mock_source_map
            
            # 模拟HTTP响应
            mock_response = MagicMock()
            mock_response.text = '{"version": 3}'
            mock_response.raise_for_status = MagicMock()
            resolver.http_client.get = AsyncMock(return_value=mock_response)
            
            # 获取Source Map
            source_map = await resolver._get_source_map(
                "https://example.com/app.js",
                "app.js.map"
            )
            
            assert source_map is not None
            # 验证缓存
            assert "https://example.com/app.js.map" in resolver.source_map_cache
    
    @pytest.mark.asyncio
    async def test_data_url_source_map(self, resolver):
        """测试data URL格式的Source Map"""
        with patch('browserfairy.analysis.source_map.sourcemap') as mock_sourcemap:
            mock_source_map = MagicMock()
            mock_sourcemap.loads.return_value = mock_source_map
            
            # Base64编码的Source Map
            import base64
            source_map_content = '{"version": 3}'
            encoded = base64.b64encode(source_map_content.encode()).decode()
            data_url = f"data:application/json;base64,{encoded}"
            
            source_map = await resolver._get_source_map(
                "https://example.com/app.js",
                data_url
            )
            
            assert source_map is not None
            mock_sourcemap.loads.assert_called_with(source_map_content)
    
    @pytest.mark.asyncio
    async def test_cleanup(self, resolver, mock_connector):
        """测试清理资源（不禁用Debugger）"""
        await resolver.initialize("test_session")
        
        # 添加一些数据
        resolver.script_metadata["script1"] = {"url": "test.js"}
        resolver.location_cache["key1"] = {"data": "test"}
        
        await resolver.cleanup()
        
        # 验证取消事件监听
        mock_connector.off_event.assert_called_with(
            "Debugger.scriptParsed",
            resolver._on_script_parsed
        )
        # 验证不调用Debugger.disable
        mock_connector.call.assert_not_called()
        # 验证清理缓存
        assert len(resolver.script_metadata) == 0
        assert len(resolver.source_map_cache) == 0
        assert len(resolver.location_cache) == 0
    
    def test_lru_cache_eviction(self, resolver):
        """测试LRU缓存淘汰"""
        resolver.max_cache_size = 3
        
        # 填充缓存
        for i in range(4):
            key = f"key{i}"
            value = {"data": i}
            resolver._update_cache(key, value)
        
        # 第一个应该被淘汰（位置缓存大小是max_cache_size * 10）
        assert len(resolver.location_cache) == 4  # 因为限制是3*10=30
        
        # 测试Source Map缓存
        for i in range(4):
            url = f"url{i}"
            sm = MagicMock()
            resolver._update_source_map_cache(url, sm)
        
        # Source Map缓存应该淘汰第一个
        assert "url0" not in resolver.source_map_cache
        assert "url3" in resolver.source_map_cache
        assert len(resolver.source_map_cache) == 3