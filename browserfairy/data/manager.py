"""数据管理协调器，集成文件写入和存储监控"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, Callable
from urllib.parse import urlparse

from ..core.connector import ChromeConnector
from ..utils.paths import get_data_directory
from .writer import DataWriter
from ..monitors.storage import StorageMonitor

logger = logging.getLogger(__name__)


class DataManager:
    """数据管理协调器，集成文件写入和存储监控"""
    
    def __init__(self, connector: ChromeConnector, data_dir: Optional[Path] = None):
        self.connector = connector
        self.data_dir = Path(data_dir) if data_dir else get_data_directory()  # 确保是Path对象
        self.session_dir = self._create_session_directory()
        self.data_writer = DataWriter(self.session_dir)
        self.storage_monitor = StorageMonitor(connector)
        self.running = False
        # 维护 origin → hostname 的映射，便于将配额数据同步到站点目录
        self.origin_to_hostname: Dict[str, str] = {}
    
    def _create_session_directory(self) -> Path:
        """创建会话目录"""
        session_name = f"session_{datetime.now().strftime('%Y-%m-%d_%H%M%S')}"
        session_dir = self.data_dir / session_name
        session_dir.mkdir(parents=True, exist_ok=True)
        return session_dir
        
    async def start(self) -> None:
        """启动数据管理（与现有模式一致的方法名）"""
        if self.running:
            return
            
        # 创建overview.json
        await self._create_session_overview()
        
        # 启动存储监控，设置回调到文件写入
        logger.debug("DataManager.start: initializing StorageMonitor")
        self.storage_monitor.set_data_callback(self._on_storage_data)
        await self.storage_monitor.start()
        
        # 存储监控流程说明：
        # 1. MemoryCollector收集内存数据时，通过write_memory_data触发origin跟踪
        # 2. StorageMonitor定期对tracked_origins调用Storage.getUsageAndQuota
        # 3. 配额数据通过_on_storage_data写入storage_global.jsonl
        
        self.running = True
        
    async def stop(self) -> None:
        """停止数据管理和清理"""
        self.running = False
        
        # 延迟模式下确保数据落盘（单行改动，不影响默认行为）
        if hasattr(self, 'data_writer') and self.data_writer:
            await self.data_writer.force_sync_pending()
            
        await self.storage_monitor.stop()
    
    def _extract_origin_from_url(self, url: str) -> Optional[str]:
        """从URL提取origin（修正：正确处理scheme/port，不假设https）"""
        try:
            parsed = urlparse(url)
            
            if not parsed.scheme or not parsed.hostname:
                return None
            
            # 构造origin：scheme://hostname[:port]
            origin = f"{parsed.scheme}://{parsed.hostname}"
            if parsed.port and parsed.port != (443 if parsed.scheme == 'https' else 80):
                origin += f":{parsed.port}"
            
            return origin
            
        except Exception as e:
            logger.debug(f"Failed to extract origin from URL {url}: {e}")
            return None
    
    async def _on_storage_data(self, data_type: str, storage_data: Dict[str, Any]) -> None:
        """存储监控数据回调处理（最小实现版本）"""
        if not self.running:
            return
        
        if data_type == "quota":
            # 配额数据写入storage_global.jsonl
            logger.debug(f"DataManager._on_storage_data: writing global quota for origin={storage_data.get('origin')}")
            await self.data_writer.append_jsonl("storage_global.jsonl", storage_data)
            # 同步写入到站点目录（若能解析到对应hostname）
            origin = storage_data.get("origin")
            hostname = None
            if origin:
                hostname = self.origin_to_hostname.get(origin)
                if not hostname:
                    # 回退：从 origin 直接解析 hostname
                    try:
                        parsed = urlparse(origin)
                        hostname = parsed.hostname
                    except Exception:
                        hostname = None
            if hostname:
                site_record = dict(storage_data)
                site_record["hostname"] = hostname
                file_path = f"{hostname}/storage.jsonl"
                logger.debug(f"DataManager._on_storage_data: writing per-site quota hostname={hostname}")
                await self.data_writer.append_jsonl(file_path, site_record)
            else:
                logger.debug("DataManager._on_storage_data: no hostname mapping for origin; skip per-site write")
        # 其他类型（如IndexedDB事件）暂不处理，留到后续版本
    
    async def _create_session_overview(self) -> None:
        """创建会话概览文件"""
        overview = {
            "sessionId": self.session_dir.name,
            "startTime": datetime.now().isoformat(),
            "version": "1.5.0",
            "features": ["memory_monitoring", "storage_quota_monitoring", "comprehensive_monitoring"],
            "dataTypes": {
                "memory.jsonl": "Memory snapshots per hostname",
                "console.jsonl": "Console logs and exceptions per hostname",
                "network.jsonl": "Network request monitoring per hostname",
                "correlations.jsonl": "Cross-layer correlation analysis per hostname",
                "storage_global.jsonl": "Storage quota data for all origins"
            }
        }
        
        overview_path = self.session_dir / "overview.json"
        with open(overview_path, 'w', encoding='utf-8') as f:
            json.dump(overview, f, indent=2, ensure_ascii=False)
        
    async def write_memory_data(self, hostname: str, memory_data: Dict[str, Any]) -> None:
        """来自MemoryCollector的数据写入接口"""
        if not self.running:
            return
            
        file_path = f"{hostname}/memory.jsonl"
        logger.debug(f"DataManager.write_memory_data: append to {file_path}")
        await self.data_writer.append_jsonl(file_path, memory_data)
        
        # 触发该hostname的存储监控（从内存数据的URL中正确提取origin）
        url = memory_data.get("url", "")
        if url:
            origin = self._extract_origin_from_url(url)
            if origin:
                # 记录映射并首次立即采集
                prev = self.origin_to_hostname.get(origin)
                if prev and prev != hostname:
                    logger.debug(f"DataManager: origin {origin} remapped from {prev} to {hostname}")
                self.origin_to_hostname[origin] = hostname
                logger.debug(f"DataManager: tracking origin {origin} for hostname {hostname}")
                await self.storage_monitor.track_origin(origin)
    
    async def write_console_data(self, hostname: str, console_data: Dict[str, Any]) -> None:
        """Console data writing (new method for comprehensive monitoring)."""
        if not self.running:
            return
        file_path = f"{hostname}/console.jsonl"
        await self.data_writer.append_jsonl(file_path, console_data)
    
    async def write_network_data(self, hostname: str, network_data: Dict[str, Any]) -> None:
        """Network data writing (new method for comprehensive monitoring)."""
        if not self.running:
            return
        file_path = f"{hostname}/network.jsonl"
        await self.data_writer.append_jsonl(file_path, network_data)
    
    async def write_correlation_data(self, hostname: str, correlation_data: Dict[str, Any]) -> None:
        """Correlation analysis data writing (new method for comprehensive monitoring)."""
        if not self.running:
            return
        file_path = f"{hostname}/correlations.jsonl"
        await self.data_writer.append_jsonl(file_path, correlation_data)
