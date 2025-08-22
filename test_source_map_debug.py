#!/usr/bin/env python
"""Debug script to test source map persistence"""

import asyncio
import logging
from pathlib import Path
from browserfairy.core import ChromeConnector
from browserfairy.monitors.memory import MemoryCollector
from browserfairy.data.manager import DataManager

# Enable ALL debug logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

async def test_source_map_persistence():
    """Test if source map persistence is working"""
    
    print("\n" + "="*60)
    print("SOURCE MAP PERSISTENCE TEST")
    print("="*60 + "\n")
    
    connector = ChromeConnector()
    try:
        print("1. Connecting to Chrome...")
        await connector.connect()
        print("   ✓ Connected\n")
    except Exception as e:
        print(f"   ✗ Failed to connect: {e}")
        print("   Please start Chrome with: open -a 'Google Chrome' --args --remote-debugging-port=9222")
        return
    
    # Get tabs
    print("2. Finding suitable tab...")
    tabs = await connector.call('Target.getTargets')
    targets = tabs['targetInfos']
    page_targets = [t for t in targets if t['type'] == 'page' and t['url'].startswith('http')]
    
    if not page_targets:
        print("   ✗ No suitable tabs found. Please open a webpage.")
        await connector.disconnect()
        return
    
    target = page_targets[0]
    url = target['url']
    hostname = url.split('//')[1].split('/')[0] if '//' in url else 'unknown'
    print(f"   ✓ Using tab: {hostname} ({url[:60]}...)\n")
    
    # Create DataManager
    print("3. Starting data management...")
    data_manager = DataManager(connector)
    await data_manager.start()
    session_dir = data_manager.session_dir
    print(f"   ✓ Session: {session_dir.name}\n")
    
    # Create collector with comprehensive mode and source map
    print("4. Creating MemoryCollector with source map enabled...")
    
    # Data callback to track events
    events_received = []
    def data_callback(data):
        event_type = data.get('type', 'unknown')
        events_received.append(event_type)
        if event_type == 'exception':
            print(f"   ! Exception captured: {data.get('message', '')[:50]}")
    
    collector = MemoryCollector(
        connector=connector,
        target_id=target['targetId'],
        hostname=hostname,
        data_callback=data_callback,
        enable_comprehensive=True,
        enable_source_map=True
    )
    
    print("   ✓ MemoryCollector created\n")
    
    # Attach and start collection
    print("5. Starting comprehensive monitoring...")
    await collector.attach()
    collection_task = asyncio.create_task(collector.start_collection())
    print("   ✓ Monitoring started\n")
    
    # Check if ConsoleMonitor and SourceMapResolver are initialized
    print("6. Checking component initialization...")
    if collector.console_monitor:
        print("   ✓ ConsoleMonitor initialized")
        if collector.console_monitor.source_map_resolver:
            resolver = collector.console_monitor.source_map_resolver
            print(f"   ✓ SourceMapResolver initialized")
            print(f"     - Hostname: {resolver.hostname}")
            print(f"     - Session ID: {resolver.session_id}")
        else:
            print("   ✗ SourceMapResolver NOT initialized")
    else:
        print("   ✗ ConsoleMonitor NOT initialized")
    print()
    
    # Wait for events
    print("7. Waiting for script parsing events (15 seconds)...")
    await asyncio.sleep(15)
    
    # Check results
    print("\n8. Checking results...")
    
    # Event statistics
    print(f"   Events received: {len(events_received)}")
    event_counts = {}
    for event in events_received:
        event_counts[event] = event_counts.get(event, 0) + 1
    for event_type, count in sorted(event_counts.items()):
        print(f"     - {event_type}: {count}")
    
    # Check SourceMapResolver state
    if collector.console_monitor and collector.console_monitor.source_map_resolver:
        resolver = collector.console_monitor.source_map_resolver
        print(f"\n   SourceMapResolver state:")
        print(f"     - Scripts parsed: {len(resolver.script_metadata)}")
        scripts_with_maps = [
            (sid, meta) for sid, meta in resolver.script_metadata.items() 
            if meta.get('sourceMapURL')
        ]
        print(f"     - Scripts with source maps: {len(scripts_with_maps)}")
        
        if scripts_with_maps:
            print(f"\n   First 3 scripts with source maps:")
            for script_id, meta in scripts_with_maps[:3]:
                url = meta.get('url', 'unknown')
                map_url = meta.get('sourceMapURL', '')
                print(f"     - {url[:60]}")
                if map_url.startswith('data:'):
                    print(f"       Map: data URL")
                else:
                    print(f"       Map: {map_url[:60]}")
    
    # Check file system
    print(f"\n9. Checking file system...")
    site_dir = session_dir / hostname
    source_maps_dir = site_dir / 'source_maps'
    sources_dir = site_dir / 'sources'
    
    print(f"   Site directory: {site_dir}")
    print(f"     - Exists: {site_dir.exists()}")
    
    if source_maps_dir.exists():
        map_files = list(source_maps_dir.glob('*.map.json'))
        metadata_file = source_maps_dir / 'metadata.jsonl'
        print(f"   ✓ source_maps/ directory created")
        print(f"     - Map files: {len(map_files)}")
        print(f"     - Metadata file exists: {metadata_file.exists()}")
        if map_files:
            print(f"     - Example files:")
            for f in map_files[:3]:
                print(f"       • {f.name}")
    else:
        print(f"   ✗ source_maps/ directory NOT created")
    
    if sources_dir.exists():
        source_files = list(sources_dir.glob('*'))
        print(f"   ✓ sources/ directory created")
        print(f"     - Source files: {len(source_files)}")
        if source_files:
            print(f"     - Example files:")
            for f in source_files[:3]:
                print(f"       • {f.name}")
    else:
        print(f"   ✗ sources/ directory NOT created")
    
    # Cleanup
    print("\n10. Cleaning up...")
    await collector.stop()
    collection_task.cancel()
    await data_manager.stop()
    await connector.disconnect()
    print("    ✓ Done\n")
    
    print("="*60)
    print("TEST COMPLETED")
    print("="*60)

if __name__ == "__main__":
    asyncio.run(test_source_map_persistence())