import asyncio
import sys
from pathlib import Path

async def check_latest_session():
    """Check the latest monitoring session for source maps"""
    
    # Find data directory
    data_dir = Path.home() / "BrowserFairyData"
    if not data_dir.exists():
        print("No BrowserFairyData directory found")
        return
    
    # Get latest session
    sessions = sorted(data_dir.glob("session_*"), reverse=True)
    if not sessions:
        print("No sessions found")
        return
    
    latest = sessions[0]
    print(f"Latest session: {latest.name}")
    print(f"Session time: {latest.name.split('_', 1)[1] if '_' in latest.name else 'unknown'}")
    print()
    
    # Check each site in the session
    sites = [d for d in latest.iterdir() if d.is_dir()]
    print(f"Sites monitored: {len(sites)}")
    
    for site_dir in sites:
        print(f"\n📁 {site_dir.name}:")
        
        # Check for various data files
        files = list(site_dir.glob("*.jsonl"))
        print(f"   Data files: {len(files)}")
        for f in files:
            size = f.stat().st_size
            print(f"     - {f.name}: {size:,} bytes")
        
        # Check for source_maps directory
        source_maps_dir = site_dir / "source_maps"
        if source_maps_dir.exists():
            map_files = list(source_maps_dir.glob("*.map.json"))
            metadata = source_maps_dir / "metadata.jsonl"
            print(f"   ✓ source_maps/: {len(map_files)} files")
            if metadata.exists():
                print(f"     - metadata.jsonl: {metadata.stat().st_size:,} bytes")
        else:
            print(f"   ❌ No source_maps/ directory")
        
        # Check for sources directory
        sources_dir = site_dir / "sources"
        if sources_dir.exists():
            source_files = list(sources_dir.glob("*"))
            print(f"   ✓ sources/: {len(source_files)} files")
        else:
            print(f"   ❌ No sources/ directory")

asyncio.run(check_latest_session())
