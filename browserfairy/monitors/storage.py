"""浏览器存储监控，复用ChromeConnector架构"""

import asyncio
import logging
import random
from datetime import datetime, timezone
from typing import Callable, Dict, Optional, Set, Any

from ..core.connector import ChromeConnector

logger = logging.getLogger(__name__)


class StorageMonitor:
    """浏览器存储监控，复用ChromeConnector架构"""
    
    def __init__(self, connector: ChromeConnector):
        self.connector = connector
        self.quota_check_interval = 30.0
        self.quota_task: Optional[asyncio.Task] = None
        self.data_callback: Optional[Callable[[str, Dict], None]] = None
        self.tracked_origins: Set[str] = set()
        self.running = False
        
    async def start(self) -> None:
        """启动存储监控（与MemoryCollector一致的方法名）"""
        if self.running:
            return
            
        # 标记为运行中，并启动配额检查任务（即使Storage.enable不可用也要运行）
        self.running = True
        self.quota_task = asyncio.create_task(self._quota_monitoring_loop())
        logger.debug("StorageMonitor.start: quota monitoring loop started")
        
        # 尝试启用存储事件监听（可选）
        try:
            await self._enable_storage_events()
        except Exception as e:
            logger.debug(f"Storage events not available: {e}")
    
    async def _enable_storage_events(self) -> None:
        """启用存储domain事件监听"""
        # 必须先调用Storage.enable才能接收事件推送（某些环境不支持此方法）
        await self.connector.call("Storage.enable")
        
        # 可选：设置事件处理器（需要connector支持事件监听）
        # 当前阶段暂不实现IndexedDB事件处理，专注配额监控
        
    async def stop(self) -> None:
        """停止监控和清理（复用现有清理模式）"""
        self.running = False
        
        if self.quota_task:
            self.quota_task.cancel()
            try:
                await self.quota_task
            except asyncio.CancelledError:
                pass
            self.quota_task = None
    
    async def track_origin(self, origin: str) -> None:
        """为origin启用IndexedDB监控，并在首次跟踪时立即采集一次配额。"""
        if not self.running or origin in self.tracked_origins:
            return
            
        # 尝试启用IndexedDB跟踪（可失败），但不影响后续立即采集
        try:
            await self.connector.call(
                "Storage.trackIndexedDBForOrigin",
                {"origin": origin}
            )
            logger.debug(f"StorageMonitor.track_origin: trackIndexedDB enabled for {origin}")
        except Exception as e:
            logger.debug(f"StorageMonitor.track_origin: trackIndexedDB not available for {origin}: {e}")

        # 无论是否支持IndexedDB事件，都加入跟踪集合并立即采集一次
        self.tracked_origins.add(origin)
        logger.debug(f"StorageMonitor.track_origin: started tracking {origin}")

        try:
            quota_data = await self._collect_quota_info(origin)
            if quota_data and self.data_callback:
                logger.debug(f"StorageMonitor.track_origin: immediate quota collected for {origin}")
                await self._safe_callback("quota", quota_data)
        except Exception as e:
            logger.debug(f"StorageMonitor.track_origin: immediate quota failed for {origin}: {e}")
    
    async def _quota_monitoring_loop(self) -> None:
        """配额监控循环（复用MemoryCollector采样模式）"""
        # 初始随机抖动，复用现有模式
        initial_jitter = random.uniform(0, 2.0)
        await asyncio.sleep(initial_jitter)
        
        while self.running:
            try:
                # 从已跟踪的origins中选择一个进行配额检查
                if self.tracked_origins:
                    origin = next(iter(self.tracked_origins))
                    quota_data = await self._collect_quota_info(origin)
                    if quota_data and self.data_callback:
                        logger.debug(f"StorageMonitor.loop: quota collected for {origin}")
                        await self._safe_callback("quota", quota_data)
                
            except Exception as e:
                logger.debug(f"Storage quota collection failed: {e}")
                
            # 等待下个检查周期
            await asyncio.sleep(self.quota_check_interval)
    
    async def _collect_quota_info(self, origin: str) -> Optional[Dict[str, Any]]:
        """收集指定origin的存储配额信息（修正：使用Browser级API）"""
        try:
            # 使用Storage.getUsageAndQuota (Browser级，无需session_id)
            result = await self.connector.call(
                "Storage.getUsageAndQuota",
                {"origin": origin}
            )
            
            quota = result.get("quota", 0)
            usage = result.get("usage", 0)
            usage_breakdown = result.get("usageBreakdown", [])
            
            # 转换usageBreakdown为字典格式
            usage_details = {}
            for item in usage_breakdown:
                storage_type = item.get("storageType", "unknown")
                usage_details[storage_type] = item.get("usage", 0)
                
            # 格式化输出，与内存数据格式保持一致
            record = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "type": "storage_quota", 
                "origin": origin,
                "data": {
                    "quota": quota,
                    "usage": usage,
                    "usageRate": (usage / quota) if quota > 0 else 0,
                    "usageDetails": usage_details,
                    "warningLevel": self._calculate_warning_level(usage, quota)
                }
            }
            logger.debug(f"StorageMonitor._collect_quota_info: origin={origin} usage={usage} quota={quota}")
            return record
            
        except Exception as e:
            logger.debug(f"Failed to collect quota info for {origin}: {e}")
            return None
    
    async def _safe_callback(self, data_type: str, data: Dict[str, Any]) -> None:
        """安全调用数据回调，避免回调异常影响监控"""
        if not self.data_callback:
            return
        
        try:
            if asyncio.iscoroutinefunction(self.data_callback):
                await self.data_callback(data_type, data)
            else:
                self.data_callback(data_type, data)
        except Exception as e:
            logger.warning(f"Storage data callback failed: {e}")
    
    def _calculate_warning_level(self, usage: int, quota: int) -> str:
        """计算配额使用警告级别"""
        if quota <= 0:
            return "unknown"
        
        usage_rate = usage / quota
        if usage_rate >= 0.9:
            return "critical"
        elif usage_rate >= 0.75:
            return "warning" 
        else:
            return "normal"
    
    def set_data_callback(self, callback: Callable[[str, Dict[str, Any]], None]) -> None:
        """设置数据回调函数"""
        self.data_callback = callback
