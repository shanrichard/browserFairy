"""BrowserFairy完整监控服务 - 极简协调器模式"""

from datetime import datetime
from typing import Optional, Callable
import asyncio
import importlib


class BrowserFairyService:
    """完整监控服务 - 极简协调器模式"""
    
    def __init__(self, log_file: Optional[str] = None, enable_source_map: bool = False):
        self.chrome_manager = None
        self.exit_event = asyncio.Event()
        self.log_file = log_file
        self.enable_source_map = enable_source_map
        
    async def start_monitoring(self, duration: Optional[int] = None) -> int:
        """一键启动完整监控服务"""
        try:
            # 1. 启动独立Chrome实例
            from .core.chrome_instance import ChromeInstanceManager
            self.chrome_manager = ChromeInstanceManager()
            host_port = await self.chrome_manager.launch_isolated_chrome()
            host, port = host_port.split(":")
            
            # 2. 记录启动日志
            if self.log_file:
                self._log_message(f"Chrome started on port {port}")
                self._log_message("Monitoring started")
            
            # 3. 调用现有监控（使用动态导入避免循环依赖）
            return await self._run_monitoring(host, int(port), duration)
            
        except Exception as e:
            if self.log_file:
                self._log_message(f"ERROR: Service startup failed: {e}")
            return 1
        finally:
            await self._cleanup()
    
    async def _run_monitoring(self, host: str, port: int, duration: Optional[int]) -> int:
        """调用现有监控逻辑（避免循环导入）"""
        # 动态导入避免循环依赖
        cli_module = importlib.import_module('browserfairy.cli')
        monitor_func = getattr(cli_module, 'monitor_comprehensive')
        
        # 创建状态回调（只处理实际会触发的事件）
        status_callback = self._create_log_callback() if self.log_file else None
        
        return await monitor_func(
            host=host,
            port=port,
            duration=duration,
            status_callback=status_callback,
            exit_event=self.exit_event,
            enable_source_map=self.enable_source_map
        )
    
    def _create_log_callback(self) -> Callable:
        """创建日志回调函数 - 只处理monitor_comprehensive实际发送的事件"""
        def log_callback(event_type: str, payload: dict):
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            # 只处理现有monitor_comprehensive实际会发送的事件
            if event_type == "console_error":
                message = f"Console Error: {payload.get('message', '')}"
            elif event_type == "large_request":
                message = f"Large Request: {payload.get('url', '')} ({payload.get('size_mb', 0):.1f}MB)"
            elif event_type == "large_response":
                message = f"Large Response: {payload.get('url', '')} ({payload.get('size_mb', 0):.1f}MB)"
            elif event_type == "correlation_found":
                message = f"Correlation: {payload.get('count', 0)} events correlated"
            else:
                message = f"{event_type}: {payload}"
            
            try:
                with open(self.log_file, "a", encoding="utf-8") as f:
                    f.write(f"[{timestamp}] {message}\n")
            except:
                pass
        
        return log_callback
    
    def _log_message(self, message: str):
        """记录简单日志消息"""
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(f"[{timestamp}] {message}\n")
        except:
            pass
    
    async def _cleanup(self):
        """清理资源"""
        try:
            if self.chrome_manager:
                await self.chrome_manager.cleanup()
        except:
            pass  # 静默清理
