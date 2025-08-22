#!/usr/bin/env python
"""Debug script to check why source maps are not being persisted"""

import asyncio
import json
import logging
from pathlib import Path
from browserfairy.core import ChromeConnector

# Enable ALL debug logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

async def debug_source_maps():
    print("\n" + "="*60)
    print("SOURCE MAP DEBUG")
    print("="*60 + "\n")
    
    connector = ChromeConnector()
    
    try:
        print("1. Connecting to Chrome...")
        await connector.connect()
        print("   ✓ Connected\n")
    except Exception as e:
        print(f"   ✗ Failed: {e}")
        print("   Start Chrome with: open -a 'Google Chrome' --args --remote-debugging-port=9222")
        return
    
    # Get tabs
    print("2. Getting tabs...")
    tabs = await connector.call('Target.getTargets')
    targets = tabs['targetInfos']
    page_targets = [t for t in targets if t['type'] == 'page' and t['url'].startswith('http')]
    
    if not page_targets:
        print("   ✗ No suitable tabs found")
        await connector.disconnect()
        return
    
    target = page_targets[0]
    url = target['url']
    hostname = url.split('//')[1].split('/')[0] if '//' in url else 'unknown'
    print(f"   ✓ Using: {hostname}\n")
    
    # Attach to target
    print("3. Attaching to target...")
    attach = await connector.call('Target.attachToTarget', {'targetId': target['targetId'], 'flatten': True})
    session_id = attach['sessionId']
    print(f"   ✓ Session ID: {session_id}\n")
    
    # Enable Debugger
    print("4. Enabling Debugger domain...")
    await connector.call('Debugger.enable', session_id=session_id)
    print("   ✓ Debugger enabled\n")
    
    # Track script events
    scripts_found = []
    scripts_with_maps = []
    
    def on_script_parsed(params):
        """Handle Debugger.scriptParsed events"""
        if params.get("sessionId") != session_id:
            return
        
        script_id = params.get("scriptId")
        script_url = params.get("url", "")
        source_map_url = params.get("sourceMapURL")
        
        if script_id and script_url:
            scripts_found.append({
                "id": script_id,
                "url": script_url[:100],
                "sourceMapURL": source_map_url
            })
            
            if source_map_url:
                scripts_with_maps.append({
                    "id": script_id,
                    "url": script_url[:100],
                    "sourceMapURL": source_map_url[:100] if not source_map_url.startswith('data:') else 'data:...'
                })
                print(f"   ! Found source map: {script_url[:50]}...")
    
    # Register event handler
    connector.on_event("Debugger.scriptParsed", on_script_parsed)
    print("5. Listening for script events...")
    
    # Reload the page to get fresh events
    print("6. Reloading page to capture all scripts...")
    await connector.call('Page.enable', session_id=session_id)
    await connector.call('Page.reload', session_id=session_id)
    
    # Wait for scripts to load
    await asyncio.sleep(5)
    
    print(f"\n7. Results:")
    print(f"   Total scripts parsed: {len(scripts_found)}")
    print(f"   Scripts with source maps: {len(scripts_with_maps)}")
    
    if scripts_with_maps:
        print("\n   Scripts with source maps:")
        for i, script in enumerate(scripts_with_maps[:5], 1):
            print(f"   {i}. {script['url']}")
            print(f"      Source map: {script['sourceMapURL']}")
    else:
        print("\n   ⚠️ No scripts with source maps found!")
        print("   This explains why source_maps/ directory is not created.")
        print("\n   Sample scripts (first 5):")
        for i, script in enumerate(scripts_found[:5], 1):
            print(f"   {i}. {script['url']}")
    
    # Now test with SourceMapResolver
    print("\n8. Testing SourceMapResolver with persist_all=True...")
    from browserfairy.analysis.source_map import SourceMapResolver
    
    resolver = SourceMapResolver(connector, persist_all=True)
    await resolver.initialize(session_id)
    resolver.set_hostname(hostname)
    
    print(f"   ✓ SourceMapResolver initialized")
    print(f"   - persist_all: {resolver.persist_all}")
    print(f"   - hostname: {resolver.hostname}")
    
    # Wait for any async tasks
    await asyncio.sleep(5)
    
    # Check if source_maps directory was created
    from browserfairy.utils.paths import get_data_directory
    data_dir = get_data_directory()
    sessions = sorted(data_dir.glob("session_*"), reverse=True)
    
    if sessions:
        latest = sessions[0]
        site_dir = latest / hostname
        source_maps_dir = site_dir / "source_maps"
        
        print(f"\n9. Checking file system:")
        print(f"   Session: {latest.name}")
        print(f"   Site dir exists: {site_dir.exists()}")
        print(f"   Source maps dir exists: {source_maps_dir.exists()}")
        
        if source_maps_dir.exists():
            files = list(source_maps_dir.glob("*.map.json"))
            print(f"   ✓ Found {len(files)} map files")
        else:
            print(f"   ✗ No source_maps directory created")
            
            # Debug: Check what's in script_metadata
            print(f"\n   Debug info:")
            print(f"   - Scripts in resolver.script_metadata: {len(resolver.script_metadata)}")
            
            # Show scripts with source maps from resolver's perspective
            resolver_scripts_with_maps = [
                (sid, meta) for sid, meta in resolver.script_metadata.items()
                if meta.get('sourceMapURL')
            ]
            print(f"   - Scripts with maps in resolver: {len(resolver_scripts_with_maps)}")
            
            if resolver_scripts_with_maps:
                for sid, meta in resolver_scripts_with_maps[:3]:
                    print(f"     • {meta['url'][:50]}")
                    print(f"       Map: {meta['sourceMapURL'][:50] if not meta['sourceMapURL'].startswith('data:') else 'data:...'}")
    
    await connector.disconnect()
    print("\n✅ Debug completed")

if __name__ == "__main__":
    asyncio.run(debug_source_maps())