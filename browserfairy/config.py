"""监控配置管理模块 - 最小化实现，保证向后兼容"""

from pathlib import Path
from typing import List, Optional
from .utils.paths import ensure_data_directory


class MonitorConfig:
    """监控配置管理 - 最小化实现，保证向后兼容"""
    
    # 预设模式定义（根据专家建议调整）
    OUTPUT_PRESETS = {
        'all': ['*'],  # 默认，收集所有
        'errors-only': ['console:error', 'exception', 'network:failed'],
        'performance': ['memory', 'gc', 'network:complete'],  # 性能分析需要网络耗时
        'minimal': ['console:error', 'exception'],
        'ai-debug': ['console:error', 'exception', 'network:failed', 'memory']
    }
    
    def __init__(self, data_dir: Optional[str] = None, 
                 output: str = 'all'):
        """初始化配置
        
        Args:
            data_dir: 数据目录路径，None则使用默认
            output: 输出过滤器，预设名或逗号分隔列表
        """
        self.data_dir = self._resolve_data_dir(data_dir)
        self.output_filters = self._parse_output(output)
        
    def _resolve_data_dir(self, data_dir: Optional[str]) -> Path:
        """解析数据目录"""
        if data_dir is None:
            return ensure_data_directory()  # 使用默认
        
        # 支持相对路径和绝对路径
        path = Path(data_dir).expanduser().resolve()
        path.mkdir(parents=True, exist_ok=True)
        return path
        
    def _parse_output(self, output: str) -> List[str]:
        """解析输出过滤器"""
        if output in self.OUTPUT_PRESETS:
            return self.OUTPUT_PRESETS[output]
        
        # 自定义列表
        return [f.strip() for f in output.split(',')]
        
    def should_collect(self, data_type: str, level: Optional[str] = None) -> bool:
        """判断是否应该收集某类数据
        
        Args:
            data_type: 数据类型（console, memory, network等）
            level: 可选的级别（error, warn, failed, complete, start等）
            
        Returns:
            是否应该收集
        """
        # 通配符
        if '*' in self.output_filters:
            return True
            
        # 完全匹配
        if data_type in self.output_filters:
            return True
            
        # 带级别匹配
        if level and f"{data_type}:{level}" in self.output_filters:
            return True
            
        return False