"""Tests for AI analyzer module."""

import pytest
import asyncio
import os
from pathlib import Path
from unittest.mock import Mock, patch, AsyncMock
from browserfairy.analysis.ai_analyzer import PerformanceAnalyzer


class TestPerformanceAnalyzer:
    """Tests for PerformanceAnalyzer class."""
    
    @pytest.fixture
    def temp_session_dir(self, tmp_path):
        """Create a temporary session directory structure."""
        session_dir = tmp_path / "session_2025-08-20_100000"
        session_dir.mkdir()
        
        # Create mock data files
        site_dir = session_dir / "example.com"
        site_dir.mkdir()
        
        # Write mock JSONL data
        memory_file = site_dir / "memory.jsonl"
        memory_file.write_text('{"type":"memory","timestamp":"2025-08-20T10:00:00","memory":{"jsHeap":{"used":10485760}}}\n')
        
        console_file = site_dir / "console.jsonl"
        console_file.write_text('{"type":"console","level":"error","message":"Test error"}\n')
        
        # Create source_maps and sources directories (for 2-6 integration)
        source_maps_dir = site_dir / "source_maps"
        source_maps_dir.mkdir()
        
        sources_dir = site_dir / "sources"
        sources_dir.mkdir()
        
        return session_dir
    
    def test_init_with_valid_dir(self, temp_session_dir):
        """Test initialization with a valid directory."""
        with patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'test-key'}):
            analyzer = PerformanceAnalyzer(temp_session_dir)
            assert analyzer.session_dir == temp_session_dir
    
    def test_init_with_invalid_dir(self, tmp_path):
        """Test initialization with non-existent directory."""
        invalid_dir = tmp_path / "non_existent"
        with pytest.raises(FileNotFoundError) as exc_info:
            PerformanceAnalyzer(invalid_dir)
        assert "Session directory not found" in str(exc_info.value)
    
    @patch.dict('os.environ', {}, clear=True)
    def test_check_api_key_missing(self, temp_session_dir, capsys):
        """Test API Key check when missing."""
        analyzer = PerformanceAnalyzer(temp_session_dir)
        assert analyzer.api_key_available == False
        
        captured = capsys.readouterr()
        assert "ANTHROPIC_API_KEY" in captured.out
        assert "https://console.anthropic.com" in captured.out
    
    @patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'test-key'})
    def test_check_api_key_present(self, temp_session_dir):
        """Test API Key check when present."""
        with patch('subprocess.run') as mock_run:
            # Mock Node.js version check
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = 'v20.0.0'
            
            analyzer = PerformanceAnalyzer(temp_session_dir)
            assert analyzer.api_key_available == True
    
    @patch('subprocess.run')
    def test_check_nodejs_version_ok(self, mock_run, temp_session_dir):
        """Test Node.js version check - version OK."""
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = 'v20.11.0'
        
        with patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'test-key'}):
            analyzer = PerformanceAnalyzer(temp_session_dir)
            assert analyzer.node_available == True
            assert analyzer.node_version == 'v20.11.0'
    
    @patch('subprocess.run')
    def test_check_nodejs_version_too_low(self, mock_run, temp_session_dir, capsys):
        """Test Node.js version check - version too low."""
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = 'v16.14.0'
        
        with patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'test-key'}):
            analyzer = PerformanceAnalyzer(temp_session_dir)
            assert analyzer.node_available == False
            
            captured = capsys.readouterr()
            assert "版本过低" in captured.out
            assert "v16.14.0" in captured.out
    
    @patch('subprocess.run', side_effect=FileNotFoundError)
    def test_check_nodejs_not_installed(self, mock_run, temp_session_dir, capsys):
        """Test Node.js check when not installed."""
        with patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'test-key'}):
            analyzer = PerformanceAnalyzer(temp_session_dir)
            assert analyzer.node_available == False
            
            captured = capsys.readouterr()
            assert "未检测到Node.js" in captured.out
    
    def test_build_prompt_general(self, temp_session_dir):
        """Test prompt building for general analysis."""
        with patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'test-key'}):
            with patch('subprocess.run') as mock_run:
                mock_run.return_value.returncode = 0
                mock_run.return_value.stdout = 'v20.0.0'
                
                analyzer = PerformanceAnalyzer(temp_session_dir)
                system_prompt, analysis_prompt = analyzer.build_prompt("general")
                
                assert "浏览器性能分析专家" in system_prompt
                assert "编写Python代码来分析监控数据" in analysis_prompt
    
    def test_build_prompt_memory_leak(self, temp_session_dir):
        """Test prompt building for memory leak analysis."""
        with patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'test-key'}):
            with patch('subprocess.run') as mock_run:
                mock_run.return_value.returncode = 0
                mock_run.return_value.stdout = 'v20.0.0'
                
                analyzer = PerformanceAnalyzer(temp_session_dir)
                system_prompt, analysis_prompt = analyzer.build_prompt("memory_leak")
                
                assert "浏览器性能分析专家" in system_prompt
                assert "内存泄漏" in analysis_prompt
                assert "heap_sampling.jsonl" in analysis_prompt
    
    @pytest.mark.asyncio
    @patch('browserfairy.analysis.ai_analyzer.query')
    async def test_analyze_without_api_key(self, mock_query, temp_session_dir, capsys):
        """Test analyze when API key is missing."""
        with patch.dict('os.environ', {}, clear=True):
            analyzer = PerformanceAnalyzer(temp_session_dir)
            result = await analyzer.analyze()
            
            assert result == False
            captured = capsys.readouterr()
            assert "缺少API Key" in captured.out
    
    @pytest.mark.asyncio
    @patch('browserfairy.analysis.ai_analyzer.query')
    @patch('subprocess.run')
    async def test_analyze_without_nodejs(self, mock_run, mock_query, temp_session_dir, capsys):
        """Test analyze when Node.js is missing."""
        mock_run.side_effect = FileNotFoundError
        
        with patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'test-key'}):
            analyzer = PerformanceAnalyzer(temp_session_dir)
            result = await analyzer.analyze()
            
            assert result == False
            captured = capsys.readouterr()
            assert "Node.js环境不满足要求" in captured.out
    
    @pytest.mark.asyncio
    @patch('browserfairy.analysis.ai_analyzer.query')
    async def test_analyze_successful(self, mock_query, temp_session_dir):
        """Test successful analysis."""
        # Mock query to return async generator
        async def mock_generator():
            mock_message = Mock()
            mock_message.result = "Analysis complete: Found 3 issues"
            yield mock_message
        
        mock_query.return_value = mock_generator()
        
        with patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'test-key'}):
            with patch('subprocess.run') as mock_run:
                mock_run.return_value.returncode = 0
                mock_run.return_value.stdout = 'v20.0.0'
                
                analyzer = PerformanceAnalyzer(temp_session_dir)
                result = await analyzer.analyze()
                
                assert result == True
                mock_query.assert_called_once()
    
    @pytest.mark.asyncio
    @patch('browserfairy.analysis.ai_analyzer.query')
    async def test_analyze_with_custom_prompt(self, mock_query, temp_session_dir):
        """Test analysis with custom prompt."""
        async def mock_generator():
            mock_message = Mock()
            mock_message.text = "Custom analysis result"
            yield mock_message
        
        mock_query.return_value = mock_generator()
        
        with patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'test-key'}):
            with patch('subprocess.run') as mock_run:
                mock_run.return_value.returncode = 0
                mock_run.return_value.stdout = 'v20.0.0'
                
                analyzer = PerformanceAnalyzer(temp_session_dir)
                result = await analyzer.analyze(custom_prompt="Analyze only memory data")
                
                assert result == True
                # Verify custom prompt was used
                call_args = mock_query.call_args
                assert "Analyze only memory data" in call_args.kwargs['prompt']
    
    @pytest.mark.asyncio
    @patch('browserfairy.analysis.ai_analyzer.query', side_effect=Exception("API Error"))
    async def test_analyze_with_exception(self, mock_query, temp_session_dir, capsys):
        """Test analysis when exception occurs."""
        with patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'test-key'}):
            with patch('subprocess.run') as mock_run:
                mock_run.return_value.returncode = 0
                mock_run.return_value.stdout = 'v20.0.0'
                
                analyzer = PerformanceAnalyzer(temp_session_dir)
                result = await analyzer.analyze()
                
                assert result == False
                captured = capsys.readouterr()
                assert "AI分析失败" in captured.out