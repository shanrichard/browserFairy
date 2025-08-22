#!/usr/bin/env python
"""End-to-end test for --persist-all-source-maps functionality"""

import asyncio
import sys
from pathlib import Path
from datetime import datetime

async def test_persist_all():
    """Test that source maps are persisted immediately when scripts are parsed"""
    
    print("\n" + "="*60)
    print("PERSIST-ALL-SOURCE-MAPS END-TO-END TEST")
    print("="*60 + "\n")
    
    # Start monitoring with persist-all enabled
    print("1. Starting monitoring with --persist-all-source-maps...")
    print("   Command: browserfairy --start-monitoring --enable-source-map --persist-all-source-maps")
    print()
    
    # Import and run
    from browserfairy.cli import start_monitoring_service
    
    # Run for a short duration
    duration = 20
    print(f"2. Running monitoring for {duration} seconds...")
    print("   Please open some websites with JavaScript to trigger script parsing")
    print()
    
    try:
        exit_code = await start_monitoring_service(
            log_file=None,
            duration=duration,
            enable_source_map=True,
            persist_all_source_maps=True
        )
    except KeyboardInterrupt:
        print("\n   Monitoring stopped by user")
        exit_code = 0
    
    print(f"\n3. Monitoring completed with exit code: {exit_code}")
    
    # Check results
    print("\n4. Checking for persisted source maps...")
    data_dir = Path.home() / "BrowserFairyData"
    
    if not data_dir.exists():
        print("   ❌ No BrowserFairyData directory found")
        return 1
    
    # Get latest session
    sessions = sorted(data_dir.glob("session_*"), reverse=True)
    if not sessions:
        print("   ❌ No sessions found")
        return 1
    
    latest = sessions[0]
    print(f"   Session: {latest.name}")
    
    # Check for source_maps directories
    found_source_maps = False
    total_map_files = 0
    total_source_files = 0
    
    for site_dir in latest.iterdir():
        if not site_dir.is_dir():
            continue
            
        source_maps_dir = site_dir / "source_maps"
        sources_dir = site_dir / "sources"
        
        if source_maps_dir.exists():
            map_files = list(source_maps_dir.glob("*.map.json"))
            metadata = source_maps_dir / "metadata.jsonl"
            
            if map_files or metadata.exists():
                found_source_maps = True
                total_map_files += len(map_files)
                
                print(f"\n   ✅ {site_dir.name}/source_maps/")
                print(f"      - Map files: {len(map_files)}")
                print(f"      - Metadata: {'Yes' if metadata.exists() else 'No'}")
                
                if map_files:
                    # Show first few files
                    for f in map_files[:3]:
                        print(f"      - {f.name}")
                    if len(map_files) > 3:
                        print(f"      - ... and {len(map_files) - 3} more")
        
        if sources_dir.exists():
            source_files = list(sources_dir.glob("*"))
            if source_files:
                total_source_files += len(source_files)
                print(f"   ✅ {site_dir.name}/sources/")
                print(f"      - Source files: {len(source_files)}")
    
    print(f"\n5. Summary:")
    print(f"   Total map files: {total_map_files}")
    print(f"   Total source files: {total_source_files}")
    
    if found_source_maps:
        print("\n✅ SUCCESS: Source maps were persisted immediately!")
        print("   The --persist-all-source-maps feature is working correctly.")
        return 0
    else:
        print("\n❌ FAILURE: No source maps were persisted.")
        print("   Possible reasons:")
        print("   - No websites with source maps were visited")
        print("   - Chrome didn't have JavaScript enabled")
        print("   - The feature is not working correctly")
        return 1

if __name__ == "__main__":
    exit_code = asyncio.run(test_persist_all())
    sys.exit(exit_code)