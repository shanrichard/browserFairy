"""Source Map解析器 - 将压缩代码位置映射到源代码"""

import base64
import json
import logging
from collections import OrderedDict
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

import httpx
import sourcemap

logger = logging.getLogger(__name__)


class SourceMapResolver:
    """Source Map解析器 - 将压缩代码位置映射到源代码"""
    
    def __init__(self, connector, max_cache_size: int = 10):
        self.connector = connector
        self.session_id = None
        
        # scriptId -> {url, sourceMapURL} 映射
        self.script_metadata = {}
        
        # sourceMapURL -> SourceMap对象缓存
        self.source_map_cache = OrderedDict()
        
        # (scriptId, line, column) -> source info 结果缓存
        self.location_cache = OrderedDict()
        
        self.max_cache_size = max_cache_size
        self.initialized = False  # 表示解析器已初始化
        self.http_client = httpx.AsyncClient(timeout=5.0)
        
    async def initialize(self, session_id: str) -> bool:
        """初始化并监听脚本事件（复用已有的Debugger domain）"""
        self.session_id = session_id
        try:
            # 注意：不主动启用Debugger domain，假设已被MemoryCollector等组件启用
            # 监听脚本解析事件以获取sourceMapURL
            self.connector.on_event("Debugger.scriptParsed", self._on_script_parsed)
            self.initialized = True
            
            logger.debug(f"SourceMapResolver initialized for session {session_id}")
            return True
        except Exception as e:
            logger.warning(f"Failed to initialize SourceMapResolver: {e}")
            return False
    
    async def _on_script_parsed(self, params: dict) -> None:
        """监听脚本解析事件，收集sourceMapURL"""
        if params.get("sessionId") != self.session_id:
            return
            
        script_id = params.get("scriptId")
        source_map_url = params.get("sourceMapURL")
        url = params.get("url")
        
        if script_id and url:
            self.script_metadata[script_id] = {
                "url": url,
                "sourceMapURL": source_map_url
            }
            if source_map_url:
                logger.debug(f"Found source map for {url}: {source_map_url}")
    
    async def resolve_stack_trace(self, stack_trace: List[Dict]) -> List[Dict]:
        """解析整个堆栈跟踪"""
        if not self.initialized or not stack_trace:
            return stack_trace
            
        enhanced_stack = []
        for frame in stack_trace:
            enhanced_frame = await self.resolve_frame(frame)
            enhanced_stack.append(enhanced_frame)
            
        return enhanced_stack
    
    async def resolve_frame(self, frame: Dict) -> Dict:
        """解析单个堆栈帧（v1仅支持有scriptId的帧）"""
        try:
            # v1要求必须有scriptId才能解析，没有scriptId直接返回
            script_id = frame.get('scriptId')
            if not script_id or script_id not in self.script_metadata:
                return frame
                
            # 读取行列号：优先使用lineNumber/columnNumber，回退到line/column
            line = frame.get('lineNumber', frame.get('line', 0))
            column = frame.get('columnNumber', frame.get('column', 0))
            
            # 检查缓存
            cache_key = f"{script_id}:{line}:{column}"
            if cache_key in self.location_cache:
                frame['original'] = self.location_cache[cache_key]
                return frame
            
            # 获取脚本元数据
            script_meta = self.script_metadata[script_id]
            source_map_url = script_meta.get('sourceMapURL')
            
            if not source_map_url:
                return frame
            
            # 获取Source Map对象
            source_map = await self._get_source_map(script_meta['url'], source_map_url)
            if not source_map:
                return frame
            
            # 使用sourcemap库查找原始位置（CDP和source-map都是0-based）
            token = source_map.lookup(line=line, column=column)
            
            if token and token.src:
                original_info = {
                    'file': token.src,  # 原始文件路径
                    'line': token.src_line,  # 原始行号
                    'column': token.src_col,  # 原始列号
                }
                
                # 添加原始函数名（如果有）
                if token.name:
                    original_info['name'] = token.name
                
                # 获取源代码片段（如果Source Map包含源代码）
                if hasattr(source_map, 'raw') and isinstance(source_map.raw, dict):
                    sources_content = source_map.raw.get('sourcesContent')
                    if sources_content:
                        # 找到对应的源文件索引
                        try:
                            src_index = source_map.sources.index(token.src)
                            if src_index < len(sources_content) and sources_content[src_index]:
                                lines = sources_content[src_index].split('\n')
                                if 0 <= token.src_line < len(lines):
                                    original_info['source'] = lines[token.src_line].strip()
                        except (ValueError, IndexError):
                            pass  # 找不到源码，忽略
                
                # 更新缓存
                self._update_cache(cache_key, original_info)
                frame['original'] = original_info
                
        except Exception as e:
            logger.debug(f"Failed to resolve frame: {e}")
            
        return frame
    
    async def _get_source_map(self, script_url: str, source_map_url: str) -> Optional[Any]:
        """获取并解析Source Map（v1仅支持data URL和HTTP）"""
        try:
            # 先规范化URL为绝对路径，确保缓存键一致
            if not source_map_url.startswith(('http://', 'https://', 'data:')):
                source_map_url = urljoin(script_url, source_map_url)
            
            # 规范化后再检查缓存
            if source_map_url in self.source_map_cache:
                return self.source_map_cache[source_map_url]
            
            # v1实现：仅支持data URL和直接HTTP获取
            # v2增强：并发下载去重（共享pending future）
            
            # 处理data URL
            if source_map_url.startswith('data:'):
                # data URL format: data:<mime>[;charset=<c>][;base64],<data>
                header, data = source_map_url.split(',', 1)
                is_base64 = header.strip().lower().endswith(';base64')
                if is_base64:
                    source_map_content = base64.b64decode(data).decode('utf-8')
                else:
                    source_map_content = data
            else:
                # HTTP下载
                response = await self.http_client.get(source_map_url)
                response.raise_for_status()
                source_map_content = response.text
            
            # 解析Source Map
            source_map = sourcemap.loads(source_map_content)
            
            # 更新缓存
            self._update_source_map_cache(source_map_url, source_map)
            
            return source_map
            
        except Exception as e:
            logger.debug(f"Failed to get source map {source_map_url}: {e}")
            return None
    
    def _update_cache(self, key: str, value: Dict):
        """更新位置映射LRU缓存"""
        # 如果已存在，先删除（移到最后）
        if key in self.location_cache:
            del self.location_cache[key]
        # 如果缓存满了，删除最旧的
        elif len(self.location_cache) >= self.max_cache_size * 10:  # 位置缓存可以更大
            self.location_cache.popitem(last=False)
        # 添加到末尾
        self.location_cache[key] = value
    
    def _update_source_map_cache(self, url: str, source_map: Any):
        """更新Source Map LRU缓存"""
        # 如果已存在，先删除（移到最后）
        if url in self.source_map_cache:
            del self.source_map_cache[url]
        # 如果缓存满了，删除最旧的
        elif len(self.source_map_cache) >= self.max_cache_size:
            self.source_map_cache.popitem(last=False)
        # 添加到末尾
        self.source_map_cache[url] = source_map
    
    async def cleanup(self):
        """清理资源"""
        if self.initialized:
            try:
                # 取消事件监听
                self.connector.off_event("Debugger.scriptParsed", self._on_script_parsed)
                # 注意：不禁用Debugger domain，因为可能被其他组件使用
            except Exception:
                pass
            self.initialized = False
        
        # 清理缓存
        self.script_metadata.clear()
        self.source_map_cache.clear()
        self.location_cache.clear()
        
        # 关闭HTTP客户端
        await self.http_client.aclose()
