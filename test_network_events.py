#!/usr/bin/env python
"""Test if network events are being captured at all."""

import asyncio
import json
from datetime import datetime
import pytest

@pytest.mark.asyncio
async def test_network_events():
    """Test raw network event capture."""
    
    from browserfairy.core.connector import ChromeConnector
    
    print("=== Testing Raw Network Events ===\n")
    
    # 1. 连接 Chrome
    connector = ChromeConnector(host="127.0.0.1", port=9222)
    
    network_events = []
    
    def on_network_event(params):
        """Capture any network event."""
        event_type = params.get("method", "unknown")
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        if "Network" in event_type:
            print(f"[{timestamp}] 🌐 {event_type}")
            
            if event_type == "Network.requestWillBeSent":
                url = params.get("params", {}).get("request", {}).get("url", "")
                method = params.get("params", {}).get("request", {}).get("method", "")
                print(f"    → {method} {url[:100]}")
                
            elif event_type == "Network.responseReceived":
                url = params.get("params", {}).get("response", {}).get("url", "")
                status = params.get("params", {}).get("response", {}).get("status", "")
                print(f"    ← {status} {url[:100]}")
                
            elif event_type == "Network.loadingFinished":
                request_id = params.get("params", {}).get("requestId", "")
                print(f"    ✓ Finished: {request_id[:20]}")
                
            network_events.append(params)
    
    try:
        print("1. Connecting to Chrome...")
        await connector.connect()
        print("✓ Connected\n")
        
        # 2. 获取第一个标签页
        targets = await connector.get_targets()
        page_targets = connector.filter_page_targets(targets)
        
        if not page_targets:
            print("❌ No tabs found")
            return
            
        target = page_targets[0]
        target_id = target["targetId"]
        print(f"2. Using tab: {target.get('title', '')[:50]}")
        print(f"   URL: {target.get('url', '')[:100]}\n")
        
        # 3. 附加到目标并启用 Network
        print("3. Attaching to target and enabling Network domain...")
        
        # 附加到目标
        response = await connector.call(
            "Target.attachToTarget",
            {"targetId": target_id, "flatten": True}
        )
        session_id = response["sessionId"]
        print(f"✓ Attached with session: {session_id}\n")
        
        # 启用 Network domain
        await connector.call("Network.enable", session_id=session_id)
        print("✓ Network domain enabled\n")
        
        # 4. 注册事件处理器
        print("4. Registering event handlers...")
        
        # 注册所有网络事件
        connector.on_event("Network.requestWillBeSent", lambda p: on_network_event({"method": "Network.requestWillBeSent", "params": p}))
        connector.on_event("Network.responseReceived", lambda p: on_network_event({"method": "Network.responseReceived", "params": p}))
        connector.on_event("Network.loadingFinished", lambda p: on_network_event({"method": "Network.loadingFinished", "params": p}))
        connector.on_event("Network.loadingFailed", lambda p: on_network_event({"method": "Network.loadingFailed", "params": p}))
        
        print("✓ Handlers registered\n")
        
        # 5. 触发页面刷新以生成网络活动
        print("5. Triggering page reload...")
        try:
            await connector.call("Page.reload", session_id=session_id)
            print("✓ Page reload triggered\n")
        except:
            print("⚠️ Could not trigger reload, please manually refresh the page\n")
        
        # 6. 监听事件
        print("6. Listening for network events for 20 seconds...")
        print("   (Please navigate or refresh the page to generate network activity)\n")
        print("-" * 60)
        
        await asyncio.sleep(20)
        
        print("-" * 60)
        print(f"\n✓ Captured {len(network_events)} network events")
        
        # 7. 分析捕获的事件
        if network_events:
            print("\nEvent summary:")
            event_types = {}
            for event in network_events:
                event_type = event.get("method", "unknown")
                event_types[event_type] = event_types.get(event_type, 0) + 1
            
            for event_type, count in event_types.items():
                print(f"  - {event_type}: {count}")
                
            # 检查 sessionId
            print("\nSession ID analysis:")
            sessions_found = set()
            for event in network_events:
                if "sessionId" in event.get("params", {}):
                    sessions_found.add(event["params"]["sessionId"])
            
            if sessions_found:
                print(f"  Found sessionIds in events: {sessions_found}")
            else:
                print("  ⚠️ No sessionId found in any events!")
                print("  This might be why NetworkMonitor filtering fails")
        else:
            print("\n❌ No network events captured!")
            print("Possible reasons:")
            print("  1. Page has no network activity")
            print("  2. Network domain not properly enabled")
            print("  3. Event handlers not correctly registered")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        
    finally:
        if connector.websocket:
            await connector.disconnect()
            print("\n✓ Disconnected")

if __name__ == "__main__":
    asyncio.run(test_network_events())