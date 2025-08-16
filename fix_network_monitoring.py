#!/usr/bin/env python
"""Fix network monitoring by analyzing the sessionId issue."""

import asyncio
import json
import logging
from datetime import datetime

# 设置详细日志
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

async def test_sessionid_injection():
    """Test if sessionId is properly injected into network events."""
    
    from browserfairy.core.connector import ChromeConnector
    
    print("=== Testing SessionId Injection ===\n")
    
    connector = ChromeConnector(host="127.0.0.1", port=9222)
    
    captured_events = []
    
    def capture_network_event(params):
        """Capture network events with their params."""
        captured_events.append(params)
        
        # Check if sessionId is in params
        if "sessionId" in params:
            print(f"✓ SessionId found in params: {params['sessionId'][:20]}...")
        else:
            print(f"❌ SessionId NOT in params for request: {params.get('request', {}).get('url', 'unknown')[:50]}")
    
    try:
        print("1. Connecting to Chrome...")
        await connector.connect()
        print("✓ Connected\n")
        
        # Get first tab
        targets = await connector.get_targets()
        page_targets = connector.filter_page_targets(targets)
        
        if not page_targets:
            print("❌ No tabs found")
            return
            
        target = page_targets[0]
        target_id = target["targetId"]
        
        print(f"2. Using tab: {target.get('title', '')[:50]}")
        
        # Attach to target
        response = await connector.call(
            "Target.attachToTarget",
            {"targetId": target_id, "flatten": True}
        )
        session_id = response["sessionId"]
        print(f"✓ Attached with session: {session_id}\n")
        
        # Enable Network domain
        await connector.call("Network.enable", session_id=session_id)
        print("✓ Network domain enabled\n")
        
        # Register event handlers
        connector.on_event("Network.requestWillBeSent", capture_network_event)
        connector.on_event("Network.responseReceived", capture_network_event)
        
        print("3. Triggering page reload...\n")
        try:
            await connector.call("Page.reload", session_id=session_id)
        except:
            print("Please manually refresh the page\n")
        
        print("4. Capturing events for 10 seconds...\n")
        print("-" * 60)
        
        await asyncio.sleep(10)
        
        print("-" * 60)
        print(f"\n✓ Captured {len(captured_events)} events\n")
        
        # Analyze captured events
        with_sessionid = sum(1 for e in captured_events if "sessionId" in e)
        without_sessionid = len(captured_events) - with_sessionid
        
        print(f"Analysis:")
        print(f"  Events WITH sessionId: {with_sessionid}")
        print(f"  Events WITHOUT sessionId: {without_sessionid}")
        
        if without_sessionid > 0:
            print(f"\n⚠️ PROBLEM: {without_sessionid} events don't have sessionId!")
            print("This is why NetworkMonitor filtering fails.")
            
            # Show some examples
            print("\nExamples of events without sessionId:")
            for event in captured_events[:5]:
                if "sessionId" not in event:
                    url = event.get("request", {}).get("url", "") or event.get("response", {}).get("url", "")
                    print(f"  - {url[:80]}")
        else:
            print("\n✓ All events have sessionId - NetworkMonitor should work!")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        
    finally:
        if connector.websocket:
            await connector.disconnect()
            print("\n✓ Disconnected")

if __name__ == "__main__":
    asyncio.run(test_sessionid_injection())