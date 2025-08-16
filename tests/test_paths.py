"""Tests for path utilities."""

import os
import tempfile
from pathlib import Path
import pytest

from browserfairy.utils.paths import get_data_directory, ensure_data_directory


def test_get_data_directory_default():
    """Test default data directory location."""
    # Clear environment variable if set
    old_value = os.environ.pop("BROWSERFAIRY_DATA_DIR", None)
    
    try:
        data_dir = get_data_directory()
        expected = Path.home() / "BrowserFairyData"
        assert data_dir == expected
    finally:
        # Restore environment variable
        if old_value:
            os.environ["BROWSERFAIRY_DATA_DIR"] = old_value


def test_get_data_directory_with_env_override():
    """Test data directory with environment variable override."""
    with tempfile.TemporaryDirectory() as temp_dir:
        test_path = Path(temp_dir) / "custom_data"
        
        # Set environment variable
        old_value = os.environ.get("BROWSERFAIRY_DATA_DIR")
        os.environ["BROWSERFAIRY_DATA_DIR"] = str(test_path)
        
        try:
            data_dir = get_data_directory()
            assert data_dir == test_path
        finally:
            # Restore environment variable
            if old_value:
                os.environ["BROWSERFAIRY_DATA_DIR"] = old_value
            else:
                os.environ.pop("BROWSERFAIRY_DATA_DIR", None)


def test_ensure_data_directory_creation():
    """Test data directory creation."""
    with tempfile.TemporaryDirectory() as temp_dir:
        test_path = Path(temp_dir) / "new_data_dir"
        
        # Directory should not exist initially
        assert not test_path.exists()
        
        # ensure_data_directory should create it
        result_path = ensure_data_directory(test_path)
        
        assert result_path == test_path
        assert test_path.exists()
        assert test_path.is_dir()


def test_ensure_data_directory_writability():
    """Test data directory writability check."""
    with tempfile.TemporaryDirectory() as temp_dir:
        test_path = Path(temp_dir) / "writable_dir"
        
        # Should succeed for writable directory
        result_path = ensure_data_directory(test_path)
        assert result_path == test_path
        assert test_path.exists()