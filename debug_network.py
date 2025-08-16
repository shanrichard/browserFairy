#!/usr/bin/env python
"""Debug network monitoring specifically."""

import asyncio
import logging
import sys
from datetime import datetime

# 设置详细日志
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

async def debug_network():
    """Debug network monitoring."""
    
    from browserfairy.core.connector import ChromeConnector
    from browserfairy.monitors.memory import MemoryCollector
    from browserfairy.data.manager import DataManager
    from functools import partial
    
    print("=== Testing Network Monitoring ===")
    
    # 1. 连接 Chrome
    connector = ChromeConnector(host="127.0.0.1", port=9222)
    try:
        print("1. Connecting to Chrome...")
        await connector.connect()
        print("✓ Connected to Chrome")
        
        # 2. 获取第一个标签页
        targets_response = await connector.get_targets()
        page_targets = connector.filter_page_targets(targets_response)
        
        if not page_targets:
            print("❌ No tabs found. Please open a webpage in Chrome.")
            return
        
        target = page_targets[0]
        target_id = target["targetId"]
        hostname = target.get("url", "").split("//")[-1].split("/")[0].split(":")[0] or "unknown"
        
        print(f"\n2. Testing with tab: {target.get('title', 'Unknown')[:50]}")
        print(f"   Target ID: {target_id[:8]}")
        print(f"   Hostname: {hostname}")
        
        # 3. 初始化数据管理
        data_manager = DataManager(connector)
        await data_manager.start()
        print(f"\n3. Session directory: {data_manager.session_dir}")
        
        # 4. 创建详细的数据回调
        async def debug_callback(data_manager, data: dict):
            """Debug callback with detailed logging."""
            data_type = data.get("type", "unknown")
            hostname = data.get("hostname", "unknown")
            
            print(f"\n📊 DATA EVENT:")
            print(f"   Type: {data_type}")
            print(f"   Hostname: {hostname}")
            
            if "network" in data_type:
                print(f"   🌐 NETWORK EVENT DETECTED!")
                print(f"   Method: {data.get('method', 'N/A')}")
                print(f"   URL: {data.get('url', 'N/A')[:100]}")
                print(f"   Status: {data.get('status', 'N/A')}")
                print(f"   Size: {data.get('responseSize', 'N/A')} bytes")
                
                # 写入网络数据
                await data_manager.write_network_data(hostname, data)
                print(f"   ✓ Network data written to {hostname}/network.jsonl")
                
            elif data_type == "memory":
                print(f"   Memory snapshot collected")
                await data_manager.write_memory_data(hostname, data)
                
            elif data_type in ["console", "exception"]:
                print(f"   Console event: {data.get('level', '')} - {data.get('message', '')[:50]}")
                await data_manager.write_console_data(hostname, data)
        
        unified_callback = partial(debug_callback, data_manager)
        
        # 5. 创建 MemoryCollector 并启用综合监控
        print("\n4. Creating MemoryCollector with comprehensive monitoring...")
        collector = MemoryCollector(
            connector=connector,
            target_id=target_id,
            hostname=hostname,
            data_callback=unified_callback,
            enable_comprehensive=True  # 这会启用 network 监控
        )
        
        # 附加到目标
        await collector.attach()
        print("✓ Attached to target")
        
        # 检查 network monitor 是否正确初始化
        if collector.network_monitor:
            print("✓ NetworkMonitor initialized")
            print(f"   Session ID: {collector.session_id}")
            
            # 检查是否注册了事件处理器
            if collector.connector._event_handlers.get("Network.requestWillBeSent"):
                print("✓ Network.requestWillBeSent handler registered")
            else:
                print("❌ Network.requestWillBeSent handler NOT registered")
                
            if collector.connector._event_handlers.get("Network.responseReceived"):
                print("✓ Network.responseReceived handler registered")
            else:
                print("❌ Network.responseReceived handler NOT registered")
                
            if collector.connector._event_handlers.get("Network.loadingFinished"):
                print("✓ Network.loadingFinished handler registered")
            else:
                print("❌ Network.loadingFinished handler NOT registered")
                
            if collector.connector._event_handlers.get("Network.loadingFailed"):
                print("✓ Network.loadingFailed handler registered")
            else:
                print("❌ Network.loadingFailed handler NOT registered")
        else:
            print("❌ NetworkMonitor NOT initialized")
        
        # 6. 启动收集
        print("\n5. Starting collection task...")
        collection_task = asyncio.create_task(collector.start_collection())
        
        # 7. 触发一些网络活动
        print("\n6. Triggering network activity...")
        print("   Please reload the page or navigate to trigger network requests")
        print("   Or wait for automatic network activity...")
        
        # 运行 30 秒
        print("\n7. Monitoring for 30 seconds...")
        await asyncio.sleep(30)
        
        print("\n8. Stopping monitoring...")
        collector.running = False
        await collection_task
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        
    finally:
        # 清理
        print("\n9. Cleaning up...")
        if 'collector' in locals():
            await collector.detach()
            print("   ✓ Collector detached")
        if 'data_manager' in locals():
            await data_manager.stop()
            print("   ✓ Data manager stopped")
        if connector.websocket:
            await connector.disconnect()
            print("   ✓ Disconnected from Chrome")
        
        # 检查生成的文件
        print("\n10. Checking generated files...")
        if 'data_manager' in locals():
            session_dir = data_manager.session_dir
            print(f"   Session directory: {session_dir}")
            
            import os
            for root, dirs, files in os.walk(session_dir):
                level = root.replace(str(session_dir), '').count(os.sep)
                indent = '   ' * (level + 1)
                print(f"{indent}{os.path.basename(root)}/")
                subindent = '   ' * (level + 2)
                for file in files:
                    file_path = os.path.join(root, file)
                    file_size = os.path.getsize(file_path)
                    print(f"{subindent}{file} ({file_size} bytes)")
                    
                    # 如果是 network.jsonl，显示前几行
                    if file == "network.jsonl":
                        print(f"{subindent}First few network events:")
                        with open(file_path, 'r') as f:
                            for i, line in enumerate(f):
                                if i >= 3:
                                    break
                                import json
                                event = json.loads(line)
                                print(f"{subindent}  - {event.get('type', 'unknown')}: {event.get('url', 'N/A')[:50]}")

if __name__ == "__main__":
    # 先确保 Chrome 正在运行
    print("Please make sure Chrome is running with --remote-debugging-port=9222")
    print("You can start it with:")
    print('  open -a "Google Chrome" --args --remote-debugging-port=9222')
    print("")
    
    asyncio.run(debug_network())