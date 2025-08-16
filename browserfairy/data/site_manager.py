"""网站数据管理器 - 按现有结构读取和分析网站数据"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Generator, Any

from ..utils.paths import get_data_directory

logger = logging.getLogger(__name__)


def read_jsonl_data(file_path: Path) -> Generator[Dict[str, Any], None, None]:
    """逐行读取JSONL - 生成器模式避免一次性加载"""
    if not file_path.exists():
        return  # 文件缺失直接跳过，不报错
        
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    # 忽略坏行，继续处理下一行
                    continue
    except Exception:
        # 文件读取失败，静默跳过
        return


def calculate_memory_stats(data_generator: Generator[Dict[str, Any], None, None]) -> Dict[str, Any]:
    """计算内存统计 - 使用生成器避免一次性加载"""
    values = []
    count = 0
    
    for record in data_generator:
        try:
            memory = record.get("memory", {})
            js_heap = memory.get("jsHeap", {})
            used = js_heap.get("used", 0)
            if used > 0:
                values.append(used)
                count += 1
                
            # 软上限：避免内存冲击，超过100k条就截断
            if count >= 100000:
                break
        except Exception:
            # 忽略坏行，继续处理
            continue
    
    if not values:
        return {"count": 0}
    
    # 简单排序法计算P95
    values.sort()
    n = len(values)
    p95_index = int(0.95 * (n - 1))
    
    return {
        "count": n,
        "min": values[0],
        "max": values[-1],
        "avg": sum(values) / n,  # 使用浮点除法保持精度
        "p95": values[p95_index]
    }


def normalize_hostname(hostname: str) -> str:
    """极简hostname规范化 - 只处理www和m前缀"""
    if not hostname:
        return "unknown"
    
    hostname = hostname.lower()
    
    # 只移除www和m前缀，不处理api等（避免误合并不同服务）
    if hostname.startswith("www."):
        hostname = hostname[4:]
    elif hostname.startswith("m."):
        hostname = hostname[2:]
    
    return hostname


def group_hostnames(hostnames: List[str]) -> Dict[str, List[str]]:
    """简单分组 - 仅用于展示汇总，不改动文件结构"""
    groups = {}
    for hostname in hostnames:
        normalized = normalize_hostname(hostname)
        if normalized not in groups:
            groups[normalized] = []
        groups[normalized].append(hostname)
    return groups


class SiteDataManager:
    """网站数据查询管理器 - 按现有结构读取session_*/{hostname}/*.jsonl"""
    
    def __init__(self, data_dir: Optional[Path] = None):
        self.data_dir = data_dir or get_data_directory()
        
    def get_all_sessions(self) -> List[str]:
        """获取所有会话ID列表"""
        sessions = []
        try:
            for item in self.data_dir.iterdir():
                if item.is_dir() and item.name.startswith('session_'):
                    sessions.append(item.name)
        except Exception:
            pass  # 目录不存在等情况静默跳过
        return sorted(sessions)
        
    def get_sites_for_session(self, session_id: str) -> List[str]:
        """获取指定会话的所有网站"""
        session_path = self.data_dir / session_id
        if not session_path.exists():
            return []
            
        sites = []
        try:
            for item in session_path.iterdir():
                if item.is_dir() and not item.name.startswith('.'):
                    sites.append(item.name)
        except Exception:
            pass
        return sorted(sites)
        
    def get_site_data_generator(self, session_id: str, hostname: str, 
                               data_type: str = "memory") -> Generator[Dict[str, Any], None, None]:
        """获取网站数据生成器 - 避免一次性加载"""
        # 按约定路径读取：session_*/{hostname}/{memory|network|console|correlations}.jsonl
        file_path = self.data_dir / session_id / hostname / f"{data_type}.jsonl"
        return read_jsonl_data(file_path)
        
    def get_site_memory_stats(self, session_id: str, hostname: str) -> Dict[str, Any]:
        """获取网站内存统计（使用生成器）"""
        data_gen = self.get_site_data_generator(session_id, hostname, "memory")
        return calculate_memory_stats(data_gen)
    
    def get_site_summary(self, hostname: str) -> Dict[str, Any]:
        """获取网站跨会话汇总信息"""
        summary = {
            "hostname": hostname,
            "sessions": [],
            "total_records": 0,
            "data_types": set()
        }
        
        for session_id in self.get_all_sessions():
            session_sites = self.get_sites_for_session(session_id)
            if hostname in session_sites:
                session_data = {
                    "session_id": session_id,
                    "data_types": []
                }
                
                session_path = self.data_dir / session_id / hostname
                try:
                    for data_file in session_path.glob("*.jsonl"):
                        data_type = data_file.stem
                        session_data["data_types"].append(data_type)
                        summary["data_types"].add(data_type)
                        
                        # 统计记录数
                        try:
                            with open(data_file, 'r', encoding='utf-8') as f:
                                record_count = sum(1 for line in f if line.strip())
                                summary["total_records"] += record_count
                        except Exception:
                            pass  # 文件读取失败时跳过
                except Exception:
                    pass  # 目录遍历失败时跳过
                
                if session_data["data_types"]:  # 只添加有数据的会话
                    summary["sessions"].append(session_data)
        
        summary["data_types"] = list(summary["data_types"])
        return summary
    
    def get_all_sites_grouped(self) -> Dict[str, List[str]]:
        """获取所有网站的分组展示"""
        all_sites = set()
        for session_id in self.get_all_sessions():
            sites = self.get_sites_for_session(session_id)
            all_sites.update(sites)
        
        return group_hostnames(list(all_sites))