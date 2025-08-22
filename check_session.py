#!/usr/bin/env python
"""Check specific session content"""

import json
from pathlib import Path

def check_session(session_name="session_2025-08-22_124744"):
    data_dir = Path.home() / "BrowserFairyData" / session_name
    
    print(f"\nChecking session: {session_name}")
    print("="*60)
    
    if not data_dir.exists():
        print(f"Session directory not found: {data_dir}")
        return
    
    print(f"Session path: {data_dir}")
    
    # List all directories (sites)
    sites = [d for d in data_dir.iterdir() if d.is_dir()]
    print(f"\nSites found: {len(sites)}")
    
    for site_dir in sites:
        print(f"\n📁 {site_dir.name}/")
        
        # List all files and directories
        items = list(site_dir.iterdir())
        
        # Separate files and directories
        files = [f for f in items if f.is_file()]
        dirs = [d for d in items if d.is_dir()]
        
        # Show files
        if files:
            print("  Files:")
            for f in sorted(files):
                size = f.stat().st_size
                print(f"    - {f.name}: {size:,} bytes")
        
        # Show directories
        if dirs:
            print("  Directories:")
            for d in sorted(dirs):
                sub_items = list(d.iterdir())
                print(f"    - {d.name}/ ({len(sub_items)} items)")
                # Show first few items in subdirectory
                for item in sub_items[:3]:
                    if item.is_file():
                        print(f"        • {item.name}")
        
        # Specifically check for source_maps and sources
        source_maps_dir = site_dir / "source_maps"
        sources_dir = site_dir / "sources"
        
        print("\n  Special directories:")
        print(f"    source_maps/ exists: {source_maps_dir.exists()}")
        print(f"    sources/ exists: {sources_dir.exists()}")
        
        # Check for console.jsonl to see if there were exceptions
        console_file = site_dir / "console.jsonl"
        if console_file.exists():
            lines = console_file.read_text().splitlines()
            events = [json.loads(line) for line in lines if line]
            
            # Count event types
            types = {}
            for event in events:
                t = event.get('type', 'unknown')
                types[t] = types.get(t, 0) + 1
            
            print(f"\n  Console events: {len(events)} total")
            for t, count in types.items():
                print(f"    - {t}: {count}")

if __name__ == "__main__":
    # Check the specific session
    check_session("session_2025-08-22_124744")
    
    # Also check the latest session
    print("\n" + "="*60)
    print("Checking latest session...")
    
    data_dir = Path.home() / "BrowserFairyData"
    sessions = sorted(data_dir.glob("session_*"), reverse=True)
    if sessions:
        latest = sessions[0]
        check_session(latest.name)