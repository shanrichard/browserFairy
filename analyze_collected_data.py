#!/usr/bin/env python
"""Analyze the collected data to understand why source maps weren't saved"""

import json
from pathlib import Path
from datetime import datetime

def analyze_session():
    print("\n" + "="*60)
    print("ANALYSIS OF COLLECTED DATA")
    print("="*60 + "\n")
    
    session_dir = Path("/Users/shanjingxiang/BrowserFairyData/session_2025-08-22_124744")
    
    if not session_dir.exists():
        print(f"✗ Session directory not found: {session_dir}")
        return
    
    print(f"Session: {session_dir.name}")
    print(f"Path: {session_dir}\n")
    
    # 1. Check directory structure
    print("1. Directory Structure:")
    print("-" * 40)
    
    all_items = list(session_dir.iterdir())
    dirs = [d for d in all_items if d.is_dir()]
    files = [f for f in all_items if f.is_file()]
    
    print(f"Directories: {len(dirs)}")
    for d in sorted(dirs):
        print(f"  📁 {d.name}/")
        # Count files in each directory
        sub_files = list(d.glob("*.jsonl"))
        if sub_files:
            print(f"     Files: {', '.join(f.name for f in sub_files[:5])}")
            if len(sub_files) > 5:
                print(f"     ... and {len(sub_files)-5} more")
    
    print(f"\nFiles: {len(files)}")
    for f in sorted(files):
        print(f"  📄 {f.name}")
    
    # 2. Check for source_maps directory specifically
    print("\n2. Source Maps Directory Check:")
    print("-" * 40)
    
    source_maps_dir = session_dir / "source_maps"
    sources_dir = session_dir / "sources"
    
    if source_maps_dir.exists():
        print(f"✓ source_maps/ exists")
        maps = list(source_maps_dir.glob("*"))
        print(f"  Contains {len(maps)} files")
        if maps:
            for m in maps[:3]:
                print(f"    - {m.name}")
    else:
        print("✗ source_maps/ directory NOT found")
    
    if sources_dir.exists():
        print(f"✓ sources/ exists")
        sources = list(sources_dir.glob("*"))
        print(f"  Contains {len(sources)} files")
    else:
        print("✗ sources/ directory NOT found")
    
    # 3. Analyze SignalPlus data
    print("\n3. SignalPlus Site Data:")
    print("-" * 40)
    
    signalplus_dir = session_dir / "t.signalplus.com"
    if signalplus_dir.exists():
        print(f"✓ t.signalplus.com/ directory exists")
        
        # Check each data file
        data_files = {
            "memory.jsonl": "Memory metrics",
            "console.jsonl": "Console logs",
            "network.jsonl": "Network requests",
            "gc.jsonl": "GC events",
            "heap_sampling.jsonl": "Heap sampling profiles",
            "correlations.jsonl": "Correlation analysis",
            "longtask.jsonl": "Long tasks"
        }
        
        for filename, description in data_files.items():
            filepath = signalplus_dir / filename
            if filepath.exists():
                size = filepath.stat().st_size
                # Count lines
                try:
                    with open(filepath, 'r') as f:
                        lines = sum(1 for _ in f)
                    print(f"  ✓ {filename}: {lines} entries ({size:,} bytes)")
                except:
                    print(f"  ✓ {filename}: exists ({size:,} bytes)")
            else:
                print(f"  ✗ {filename}: not found")
        
        # Check for console errors mentioning source maps
        console_file = signalplus_dir / "console.jsonl"
        if console_file.exists():
            print("\n  Checking console.jsonl for source map references...")
            source_map_mentions = 0
            error_count = 0
            
            with open(console_file, 'r') as f:
                for line in f:
                    try:
                        entry = json.loads(line)
                        if 'source' in str(entry).lower() and 'map' in str(entry).lower():
                            source_map_mentions += 1
                        if entry.get('type') == 'error':
                            error_count += 1
                    except:
                        pass
            
            print(f"    - Errors logged: {error_count}")
            print(f"    - Source map mentions: {source_map_mentions}")
    
    # 4. Check overview.json
    print("\n4. Session Overview:")
    print("-" * 40)
    
    overview_file = session_dir / "overview.json"
    if overview_file.exists():
        with open(overview_file, 'r') as f:
            overview = json.load(f)
        
        print(f"  Session ID: {overview.get('session_id', 'N/A')}")
        print(f"  Start time: {overview.get('start_time', 'N/A')}")
        
        if 'configuration' in overview:
            config = overview['configuration']
            print(f"  Configuration:")
            print(f"    - Enable source maps: {config.get('enable_source_maps', False)}")
            print(f"    - Persist all source maps: {config.get('persist_all_source_maps', False)}")
    else:
        print("  ✗ overview.json not found")
    
    # 5. Summary and diagnosis
    print("\n" + "="*60)
    print("DIAGNOSIS")
    print("="*60 + "\n")
    
    issues = []
    
    if not source_maps_dir.exists():
        issues.append("❌ source_maps/ directory was never created")
    
    if not sources_dir.exists():
        issues.append("❌ sources/ directory was never created")
    
    if overview_file.exists():
        with open(overview_file, 'r') as f:
            overview = json.load(f)
        config = overview.get('configuration', {})
        
        if not config.get('persist_all_source_maps'):
            issues.append("⚠️ persist_all_source_maps was NOT enabled in configuration")
        
        if not config.get('enable_source_maps'):
            issues.append("⚠️ enable_source_maps was NOT enabled in configuration")
    
    if issues:
        print("Issues found:")
        for issue in issues:
            print(f"  {issue}")
    else:
        print("✓ No obvious issues found in configuration")
    
    print("\nConclusion:")
    print("-" * 40)
    print("The source_maps directory was never created during your monitoring session.")
    print("This indicates that either:")
    print("1. The --persist-all-source-maps flag wasn't passed correctly")
    print("2. The website doesn't have source maps available")
    print("3. The source map collection code has a bug preventing persistence")
    
    print("\nRecommended next step:")
    print("Run: python -m browserfairy --monitor-comprehensive --persist-all-source-maps")
    print("And verify that source maps are being collected for the target site.")

if __name__ == "__main__":
    analyze_session()