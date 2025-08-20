"""Cross-platform path utilities."""

import os
from pathlib import Path
from typing import Optional


def get_data_directory() -> Path:
    """Get the data directory path, with environment variable override support."""
    # Allow environment variable override
    env_override = os.environ.get("BROWSERFAIRY_DATA_DIR")
    if env_override:
        # Expand ~ to home directory path
        return Path(env_override).expanduser()
    
    # Default to user home directory
    return Path.home() / "BrowserFairyData"


def ensure_data_directory(data_dir: Optional[Path] = None) -> Path:
    """Ensure the data directory exists and is writable."""
    if data_dir is None:
        data_dir = get_data_directory()
    
    # Create directory if it doesn't exist
    data_dir.mkdir(parents=True, exist_ok=True)
    
    # Simple writability check
    test_file = data_dir / ".write_test"
    try:
        test_file.write_text("test")
        test_file.unlink()
    except Exception as e:
        raise RuntimeError(f"Data directory {data_dir} is not writable: {e}")
    
    return data_dir