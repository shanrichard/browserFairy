#!/usr/bin/env python
"""Check specific file for source map"""

import asyncio
import json
from browserfairy.core import ChromeConnector

async def check_specific_source_map():
    print("\nChecking index.abdfeb54.js for Source Map")
    print("="*60)
    
    connector = ChromeConnector()
    
    try:
        await connector.connect()
        print("✓ Connected to Chrome\n")
    except Exception as e:
        print(f"✗ Failed to connect: {e}")
        return
    
    # Get tabs
    tabs = await connector.call('Target.getTargets')
    targets = tabs['targetInfos']
    
    # Find signalplus tab
    signalplus_targets = [t for t in targets if 't.signalplus.com' in t.get('url', '')]
    
    if not signalplus_targets:
        print("No SignalPlus tab found")
        await connector.disconnect()
        return
    
    target = signalplus_targets[0]
    print(f"Found tab: {target['url'][:80]}...\n")
    
    # Attach to target
    attach = await connector.call('Target.attachToTarget', {'targetId': target['targetId'], 'flatten': True})
    session_id = attach['sessionId']
    
    # Enable Debugger
    await connector.call('Debugger.enable', session_id=session_id)
    print("Debugger enabled\n")
    
    # Collect all script events
    all_scripts = []
    
    def on_script_parsed(params):
        if params.get("sessionId") != session_id:
            return
        all_scripts.append(params)
    
    connector.on_event("Debugger.scriptParsed", on_script_parsed)
    
    # Wait to collect current scripts (no reload to avoid issues)
    print("Collecting current scripts...")
    
    # Wait for scripts
    await asyncio.sleep(8)
    
    print(f"Total scripts collected: {len(all_scripts)}\n")
    
    # Look for index.abdfeb54.js specifically
    index_scripts = []
    for script in all_scripts:
        url = script.get('url', '')
        if 'index' in url and 'abdfeb54' in url:
            index_scripts.append(script)
    
    if index_scripts:
        print(f"Found {len(index_scripts)} script(s) matching 'index.abdfeb54':\n")
        for i, script in enumerate(index_scripts, 1):
            print(f"{i}. Script details:")
            print(f"   Script ID: {script.get('scriptId')}")
            print(f"   URL: {script.get('url', '')}")
            print(f"   Has sourceMapURL: {'sourceMapURL' in script}")
            if 'sourceMapURL' in script:
                source_map = script.get('sourceMapURL', '')
                if source_map:
                    print(f"   Source Map URL: {source_map[:200] if not source_map.startswith('data:') else 'data:... (inline)'}")
                else:
                    print(f"   Source Map URL: (empty string)")
            else:
                print(f"   Source Map URL: (field not present)")
            print(f"   hasSourceURL: {script.get('hasSourceURL', False)}")
            print(f"   All fields: {list(script.keys())}")
            print()
    else:
        print("No scripts found matching 'index.abdfeb54'")
        
        # Search more broadly
        print("\nSearching for any 'index' scripts:")
        index_any = [s for s in all_scripts if 'index' in s.get('url', '').lower()]
        print(f"Found {len(index_any)} scripts with 'index' in URL")
        
        if index_any:
            print("\nFirst 5 'index' scripts:")
            for i, script in enumerate(index_any[:5], 1):
                url = script.get('url', '')
                has_map = 'sourceMapURL' in script and script.get('sourceMapURL')
                print(f"{i}. {url[:100]}")
                print(f"   Has source map: {has_map}")
    
    # Also check if any scripts at all have source maps
    scripts_with_maps = [s for s in all_scripts if s.get('sourceMapURL')]
    print(f"\n\nTotal scripts with source maps: {len(scripts_with_maps)}")
    
    if scripts_with_maps:
        print("\nFirst 5 scripts with source maps:")
        for i, script in enumerate(scripts_with_maps[:5], 1):
            print(f"{i}. {script.get('url', '')[:100]}")
            map_url = script.get('sourceMapURL', '')
            if map_url.startswith('data:'):
                print(f"   Map: inline data URL")
            else:
                print(f"   Map: {map_url[:100]}")
    
    await connector.disconnect()
    print("\n✅ Check completed")

if __name__ == "__main__":
    asyncio.run(check_specific_source_map())