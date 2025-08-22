#!/usr/bin/env python
"""Check if scripts have source maps directly from Chrome"""

import asyncio
import json
from browserfairy.core import ChromeConnector

async def check_source_maps():
    print("\nDirect Source Map Check")
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
        print("No SignalPlus tab found. Please open https://t.signalplus.com")
        await connector.disconnect()
        return
    
    target = signalplus_targets[0]
    print(f"Found SignalPlus tab: {target['url'][:80]}...\n")
    
    # Attach to target
    attach = await connector.call('Target.attachToTarget', {'targetId': target['targetId'], 'flatten': True})
    session_id = attach['sessionId']
    
    # Enable Debugger
    await connector.call('Debugger.enable', session_id=session_id)
    print("Debugger enabled\n")
    
    # Get all scripts
    scripts = []
    
    def on_script_parsed(params):
        if params.get("sessionId") != session_id:
            return
        scripts.append(params)
    
    connector.on_event("Debugger.scriptParsed", on_script_parsed)
    
    # Force reload to get all scripts
    print("Reloading page to capture all scripts...")
    await connector.call('Page.enable', session_id=session_id)
    await connector.call('Page.reload', session_id=session_id)
    
    # Wait for scripts
    await asyncio.sleep(5)
    
    print(f"\nTotal scripts: {len(scripts)}")
    
    # Check for source maps
    scripts_with_maps = []
    for script in scripts:
        if script.get('sourceMapURL'):
            scripts_with_maps.append({
                'scriptId': script.get('scriptId'),
                'url': script.get('url', ''),
                'sourceMapURL': script.get('sourceMapURL', '')
            })
    
    print(f"Scripts with source maps: {len(scripts_with_maps)}")
    
    if scripts_with_maps:
        print("\nScripts with source maps:")
        for i, script in enumerate(scripts_with_maps[:10], 1):
            print(f"\n{i}. Script ID: {script['scriptId']}")
            print(f"   URL: {script['url'][:100]}")
            if script['sourceMapURL'].startswith('data:'):
                print(f"   Source Map: data:... ({len(script['sourceMapURL'])} chars)")
            else:
                print(f"   Source Map: {script['sourceMapURL'][:100]}")
    else:
        print("\n⚠️ NO SCRIPTS WITH SOURCE MAPS FOUND!")
        print("This is why source_maps directory is not created.")
        
        # Show some sample scripts
        print("\nSample scripts without source maps:")
        for i, script in enumerate(scripts[:5], 1):
            url = script.get('url', '')
            if url:
                print(f"{i}. {url[:100]}")
    
    await connector.disconnect()
    print("\n✅ Check completed")

if __name__ == "__main__":
    asyncio.run(check_source_maps())