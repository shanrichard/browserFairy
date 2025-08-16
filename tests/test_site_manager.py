"""测试网站数据管理器功能"""

import json
import pytest
from pathlib import Path
from unittest.mock import patch

from browserfairy.data.site_manager import (
    SiteDataManager,
    read_jsonl_data, 
    calculate_memory_stats,
    normalize_hostname,
    group_hostnames
)


class TestSiteDataManager:
    """SiteDataManager功能测试"""
    
    @pytest.fixture
    def sample_data_structure(self, tmp_path):
        """创建标准的测试数据目录结构"""
        # 模拟现有DataWriter生成的目录结构
        
        # session_2024-01-01_120000/
        session_dir = tmp_path / "session_2024-01-01_120000"
        session_dir.mkdir()
        
        # github.com数据
        github_dir = session_dir / "github.com"
        github_dir.mkdir()
        
        # 创建memory.jsonl
        memory_file = github_dir / "memory.jsonl"
        test_memory_data = [
            {"timestamp": "2024-01-01T12:00:00Z", "memory": {"jsHeap": {"used": 1000000}}},
            {"timestamp": "2024-01-01T12:01:00Z", "memory": {"jsHeap": {"used": 1200000}}},
            {"timestamp": "2024-01-01T12:02:00Z", "memory": {"jsHeap": {"used": 800000}}}
        ]
        
        with open(memory_file, 'w', encoding='utf-8') as f:
            for data in test_memory_data:
                f.write(json.dumps(data) + '\n')
        
        # 创建console.jsonl
        console_file = github_dir / "console.jsonl"
        test_console_data = [
            {"timestamp": "2024-01-01T12:00:00Z", "type": "console", "level": "log", "message": "test"}
        ]
        
        with open(console_file, 'w', encoding='utf-8') as f:
            for data in test_console_data:
                f.write(json.dumps(data) + '\n')
        
        # google.com数据（仅memory）
        google_dir = session_dir / "google.com"  
        google_dir.mkdir()
        
        google_memory_file = google_dir / "memory.jsonl"
        with open(google_memory_file, 'w', encoding='utf-8') as f:
            f.write(json.dumps({"memory": {"jsHeap": {"used": 500000}}}) + '\n')
        
        # session_2024-01-02_120000/ (第二个会话)
        session2_dir = tmp_path / "session_2024-01-02_120000"
        session2_dir.mkdir()
        
        github2_dir = session2_dir / "github.com"
        github2_dir.mkdir()
        
        memory2_file = github2_dir / "memory.jsonl"
        with open(memory2_file, 'w', encoding='utf-8') as f:
            f.write(json.dumps({"memory": {"jsHeap": {"used": 2000000}}}) + '\n')
        
        return tmp_path
    
    def test_get_all_sessions(self, sample_data_structure):
        """测试会话列表获取正确性"""
        manager = SiteDataManager(sample_data_structure)
        sessions = manager.get_all_sessions()
        
        assert len(sessions) == 2
        assert "session_2024-01-01_120000" in sessions
        assert "session_2024-01-02_120000" in sessions
        assert sessions == sorted(sessions)  # 确保排序
    
    def test_get_sites_for_session(self, sample_data_structure):
        """测试单会话网站列表获取"""
        manager = SiteDataManager(sample_data_structure)
        sites = manager.get_sites_for_session("session_2024-01-01_120000")
        
        assert len(sites) == 2
        assert "github.com" in sites
        assert "google.com" in sites
        assert sites == sorted(sites)  # 确保排序
    
    def test_get_sites_for_nonexistent_session(self, sample_data_structure):
        """测试不存在会话的处理"""
        manager = SiteDataManager(sample_data_structure)
        sites = manager.get_sites_for_session("session_nonexistent")
        
        assert sites == []
    
    def test_get_site_data_generator(self, sample_data_structure):
        """测试网站数据生成器"""
        manager = SiteDataManager(sample_data_structure)
        data_gen = manager.get_site_data_generator("session_2024-01-01_120000", "github.com", "memory")
        
        data_list = list(data_gen)
        assert len(data_list) == 3
        assert data_list[0]["memory"]["jsHeap"]["used"] == 1000000
        assert data_list[1]["memory"]["jsHeap"]["used"] == 1200000
        assert data_list[2]["memory"]["jsHeap"]["used"] == 800000
    
    def test_get_site_memory_stats(self, sample_data_structure):
        """测试内存统计计算"""
        manager = SiteDataManager(sample_data_structure)
        stats = manager.get_site_memory_stats("session_2024-01-01_120000", "github.com")
        
        assert stats["count"] == 3
        assert stats["min"] == 800000
        assert stats["max"] == 1200000
        assert stats["avg"] == 1000000.0  # (1000000 + 1200000 + 800000) / 3 = 1000000.0
        # P95: int(0.95 * (3-1)) = 1, 即第2个值（排序后）：1000000
        assert stats["p95"] == 1000000
    
    def test_get_site_summary(self, sample_data_structure):
        """测试网站汇总信息"""
        manager = SiteDataManager(sample_data_structure)
        summary = manager.get_site_summary("github.com")
        
        assert summary["hostname"] == "github.com"
        assert len(summary["sessions"]) == 2  # 两个会话都有github.com
        assert summary["total_records"] > 0
        assert "memory" in summary["data_types"]
    
    def test_get_all_sites_grouped(self, sample_data_structure):
        """测试网站分组展示"""
        manager = SiteDataManager(sample_data_structure)
        groups = manager.get_all_sites_grouped()
        
        assert "github.com" in groups
        assert "google.com" in groups
    
    def test_empty_data_directory(self, tmp_path):
        """测试空数据目录的处理"""
        manager = SiteDataManager(tmp_path)
        
        assert manager.get_all_sessions() == []
        assert manager.get_sites_for_session("any") == []
        
        summary = manager.get_site_summary("any.com")
        assert summary["hostname"] == "any.com"
        assert len(summary["sessions"]) == 0


class TestReadJsonlData:
    """测试JSONL读取生成器"""
    
    def test_read_valid_jsonl(self, tmp_path):
        """测试正常JSONL文件读取"""
        test_file = tmp_path / "test.jsonl"
        test_data = [
            {"id": 1, "value": "test1"},
            {"id": 2, "value": "test2"}
        ]
        
        with open(test_file, 'w', encoding='utf-8') as f:
            for data in test_data:
                f.write(json.dumps(data) + '\n')
        
        data_list = list(read_jsonl_data(test_file))
        assert len(data_list) == 2
        assert data_list[0]["id"] == 1
        assert data_list[1]["value"] == "test2"
    
    def test_read_jsonl_with_bad_lines(self, tmp_path):
        """测试包含坏JSON行的处理"""
        test_file = tmp_path / "bad.jsonl"
        
        with open(test_file, 'w', encoding='utf-8') as f:
            f.write('{"valid": "data"}\n')
            f.write('invalid json line\n')  # 坏行
            f.write('{"another": "valid"}\n')
            f.write('\n')  # 空行
        
        data_list = list(read_jsonl_data(test_file))
        assert len(data_list) == 2  # 只有2个有效JSON
        assert data_list[0]["valid"] == "data"
        assert data_list[1]["another"] == "valid"
    
    def test_read_nonexistent_file(self, tmp_path):
        """测试不存在文件的处理"""
        nonexistent_file = tmp_path / "nonexistent.jsonl"
        
        data_list = list(read_jsonl_data(nonexistent_file))
        assert data_list == []  # 应该返回空列表，不报错


class TestCalculateMemoryStats:
    """测试内存统计计算"""
    
    def test_calculate_stats_normal(self):
        """测试正常数据的统计计算"""
        def sample_generator():
            yield {"memory": {"jsHeap": {"used": 1000000}}}
            yield {"memory": {"jsHeap": {"used": 2000000}}}
            yield {"memory": {"jsHeap": {"used": 3000000}}}
            yield {"memory": {"jsHeap": {"used": 4000000}}}
            yield {"memory": {"jsHeap": {"used": 5000000}}}
        
        stats = calculate_memory_stats(sample_generator())
        assert stats["count"] == 5
        assert stats["min"] == 1000000
        assert stats["max"] == 5000000
        assert stats["avg"] == 3000000.0  # 浮点平均值
        # P95: int(0.95 * (5-1)) = 3, 即排序后第4个值（索引3）
        assert stats["p95"] == 4000000
    
    def test_calculate_stats_with_invalid_data(self):
        """测试包含无效数据的处理"""
        def mixed_generator():
            yield {"memory": {"jsHeap": {"used": 1000000}}}
            yield {"invalid": "data"}  # 无效数据
            yield {"memory": {"jsHeap": {"used": 2000000}}}
            yield {"memory": {}}  # 缺失jsHeap
            yield {"memory": {"jsHeap": {"used": 3000000}}}
        
        stats = calculate_memory_stats(mixed_generator())
        assert stats["count"] == 3  # 只有3个有效数据
        assert stats["min"] == 1000000
        assert stats["max"] == 3000000
        assert stats["avg"] == 2000000.0  # (1000000 + 2000000 + 3000000) / 3
    
    def test_calculate_stats_empty_data(self):
        """测试空数据的处理"""
        def empty_generator():
            return
            yield  # 永远不会执行
        
        stats = calculate_memory_stats(empty_generator())
        assert stats["count"] == 0
    
    def test_calculate_stats_large_dataset_limit(self):
        """测试大数据集的软上限保护"""
        def large_generator():
            for i in range(150000):  # 超过100k限制
                yield {"memory": {"jsHeap": {"used": i}}}
        
        stats = calculate_memory_stats(large_generator())
        assert stats["count"] == 100000  # 应该被截断到100k


class TestHostnameNormalization:
    """测试域名规范化和分组"""
    
    def test_normalize_hostname(self):
        """测试极简域名规范化"""
        assert normalize_hostname("www.github.com") == "github.com"
        assert normalize_hostname("m.facebook.com") == "facebook.com"
        assert normalize_hostname("API.GITHUB.COM") == "api.github.com"  # 不移除api
        assert normalize_hostname("gist.github.com") == "gist.github.com"  # 不移除gist
        assert normalize_hostname("GitHub.Com") == "github.com"  # 统一小写
        assert normalize_hostname("") == "unknown"  # 空字符串处理
    
    def test_group_hostnames(self):
        """测试域名分组功能"""
        hostnames = ["github.com", "www.github.com", "api.github.com", "m.facebook.com", "facebook.com"]
        groups = group_hostnames(hostnames)
        
        # github.com组应该包含github.com和www.github.com
        assert len(groups["github.com"]) == 2
        assert "github.com" in groups["github.com"]
        assert "www.github.com" in groups["github.com"]
        
        # api.github.com应该独立分组（不误合并）
        assert "api.github.com" in groups
        assert len(groups["api.github.com"]) == 1
        
        # facebook.com组应该包含facebook.com和m.facebook.com  
        assert len(groups["facebook.com"]) == 2
        assert "facebook.com" in groups["facebook.com"]
        assert "m.facebook.com" in groups["facebook.com"]