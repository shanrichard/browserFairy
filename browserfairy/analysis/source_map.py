"""Source Map解析器 - 将压缩代码位置映射到源代码"""

import asyncio
import base64
import hashlib
import json
import logging
import os
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

import httpx
import sourcemap

logger = logging.getLogger(__name__)


class SourceMapResolver:
    """Source Map解析器 - 将压缩代码位置映射到源代码"""
    
    def __init__(self, connector, max_cache_size: int = 10, persist_all: bool = False):
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
        
        # 持久化相关属性
        self.hostname = None  # 由ConsoleMonitor设置
        self.persistence_semaphore = asyncio.Semaphore(2)  # 并发控制
        self.metadata_lock = asyncio.Lock()  # 专用锁保护metadata.jsonl写入
        
        # 主动持久化相关属性
        self.persist_all = persist_all  # 是否主动持久化所有source maps
        self.download_semaphore = asyncio.Semaphore(3)  # 限制并发下载数
        
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
    
    def set_hostname(self, hostname: str) -> None:
        """设置hostname用于确定存储路径"""
        self.hostname = hostname
        logger.debug(f"SourceMapResolver hostname set to: {hostname}")
    
    def _get_current_session_dir(self) -> Optional[Path]:
        """自动发现当前会话目录（按目录名中的时间戳排序，避免ctime问题）"""
        try:
            from ..utils.paths import get_data_directory
            data_dir = get_data_directory()
            
            # 查找所有session_*目录
            session_dirs = list(data_dir.glob("session_*"))
            if not session_dirs:
                logger.debug("No session directories found")
                return None
            
            # 按目录名中的时间戳排序（session_YYYY-MM-DD_HHMMSS格式）
            def extract_timestamp(path: Path) -> str:
                try:
                    # 提取session_之后的时间戳部分
                    name_parts = path.name.split('_', 1)
                    if len(name_parts) > 1:
                        return name_parts[1]  # YYYY-MM-DD_HHMMSS部分
                    return ""
                except:
                    return ""
            
            # 按时间戳排序，返回最新的
            sorted_sessions = sorted(session_dirs, key=extract_timestamp, reverse=True)
            latest_session = sorted_sessions[0]
            logger.debug(f"Found latest session directory: {latest_session}")
            return latest_session
        except Exception as e:
            logger.warning(f"Failed to discover session directory: {e}")
            return None
    
    async def _on_script_parsed(self, params: dict) -> None:
        """监听脚本解析事件，收集sourceMapURL并保存脚本源代码"""
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
            
            # 如果启用了persist_all，保存所有脚本（不管有没有source map）
            if self.persist_all and self.hostname:
                if source_map_url:
                    logger.debug(f"Found source map for {url}: {source_map_url}")
                    # 有source map，下载source map和关联的源文件
                    asyncio.create_task(self._proactive_persist(script_id, url, source_map_url))
                else:
                    logger.debug(f"No source map for {url}, will save script source directly")
                    # 没有source map，直接获取并保存脚本源代码
                    asyncio.create_task(self._persist_script_source(script_id, url))
    
    async def _proactive_persist(self, script_id: str, script_url: str, source_map_url: str) -> None:
        """主动下载并持久化source map（不等待异常）"""
        async with self.download_semaphore:  # 限流
            try:
                # 复用现有的_get_source_map方法
                source_map = await self._get_source_map(script_url, source_map_url, script_id)
                if source_map:
                    logger.debug(f"Proactively persisted source map for {script_url}")
            except Exception as e:
                logger.warning(f"Failed to proactively persist source map for {script_url}: {e}")
    
    async def _persist_script_source(self, script_id: str, script_url: str) -> None:
        """获取并持久化脚本源代码（没有source map的情况）"""
        async with self.download_semaphore:  # 限流
            try:
                # 调用Debugger.getScriptSource获取源代码
                response = await self.connector.call(
                    "Debugger.getScriptSource",
                    {"scriptId": script_id},
                    session_id=self.session_id
                )
                
                if response and "scriptSource" in response:
                    # 保存脚本源代码
                    await self._save_script_source(script_id, script_url, response["scriptSource"])
                    logger.debug(f"Persisted script source for {script_url}")
                else:
                    logger.warning(f"No script source returned for {script_url}")
            except Exception as e:
                logger.warning(f"Failed to persist script source for {script_url}: {e}")
    
    async def _save_script_source(self, script_id: str, script_url: str, script_content: str) -> None:
        """保存脚本源代码到文件系统"""
        async with self.persistence_semaphore:
            try:
                # 使用 asyncio.to_thread 执行文件操作
                await asyncio.to_thread(
                    self._write_script_source_file,
                    script_id, script_url, script_content
                )
            except Exception as e:
                logger.warning(f"Failed to save script source for {script_url}: {e}")
    
    def _write_script_source_file(self, script_id: str, script_url: str, script_content: str) -> None:
        """同步写入脚本源代码到文件（在thread中执行）"""
        session_dir = self._get_current_session_dir()
        if not session_dir:
            logger.warning("No session directory found for script source persistence")
            return
            
        # 创建目标目录结构
        site_dir = session_dir / self.hostname
        sources_dir = site_dir / "sources"
        sources_dir.mkdir(parents=True, exist_ok=True)
        
        # 从URL提取文件名
        from urllib.parse import urlparse
        parsed_url = urlparse(script_url)
        filename = parsed_url.path.split('/')[-1] if parsed_url.path else 'unknown.js'
        
        # 如果没有文件名或文件名无效，使用scriptId
        if not filename or filename == '/' or not filename.endswith(('.js', '.mjs', '.jsx', '.ts', '.tsx')):
            filename = f"script_{script_id}.js"
        
        # 计算内容哈希以避免重复
        content_hash = hashlib.blake2s(script_content.encode('utf-8'), digest_size=8).hexdigest()
        
        # 使用哈希前缀 + 文件名避免冲突
        unique_filename = f"{content_hash}_{filename}"
        source_file = sources_dir / unique_filename
        
        # 如果文件已存在且内容相同则跳过
        if source_file.exists():
            try:
                with open(source_file, 'r', encoding='utf-8') as existing:
                    if existing.read() == script_content:
                        logger.debug(f"Script source already exists: {unique_filename}")
                        return
            except Exception:
                pass  # 如果读取失败，继续写入
        
        # 写入脚本源代码
        with open(source_file, 'w', encoding='utf-8') as f:
            f.write(script_content)
            f.flush()
            os.fsync(f.fileno())
        
        logger.debug(f"Saved script source: {unique_filename}")
        
        # 写入元数据记录
        metadata_file = site_dir / "sources" / "metadata.jsonl"
        metadata_record = {
            "scriptId": script_id,
            "scriptUrl": script_url,
            "filename": unique_filename,
            "contentHash": content_hash,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        with open(metadata_file, 'a', encoding='utf-8') as f:
            f.write(json.dumps(metadata_record, ensure_ascii=False) + '\n')
            f.flush()
            os.fsync(f.fileno())
    
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
            source_map = await self._get_source_map(script_meta['url'], source_map_url, script_id)
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
    
    async def _get_source_map(self, script_url: str, source_map_url: str, script_id: Optional[str] = None) -> Optional[Any]:
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
            
            # 异步持久化source map和源文件
            if self.hostname and script_id:
                # 异步持久化，不等待完成，不阻塞主流程
                asyncio.create_task(self._persist_source_map_async(
                    script_id, source_map_url, source_map_content, source_map
                ))
            
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
    
    async def _persist_source_map_async(self, script_id: str, source_map_url: str,
                                       source_map_content: str, source_map: Any) -> None:
        """异步持久化source map和源文件（完全自管理，零耦合）"""
        if not self.hostname:
            return
            
        async with self.persistence_semaphore:
            try:
                # 使用 asyncio.to_thread 执行文件操作（不含metadata写入）
                metadata_record = await asyncio.to_thread(
                    self._write_source_map_files, 
                    script_id, source_map_url, source_map_content, source_map
                )
                
                # 如果返回了metadata记录，在异步上下文中写入（加锁保护）
                if metadata_record:
                    await self._write_metadata_record(metadata_record)
                    
                logger.debug(f"Source map persisted for script {script_id}")
            except Exception as e:
                logger.warning(f"Source map persistence failed for script {script_id}: {e}")
    
    async def _write_metadata_record(self, metadata_record: Dict[str, Any]) -> None:
        """异步写入metadata记录（加锁保护）"""
        session_dir = self._get_current_session_dir()
        if not session_dir:
            return
            
        metadata_file = session_dir / self.hostname / "source_maps" / "metadata.jsonl"
        
        async with self.metadata_lock:
            try:
                # 使用asyncio.to_thread执行文件写入
                await asyncio.to_thread(self._write_metadata_to_file, metadata_file, metadata_record)
            except Exception as e:
                logger.warning(f"Failed to write metadata record: {e}")
    
    def _write_metadata_to_file(self, metadata_file: Path, metadata_record: Dict[str, Any]) -> None:
        """同步写入metadata到文件"""
        with open(metadata_file, 'a', encoding='utf-8') as f:
            f.write(json.dumps(metadata_record, ensure_ascii=False) + '\n')
            f.flush()
            os.fsync(f.fileno())
    
    def _write_source_map_files(self, script_id: str, source_map_url: str, 
                               source_map_content: str, source_map: Any) -> Optional[Dict[str, Any]]:
        """同步文件写入逻辑（在thread中执行）"""
        session_dir = self._get_current_session_dir()
        if not session_dir:
            logger.warning("No session directory found for source map persistence")
            return None
            
        # 创建目标目录结构
        site_dir = session_dir / self.hostname
        source_maps_dir = site_dir / "source_maps"
        sources_dir = site_dir / "sources"
        
        # 确保目录存在
        source_maps_dir.mkdir(parents=True, exist_ok=True)
        
        # 安全的文件名（移除特殊字符）
        safe_script_id = "".join(c for c in script_id if c.isalnum() or c in "._-")
        source_map_file = source_maps_dir / f"{safe_script_id}.map.json"
        
        # 写入source map文件
        source_map_data = {
            "sourceMapUrl": source_map_url,
            "scriptUrl": self.script_metadata.get(script_id, {}).get("url", ""),
            "sourceMap": json.loads(source_map_content) if isinstance(source_map_content, str) else source_map_content,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        with open(source_map_file, 'w', encoding='utf-8') as f:
            json.dump(source_map_data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        
        # 提取并保存sourcesContent中的源文件
        if hasattr(source_map, 'raw') and isinstance(source_map.raw, dict):
            sources_content = source_map.raw.get('sourcesContent')
            sources = source_map.raw.get('sources', [])
            
            if sources_content and sources:
                sources_dir.mkdir(parents=True, exist_ok=True)
                
                for i, (source_path, content) in enumerate(zip(sources, sources_content)):
                    if content:
                        # 计算内容哈希以避免重复和命名冲突
                        content_hash = hashlib.blake2s(content.encode('utf-8'), digest_size=8).hexdigest()
                        
                        # 使用哈希前缀 + 原始文件名避免冲突：hash_original_name
                        safe_basename = source_path.replace('/', '_').replace('\\', '_')
                        unique_filename = f"{content_hash}_{safe_basename}"
                        source_file = sources_dir / unique_filename
                        
                        # 如果文件已存在且内容相同则跳过（基于哈希去重）
                        if source_file.exists():
                            try:
                                with open(source_file, 'r', encoding='utf-8') as existing:
                                    existing_content = existing.read()
                                    if existing_content == content:
                                        continue  # 内容相同，跳过写入
                            except:
                                pass  # 读取失败，继续写入覆盖
                        
                        # 写入源文件
                        with open(source_file, 'w', encoding='utf-8') as f:
                            f.write(content)
                            f.flush()
                            os.fsync(f.fileno())
        
        # 准备metadata记录（返回给调用者异步写入）
        metadata_record = {
            "scriptId": script_id,
            "sourceMapFile": f"{safe_script_id}.map.json",
            "scriptUrl": self.script_metadata.get(script_id, {}).get("url", ""),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        return metadata_record
    
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
