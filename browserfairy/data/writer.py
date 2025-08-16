"""JSONL文件写入器，复用现有错误处理模式"""

import asyncio
import json
import logging
import os
from collections import defaultdict
from pathlib import Path
from typing import Dict, Any

logger = logging.getLogger(__name__)


class DataWriter:
    """JSONL文件写入器，复用现有错误处理模式"""
    
    MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB per file
    
    def __init__(self, session_dir: Path, enable_delayed_sync: bool = False):
        self.session_dir = session_dir
        self.file_locks: Dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self.enable_delayed_sync = enable_delayed_sync
        self._pending_sync_files = set()  # 待同步文件集合（仅在事件循环线程访问）
        
    async def append_jsonl(self, file_path: str, data: Dict[str, Any]) -> None:
        """加锁的追加写入JSONL（避免新依赖，使用asyncio.to_thread）"""
        full_path = self.session_dir / file_path
        
        try:
            # 确保目录存在（复用paths.py逻辑）
            full_path.parent.mkdir(parents=True, exist_ok=True)
            
            # 文件级锁保护
            async with self.file_locks[file_path]:
                # 检查文件大小，必要时轮转
                await self._rotate_if_needed(full_path)
                
                # JSONL格式（每条一行JSON）
                json_line = json.dumps(data, ensure_ascii=False) + "\n"
                
                # 使用asyncio.to_thread避免阻塞事件循环，无需新依赖
                await asyncio.to_thread(self._sync_write_jsonl, full_path, json_line)
                
                # 写入完成后，在事件循环线程中安全操作集合
                if self.enable_delayed_sync:
                    self._pending_sync_files.add(full_path)
                
        except Exception as e:
            logger.warning(f"Failed to write data to {file_path}: {e}")
            # 不抛出异常，避免影响监控流程
    
    def _sync_write_jsonl(self, file_path: Path, json_line: str) -> None:
        """同步文件写入 - 条件性fsync（线程安全）"""
        with open(file_path, 'a', encoding='utf-8') as f:
            f.write(json_line)
            f.flush()
            
            if not self.enable_delayed_sync:
                # 默认模式：立即同步（保持原行为）
                os.fsync(f.fileno())
            # 延迟模式：什么都不做，让调用方处理
    
    async def _rotate_if_needed(self, file_path: Path) -> None:
        """文件轮转检查和执行 - 轮转前无条件fsync避免数据丢失"""
        try:
            if not file_path.exists():
                return
            
            # 检查文件大小（修正：正确使用asyncio.to_thread）
            stat_result = await asyncio.to_thread(file_path.stat)
            file_size = stat_result.st_size
            if file_size < self.MAX_FILE_SIZE:
                return
            
            # 轮转前无条件fsync当前文件（与延迟设置无关，确保数据安全）
            def _force_sync_before_rotation():
                try:
                    with open(file_path, 'r+b') as f:
                        os.fsync(f.fileno())
                except Exception as e:
                    logger.warning(f"Pre-rotation sync failed for {file_path}: {e}")
                    
            await asyncio.to_thread(_force_sync_before_rotation)
            
            # 从待同步集合中移除（即将被改名）
            self._pending_sync_files.discard(file_path)
            
            # 执行轮转：file.jsonl -> file.1.jsonl，最多保留5个历史文件
            await asyncio.to_thread(self._sync_rotate_files, file_path)
            
        except Exception as e:
            logger.warning(f"File rotation failed for {file_path}: {e}")
    
    def _sync_rotate_files(self, current_file: Path) -> None:
        """同步文件轮转（命名策略：file.1.jsonl, file.2.jsonl, ...）"""
        MAX_ROTATED_FILES = 5
        
        base_name = current_file.stem  # e.g., "rotate_test" from "rotate_test.jsonl"
        parent_dir = current_file.parent
        
        # 移除最老的文件（file.5.jsonl）
        oldest_file = parent_dir / f"{base_name}.{MAX_ROTATED_FILES}.jsonl"
        if oldest_file.exists():
            oldest_file.unlink()
        
        # 向后移动现有文件：file.3.jsonl -> file.4.jsonl
        for i in range(MAX_ROTATED_FILES - 1, 0, -1):
            old_file = parent_dir / f"{base_name}.{i}.jsonl"
            new_file = parent_dir / f"{base_name}.{i + 1}.jsonl"
            if old_file.exists():
                old_file.rename(new_file)
        
        # 当前文件重命名为 file.1.jsonl
        rotated_file = parent_dir / f"{base_name}.1.jsonl"
        current_file.rename(rotated_file)
    
    async def force_sync_pending(self) -> None:
        """强制同步所有待同步文件（会话结束时调用）"""
        if not self._pending_sync_files:
            return
            
        files_to_sync = self._pending_sync_files.copy()
        self._pending_sync_files.clear()
        
        def _batch_sync(file_paths):
            for file_path in file_paths:
                try:
                    with open(file_path, 'r+b') as f:
                        os.fsync(f.fileno())
                except Exception as e:
                    logger.warning(f"Force sync failed for {file_path}: {e}")
        
        await asyncio.to_thread(_batch_sync, files_to_sync)