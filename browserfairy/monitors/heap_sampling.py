"""内存采样监控器 - HeapProfiler轻量级采样分析"""

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Optional, Callable, Dict, Any, List
from collections import defaultdict

from ..core.connector import ChromeConnector
from ..utils.event_id import make_event_id

logger = logging.getLogger(__name__)

# 采样配置常量（保守设置，优先保证性能稳定性）
HEAP_SAMPLING_INTERVAL = 65536  # bytes, 64KB采样间隔（比Chrome默认32KB更保守）
HEAP_PROFILE_COLLECTION_INTERVAL = 60.0  # seconds, 60秒收集周期（更保守）  
HEAP_SAMPLING_DURATION_LIMIT = 600.0  # seconds, 10分钟重启（减少重启开销）
HEAP_PROFILE_MAX_NODES = 1000  # 节点数上限
HEAP_PROFILE_MAX_TOP_ALLOCATORS = 10  # top函数限制


class HeapSamplingMonitor:
    """HeapProfiler采样监控器 - 遵循GCMonitor架构模式"""
    
    def __init__(self, connector: ChromeConnector, session_id: str,
                 event_queue: asyncio.Queue, target_id: str = None,
                 status_callback: Optional[Callable] = None):
        self.connector = connector
        self.session_id = session_id 
        self.event_queue = event_queue
        self.target_id = target_id  # 新增：用于数据关联
        self.status_callback = status_callback
        self.hostname: Optional[str] = None
        
        # 采样状态管理
        self.sampling_active = False
        self.last_sampling_start = 0.0
        self.collection_task: Optional[asyncio.Task] = None
        
    def set_hostname(self, hostname: str) -> None:
        """设置hostname用于数据分组"""
        self.hostname = hostname
        
    async def start_monitoring(self) -> None:
        """启动HeapProfiler采样监控 - 遵循GCMonitor模式"""
        try:
            # 启用HeapProfiler domain
            await self.connector.call("HeapProfiler.enable", 
                                     session_id=self.session_id, timeout=3.0)
            
            # 启动采样
            if await self._start_heap_sampling():
                self.sampling_active = True
                # 启动独立的profile收集任务
                self.collection_task = asyncio.create_task(self._profile_collection_loop())
                logger.debug(f"Heap sampling monitoring started for {self.hostname}")
            
        except Exception as e:
            logger.warning(f"Failed to start heap sampling for {self.hostname}: {e}")
            # 优雅降级，不抛异常
            
    async def stop_monitoring(self) -> None:
        """停止HeapProfiler采样监控"""
        self.sampling_active = False
        
        # 取消收集任务
        if self.collection_task:
            self.collection_task.cancel()
            try:
                await self.collection_task
            except asyncio.CancelledError:
                pass
            self.collection_task = None
            
        # 停止采样
        try:
            await self.connector.call("HeapProfiler.stopSampling",
                                     session_id=self.session_id, timeout=3.0)
        except Exception as e:
            logger.debug(f"Failed to stop heap sampling: {e}")
            
        logger.debug(f"Heap sampling monitoring stopped for {self.hostname}")

    async def _start_heap_sampling(self) -> bool:
        """启动HeapProfiler采样"""
        try:
            await self.connector.call("HeapProfiler.startSampling", {
                "samplingInterval": HEAP_SAMPLING_INTERVAL
            }, session_id=self.session_id, timeout=5.0)
            
            self.last_sampling_start = time.time()
            return True
            
        except Exception as e:
            logger.debug(f"Failed to start heap sampling: {e}")
            return False
    
    async def _profile_collection_loop(self):
        """独立的profile收集循环 - 类似GCMonitor.check_gc_metrics的调用模式"""
        while self.sampling_active:
            try:
                await asyncio.sleep(HEAP_PROFILE_COLLECTION_INTERVAL)
                
                # 检查是否需要重启采样（防止数据积累过大）
                if time.time() - self.last_sampling_start > HEAP_SAMPLING_DURATION_LIMIT:
                    await self._restart_heap_sampling()
                
                # 收集profile数据
                await self._collect_heap_profile()
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"Heap profile collection error: {e}")
                await asyncio.sleep(5.0)  # 错误后等待5秒
    
    async def _restart_heap_sampling(self):
        """重启采样，清理积累数据"""
        try:
            await self.connector.call("HeapProfiler.stopSampling",
                                     session_id=self.session_id, timeout=3.0)
            await asyncio.sleep(0.1)  # 短暂延迟
            await self._start_heap_sampling()
            logger.debug(f"Heap sampling restarted for {self.hostname}")
        except Exception as e:
            logger.debug(f"Failed to restart heap sampling: {e}")

    async def _collect_heap_profile(self):
        """收集并解析heap profile数据 - 发送到event_queue"""
        try:
            # 获取采样profile
            profile_response = await self.connector.call(
                "HeapProfiler.getSamplingProfile",
                session_id=self.session_id, 
                timeout=10.0  # 较长超时，因为可能数据量大
            )
            
            profile_data = profile_response.get("profile", {})
            if not profile_data:
                logger.debug("Empty heap profile received")
                return
                
            # 解析profile数据
            parsed_result = self._parse_heap_profile(profile_data)
            if not parsed_result:
                return
                
            # 构造事件数据（遵循现有事件格式）
            heap_event = {
                "type": "heap_sampling",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "hostname": self.hostname,
                "targetId": self.target_id,  # 新增：便于数据关联和归档
                "sessionId": self.session_id,
                "sampling_config": {
                    "sampling_interval": HEAP_SAMPLING_INTERVAL,
                    "duration_ms": int((time.time() - self.last_sampling_start) * 1000)
                },
                "profile_summary": {
                    "total_size": parsed_result["total_size"],
                    "total_samples": parsed_result["total_samples"], 
                    "node_count": parsed_result["node_count"],
                    "max_allocation_size": parsed_result["max_allocation_size"]
                },
                "top_allocators": parsed_result["top_allocators"],
                "event_id": make_event_id("heap", self.hostname, int(time.time() * 1000))
            }
            
            # 发送到event_queue（遵循GCMonitor._emit_gc_event模式）
            try:
                self.event_queue.put_nowait(("heap_sampling", heap_event))
                
                # 状态回调通知（增加保护，避免回调异常中断流程）
                if self.status_callback:
                    try:
                        self.status_callback("heap_profile_collected", {
                            "hostname": self.hostname,
                            "total_size": parsed_result["total_size"],
                            "sample_count": parsed_result["total_samples"]
                        })
                    except Exception as e:
                        logger.warning(f"Error in heap_profile_collected status callback: {e}")
                    
            except asyncio.QueueFull:
                logger.warning("Heap sampling event queue full, dropping profile")
                
        except Exception as e:
            logger.debug(f"Failed to collect heap profile: {e}")

    def _parse_heap_profile(self, profile_data: dict) -> Optional[Dict[str, Any]]:
        """解析HeapProfiler复杂数据结构 - 核心算法"""
        try:
            head = profile_data.get("head", {})
            samples = profile_data.get("samples", [])
            
            if not samples or not head:
                return None
                
            # 1. 构建node映射（递归遍历，深度限制防止栈溢出）
            nodes_map = {}
            self._build_nodes_map(head, nodes_map, max_depth=20)
            
            # 节点数量控制（防止数据过大）
            if len(nodes_map) > HEAP_PROFILE_MAX_NODES:
                logger.debug(f"Heap profile too large ({len(nodes_map)} nodes), truncating")
                # 截断策略：保留前HEAP_PROFILE_MAX_NODES个节点
                nodes_map = dict(list(nodes_map.items())[:HEAP_PROFILE_MAX_NODES])
            
            # 2. 聚合samples，按nodeId统计分配
            allocation_stats = defaultdict(lambda: {"total_size": 0, "sample_count": 0})
            total_size = 0
            max_size = 0
            
            for sample in samples:
                node_id = sample.get("nodeId")
                size = sample.get("size", 0)
                if node_id is not None and size > 0:
                    allocation_stats[node_id]["total_size"] += size
                    allocation_stats[node_id]["sample_count"] += 1
                    total_size += size
                    max_size = max(max_size, size)
            
            # 3. 提取热点函数（top N，按分配大小排序）
            top_allocators = []
            sorted_allocations = sorted(
                allocation_stats.items(),
                key=lambda x: x[1]["total_size"], 
                reverse=True
            )[:HEAP_PROFILE_MAX_TOP_ALLOCATORS]
            
            for node_id, stats in sorted_allocations:
                if node_id in nodes_map:
                    node = nodes_map[node_id]
                    call_frame = node.get("callFrame", {})
                    
                    # 提取函数信息（截断长字符串）
                    function_name = call_frame.get("functionName", "anonymous")[:100]
                    script_url = call_frame.get("url", "unknown")[:200]
                    
                    top_allocators.append({
                        "function_name": function_name,
                        "script_url": script_url,
                        "line_number": call_frame.get("lineNumber", 0),
                        "column_number": call_frame.get("columnNumber", 0),
                        "self_size": stats["total_size"],
                        "sample_count": stats["sample_count"],
                        "allocation_percentage": round(stats["total_size"] / total_size * 100, 2) if total_size > 0 else 0
                    })
            
            return {
                "total_samples": len(samples),
                "node_count": len(nodes_map),
                "total_size": total_size,
                "max_allocation_size": max_size,
                "top_allocators": top_allocators
            }
            
        except Exception as e:
            logger.debug(f"Failed to parse heap profile: {e}")
            return None
    
    def _build_nodes_map(self, node: dict, nodes_map: dict, depth: int = 0, max_depth: int = 20) -> None:
        """递归构建节点映射，严格控制深度防止栈溢出"""
        if depth > max_depth:
            return
            
        node_id = node.get("id")
        if node_id is not None:
            nodes_map[node_id] = node
            
        # 递归处理子节点
        for child in node.get("children", []):
            if len(nodes_map) >= HEAP_PROFILE_MAX_NODES:
                break  # 节点数量限制
            self._build_nodes_map(child, nodes_map, depth + 1, max_depth)
