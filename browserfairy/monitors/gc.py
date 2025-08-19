"""垃圾回收事件监控器 - 收集GC原始数据"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional, Callable, Dict, Any

from ..core.connector import ChromeConnector
from ..utils.event_id import make_event_id

logger = logging.getLogger(__name__)


class GCMonitor:
    """垃圾回收事件监控器 - 通过Performance指标和Console日志检测GC事件"""
    
    def __init__(self, connector: ChromeConnector, session_id: str,
                 event_queue: asyncio.Queue, status_callback: Optional[Callable] = None):
        self.connector = connector
        self.session_id = session_id
        self.event_queue = event_queue
        self.status_callback = status_callback
        self.hostname: Optional[str] = None
        
        # GC监控状态
        self.last_gc_metrics: Dict[str, Any] = {}
        self.monitoring_active = False
        
        # GC相关指标名称（基于Chrome CDP文档）
        self.gc_metric_names = {
            "MajorGCCount": "major",   # 注意：多数环境不可用，仅作尝试性检测
            "MinorGCCount": "minor",   # 注意：多数环境不可用，仅作尝试性检测
            # 使用与现有实现一致的堆指标名（与 MemoryCollector 保持一致）
            "JSHeapUsedSize": "heap_size_change",  # 间接GC指标：堆使用量显著下降
        }
        
    def set_hostname(self, hostname: str) -> None:
        """设置hostname用于数据分组"""
        self.hostname = hostname
    
    async def start_monitoring(self) -> None:
        """启动GC事件监控"""
        try:
            # 启用Performance domain（如果还未启用）
            await self.connector.call("Performance.enable", session_id=self.session_id, timeout=3.0)
            
            # 启用Runtime domain监听Console中的GC日志
            await self.connector.call("Runtime.enable", session_id=self.session_id, timeout=3.0)
            
            # 注册Console事件监听器
            self.connector.on_event("Runtime.consoleAPICalled", self._on_console_message)
            
            # 获取初始GC指标基线
            await self._update_gc_baseline()
            
            self.monitoring_active = True
            logger.debug(f"GC monitoring started for {self.hostname}")
            
        except Exception as e:
            logger.warning(f"Failed to start GC monitoring for {self.hostname}: {e}")
            # 不抛异常，优雅降级
    
    async def stop_monitoring(self) -> None:
        """停止GC事件监控"""
        self.monitoring_active = False
        
        # 移除事件监听器
        self.connector.off_event("Runtime.consoleAPICalled", self._on_console_message)
        
        logger.debug(f"GC monitoring stopped for {self.hostname}")
    
    async def check_gc_metrics(self) -> None:
        """检查GC指标变化（定期调用，与内存采集同步）"""
        if not self.monitoring_active:
            return
            
        try:
            # 获取当前Performance指标
            metrics_response = await self.connector.call(
                "Performance.getMetrics", 
                session_id=self.session_id,
                timeout=3.0
            )
            
            current_metrics = {m["name"]: m["value"] for m in metrics_response.get("metrics", [])}
            
            # 检查GC相关指标的变化
            gc_events = self._detect_gc_changes(current_metrics)
            
            # 发出检测到的GC事件
            for gc_event in gc_events:
                await self._emit_gc_event(gc_event)
            
            # 更新基线
            self.last_gc_metrics = current_metrics
            
        except Exception as e:
            logger.debug(f"GC metrics check failed for {self.hostname}: {e}")
    
    def _detect_gc_changes(self, current_metrics: Dict[str, Any]) -> list:
        """检测GC指标变化，推断GC事件"""
        gc_events = []
        
        if not self.last_gc_metrics:
            # 首次运行，无基线比较
            return gc_events
        
        # 1) 计数型指标：尝试性检测（多数环境不可用）
        for metric_name, gc_type in self.gc_metric_names.items():
            if not metric_name.endswith("Count"):
                continue
            if metric_name in current_metrics and metric_name in self.last_gc_metrics:
                current_value = current_metrics[metric_name]
                last_value = self.last_gc_metrics[metric_name]
                if current_value and last_value and current_value > last_value:
                    gc_events.append({
                        "type": gc_type,
                        "metric_name": metric_name,
                        "count_increase": current_value - last_value,
                        "total_count": current_value,
                        "detected_via": "performance_metrics"
                    })

        # 2) 堆内存显著下降：可靠的间接信号（与 MemoryCollector 指标一致）
        heap_metric = "JSHeapUsedSize"
        if heap_metric in current_metrics and heap_metric in self.last_gc_metrics:
            current_value = current_metrics[heap_metric]
            last_value = self.last_gc_metrics[heap_metric]
            if current_value is not None and last_value is not None:
                size_decrease = last_value - current_value
                if size_decrease > 10 * 1024 * 1024:  # 10MB 阈值
                    gc_events.append({
                        "type": "heap_decrease_gc",
                        "metric_name": heap_metric,
                        "size_decrease_mb": size_decrease / (1024 * 1024),
                        "current_size_mb": current_value / (1024 * 1024),
                        "detected_via": "heap_size_analysis"
                    })

        return gc_events
    
    async def _on_console_message(self, params: dict) -> None:
        """处理Console消息，寻找GC相关日志"""
        try:
            # 检查sessionId过滤（如果有的话）
            if params.get("sessionId") and params.get("sessionId") != self.session_id:
                return
                
            # 从Console参数中提取GC信息
            gc_message = self._extract_gc_info_from_console(params.get("args", []))
            
            if gc_message:
                await self._emit_gc_event({
                    "type": "console_gc",
                    "message": gc_message,
                    "console_type": params.get("type", "log"),
                    "detected_via": "console_log"
                })
                
        except Exception as e:
            logger.debug(f"GC console message processing failed for {self.hostname}: {e}")
    
    def _extract_gc_info_from_console(self, args: list) -> Optional[str]:
        """从Console参数中提取GC相关信息"""
        for arg in args:
            if arg.get("type") == "string":
                value = arg.get("value", "")
                if isinstance(value, str):
                    value_lower = value.lower()
                    # 查找GC相关关键词
                    gc_keywords = [
                        "gc", "garbage collect", "heap collect", 
                        "major gc", "minor gc", "full gc",
                        "scavenge", "mark-sweep", "mark-compact"
                    ]
                    if any(keyword in value_lower for keyword in gc_keywords):
                        return value[:500]  # 截断长消息，保留前500字符
        return None
    
    async def _emit_gc_event(self, gc_info: Dict[str, Any]) -> None:
        """发出GC事件到队列"""
        try:
            timestamp = datetime.now(timezone.utc).isoformat()
            gc_event = {
                "timestamp": timestamp,
                "type": "gc_event",
                "hostname": self.hostname,
                "data": gc_info
            }
            
            # Add event_id for deduplication
            try:
                gc_type = gc_info.get("type", "unknown")
                # Use GC type and key metrics to generate unique ID
                if gc_type == "heap_decrease_gc":
                    # For heap-based GC detection, include size decrease
                    gc_event["event_id"] = make_event_id(
                        "gc_event",
                        self.hostname or "",
                        timestamp,
                        gc_type,
                        gc_info.get("size_decrease_mb", 0),
                        gc_info.get("current_size_mb", 0)
                    )
                elif gc_type == "console_gc":
                    # For console-based GC detection, include message
                    gc_event["event_id"] = make_event_id(
                        "gc_event",
                        self.hostname or "",
                        timestamp,
                        gc_type,
                        gc_info.get("message", "")[:50]  # First 50 chars of message
                    )
                else:
                    # For counter-based GC (major/minor), include count increase
                    gc_event["event_id"] = make_event_id(
                        "gc_event",
                        self.hostname or "",
                        timestamp,
                        gc_type,
                        gc_info.get("count_increase", 0),
                        gc_info.get("current_count", 0)
                    )
            except Exception:
                pass  # Continue without event_id if generation fails
            
            # 加入事件队列
            self.event_queue.put_nowait(("gc", gc_event))
            
            # 状态回调通知（仅对重要的GC事件）
            if (self.status_callback and 
                gc_info.get("type") in ["major", "minor", "heap_decrease_gc"]):
                try:
                    self.status_callback("gc_detected", {
                        "gc_type": gc_info["type"],
                        "hostname": self.hostname,
                        "details": gc_info.get("count_increase") or gc_info.get("size_decrease_mb")
                    })
                except Exception as e:
                    logger.warning(f"Error in GC status callback: {e}")
                
        except asyncio.QueueFull:
            logger.warning(f"GC event queue full, dropping event for {self.hostname}")
        except Exception as e:
            logger.debug(f"Failed to emit GC event for {self.hostname}: {e}")
    
    async def _update_gc_baseline(self) -> None:
        """更新GC指标基线"""
        try:
            metrics_response = await self.connector.call(
                "Performance.getMetrics",
                session_id=self.session_id,
                timeout=3.0
            )
            
            self.last_gc_metrics = {m["name"]: m["value"] for m in metrics_response.get("metrics", [])}
            logger.debug(f"GC baseline updated for {self.hostname}: {len(self.last_gc_metrics)} metrics")
            
        except Exception as e:
            logger.debug(f"Failed to update GC baseline for {self.hostname}: {e}")
            self.last_gc_metrics = {}
