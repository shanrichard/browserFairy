#!/usr/bin/env python
"""Diagnose why source maps are not being collected"""

import asyncio
import json
import os
from pathlib import Path
from browserfairy.core import ChromeConnector
from browserfairy.analysis.source_map import SourceMapResolver
from browserfairy.monitors.console import ConsoleMonitor

async def diagnose():
    print("\n" + "="*60)
    print("SOURCE MAP COLLECTION DIAGNOSTIC")
    print("="*60 + "\n")
    
    # 1. Check data directory
    print("1. Checking existing data...")
    session_dir = Path("/Users/shanjingxiang/BrowserFairyData/session_2025-08-22_124744")
    
    if session_dir.exists():
        print(f"✓ Session directory exists: {session_dir}")
        
        # Check for source_maps directory
        source_maps_dir = session_dir / "source_maps"
        if source_maps_dir.exists():
            print(f"✓ source_maps directory exists")
            files = list(source_maps_dir.glob("*"))
            print(f"  Contains {len(files)} files")
        else:
            print("✗ source_maps directory does NOT exist")
        
        # Check what data was collected
        sites = [d for d in session_dir.iterdir() if d.is_dir() and d.name != "source_maps"]
        print(f"\nSites monitored: {[s.name for s in sites]}")
    else:
        print(f"✗ Session directory not found: {session_dir}")
    
    print("\n" + "-"*60 + "\n")
    
    # 2. Test Chrome connection
    print("2. Testing Chrome connection...")
    connector = ChromeConnector()
    
    try:
        await connector.connect()
        print("✓ Connected to Chrome")
    except Exception as e:
        print(f"✗ Failed to connect: {e}")
        print("\nPlease start Chrome with:")
        print("  open -a 'Google Chrome' --args --remote-debugging-port=9222")
        return
    
    # 3. Find SignalPlus tab
    print("\n3. Looking for SignalPlus tab...")
    tabs = await connector.call('Target.getTargets')
    targets = tabs['targetInfos']
    
    signalplus_targets = [t for t in targets if 't.signalplus.com' in t.get('url', '')]
    
    if not signalplus_targets:
        print("✗ No SignalPlus tab found")
        print("  Please open: https://t.signalplus.com")
        await connector.disconnect()
        return
    
    target = signalplus_targets[0]
    print(f"✓ Found tab: {target['url'][:60]}...")
    
    # 4. Test Debugger.scriptParsed events
    print("\n4. Testing Debugger.scriptParsed events...")
    
    attach = await connector.call('Target.attachToTarget', {
        'targetId': target['targetId'], 
        'flatten': True
    })
    session_id = attach['sessionId']
    print(f"✓ Attached to target (sessionId: {session_id[:16]}...)")
    
    # Enable Debugger
    await connector.call('Debugger.enable', session_id=session_id)
    print("✓ Debugger enabled")
    
    # Collect script events
    scripts_collected = []
    scripts_with_maps = []
    
    def on_script_parsed(params):
        if params.get("sessionId") != session_id:
            return
        scripts_collected.append(params)
        if params.get('sourceMapURL'):
            scripts_with_maps.append(params)
    
    connector.on_event("Debugger.scriptParsed", on_script_parsed)
    
    print("\nWaiting 10 seconds to collect script events...")
    await asyncio.sleep(10)
    
    print(f"\n✓ Collected {len(scripts_collected)} scripts")
    print(f"✓ Scripts with source maps: {len(scripts_with_maps)}")
    
    if scripts_with_maps:
        print("\nExample scripts with source maps:")
        for i, script in enumerate(scripts_with_maps[:3], 1):
            url = script.get('url', '')
            source_map = script.get('sourceMapURL', '')
            print(f"{i}. {url[:60]}...")
            if source_map.startswith('data:'):
                print(f"   Map: data:... (inline)")
            else:
                print(f"   Map: {source_map[:60]}...")
    
    # 5. Test SourceMapResolver directly
    print("\n" + "-"*60)
    print("\n5. Testing SourceMapResolver with persist_all=True...")
    
    # Create test directory
    test_dir = Path("/tmp/source_map_test")
    test_dir.mkdir(exist_ok=True)
    
    resolver = SourceMapResolver(
        connector=connector,
        persist_all=True  # Enable proactive persistence
    )
    
    # Mock data manager
    class MockDataManager:
        def __init__(self):
            self.base_path = test_dir
        
        def write_data(self, hostname, data_type, data):
            print(f"  DataManager.write_data called: {hostname}/{data_type}")
    
    resolver.data_manager = MockDataManager()
    
    # Initialize resolver for the session
    await resolver.initialize(session_id)
    print("✓ SourceMapResolver initialized")
    
    # Wait for events
    print("\nWaiting 5 seconds for source map processing...")
    await asyncio.sleep(5)
    
    # Check what was collected
    print(f"\n✓ Source maps in cache: {len(resolver.source_maps)}")
    if resolver.source_maps:
        print("  Cached source maps:")
        for url in list(resolver.source_maps.keys())[:3]:
            print(f"    - {url[:60]}...")
    
    # 6. Summary
    print("\n" + "="*60)
    print("DIAGNOSTIC SUMMARY")
    print("="*60)
    
    if scripts_with_maps:
        print(f"\n✓ Found {len(scripts_with_maps)} scripts with source maps")
        print("✓ SourceMapResolver can detect and process them")
        print("\n⚠️ ISSUE: The source maps are present but not being persisted")
        print("\nPossible causes:")
        print("1. persist_all_source_maps parameter not propagating correctly")
        print("2. DataManager not initialized in ConsoleMonitor")
        print("3. Event handlers not being set up properly")
    else:
        print("\n✗ No scripts with source maps detected")
        print("\nThis could mean:")
        print("1. SignalPlus uses production builds without source maps")
        print("2. Source maps are loaded dynamically later")
        print("3. Source maps are inline but not detected properly")
    
    await connector.disconnect()
    print("\n✅ Diagnostic completed")

if __name__ == "__main__":
    asyncio.run(diagnose())