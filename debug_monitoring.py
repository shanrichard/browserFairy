#!/usr/bin/env python
"""Debug script to trace data flow in BrowserFairy monitoring."""

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

async def debug_monitor():
    """Debug monitoring with detailed logging."""
    
    from browserfairy.core.connector import ChromeConnector
    from browserfairy.monitors.tabs import TabMonitor
    from browserfairy.monitors.memory import MemoryMonitor, MemoryCollector
    from browserfairy.data.manager import DataManager
    from functools import partial
    
    print("=== Starting Debug Monitor ===")
    
    # 1. 连接 Chrome
    connector = ChromeConnector(host="127.0.0.1", port=9222)
    try:
        print("1. Connecting to Chrome...")
        await connector.connect()
        print("✓ Connected to Chrome")
        
        # 2. 初始化组件
        print("\n2. Initializing components...")
        tab_monitor = TabMonitor(connector)
        memory_monitor = MemoryMonitor(connector)
        data_manager = DataManager(connector)
        
        # 3. 启动数据管理
        print("\n3. Starting data manager...")
        await data_manager.start()
        print(f"✓ Session directory: {data_manager.session_dir}")
        
        # 4. 创建数据回调
        print("\n4. Setting up callbacks...")
        
        async def debug_data_callback(data_manager, data: dict):
            """Debug data callback with logging."""
            hostname = data.get("hostname", "unknown")
            data_type = data.get("type", "unknown")
            
            print(f"📊 DATA CALLBACK: type={data_type}, hostname={hostname}")
            print(f"   Data keys: {list(data.keys())}")
            
            try:
                if data_type == "memory":
                    print(f"   → Writing memory data for {hostname}")
                    await data_manager.write_memory_data(hostname, data)
                    print(f"   ✓ Memory data written")
                elif data_type in ["console", "exception"]:
                    print(f"   → Writing console data for {hostname}")
                    await data_manager.write_console_data(hostname, data)
                elif data_type in ["network_request_complete", "network_request_failed", "network_request_start"]:
                    print(f"   → Writing network data for {hostname}")
                    await data_manager.write_network_data(hostname, data)
                elif data_type == "correlation":
                    print(f"   → Writing correlation data for {hostname}")
                    await data_manager.write_correlation_data(hostname, data)
                else:
                    print(f"   ⚠️ Unknown data type: {data_type}")
            except Exception as e:
                print(f"   ❌ Error writing data: {e}")
                import traceback
                traceback.print_exc()
        
        unified_callback = partial(debug_data_callback, data_manager)
        memory_monitor.set_data_callback(unified_callback)
        
        # 5. 设置标签页事件处理
        print("\n5. Setting up tab event handler...")
        
        async def on_tab_event(event_type: str, payload: dict):
            target_id = payload["targetId"]
            hostname = payload["hostname"]
            
            print(f"📑 TAB EVENT: {event_type} - {hostname} ({target_id[:8]})")
            
            if event_type == "CREATED":
                print(f"   → Creating collector for {hostname}")
                collector = MemoryCollector(
                    connector=connector,
                    target_id=target_id,
                    hostname=hostname,
                    data_callback=unified_callback,
                    enable_comprehensive=True
                )
                await collector.attach()
                memory_monitor.collectors[target_id] = collector
                
                # 手动启动收集任务
                print(f"   → Starting collection task")
                collector.collection_task = asyncio.create_task(collector.start_collection())
                print(f"   ✓ Collector created and started")
                
            elif event_type == "DESTROYED":
                print(f"   → Removing collector for {hostname}")
                await memory_monitor.remove_collector(target_id)
                
            elif event_type == "URL_CHANGED":
                collector = memory_monitor.collectors.get(target_id)
                if collector and collector.hostname != hostname:
                    print(f"   → Hostname changed, recreating collector")
                    await memory_monitor.remove_collector(target_id)
                    collector = MemoryCollector(
                        connector=connector,
                        target_id=target_id,
                        hostname=hostname,
                        data_callback=unified_callback,
                        enable_comprehensive=True
                    )
                    await collector.attach()
                    memory_monitor.collectors[target_id] = collector
                    collector.collection_task = asyncio.create_task(collector.start_collection())
        
        tab_monitor.event_callback = on_tab_event
        
        # 6. 启动监控
        print("\n6. Starting tab monitoring...")
        await tab_monitor.start_monitoring()
        
        # 7. 获取当前标签页
        print("\n7. Getting current tabs...")
        current_targets = await tab_monitor.get_current_targets()
        print(f"   Found {len(current_targets)} tabs")
        
        for target_id, target_info in current_targets.items():
            hostname = target_info.get("hostname")
            url = target_info.get("url", "")
            title = target_info.get("title", "")
            print(f"   - {hostname}: {title[:50]} ({target_id[:8]})")
            
            if hostname:
                print(f"     → Creating collector for existing tab")
                collector = MemoryCollector(
                    connector=connector,
                    target_id=target_id,
                    hostname=hostname,
                    data_callback=unified_callback,
                    enable_comprehensive=True
                )
                await collector.attach()
                memory_monitor.collectors[target_id] = collector
                collector.collection_task = asyncio.create_task(collector.start_collection())
                collector.update_page_info(url, title)
        
        print(f"\n✓ Monitoring {memory_monitor.get_collector_count()} tabs")
        print(f"✓ Data directory: {data_manager.data_dir}")
        
        # 8. 运行监控 20 秒
        print("\n8. Running monitoring for 20 seconds...")
        await asyncio.sleep(20)
        
        print("\n9. Stopping monitoring...")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        
    finally:
        # 清理
        print("\n10. Cleaning up...")
        if 'data_manager' in locals():
            await data_manager.stop()
            print("   ✓ Data manager stopped")
        if 'memory_monitor' in locals():
            await memory_monitor.stop_all_collectors()
            print("   ✓ Memory monitor stopped")
        if 'tab_monitor' in locals():
            await tab_monitor.stop_monitoring()
            print("   ✓ Tab monitor stopped")
        if connector.websocket:
            await connector.disconnect()
            print("   ✓ Disconnected from Chrome")
        
        # 检查生成的文件
        print("\n11. Checking generated files...")
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

if __name__ == "__main__":
    asyncio.run(debug_monitor())