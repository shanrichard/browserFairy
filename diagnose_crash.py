#!/usr/bin/env python
"""诊断 BrowserFairy 崩溃问题"""

import asyncio
import logging
import sys
from datetime import datetime

# 设置详细日志
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

async def diagnose_issue():
    """诊断连接问题"""
    
    from browserfairy.core.chrome_instance import ChromeInstanceManager
    from browserfairy.core.connector import ChromeConnector
    
    print("=== BrowserFairy 诊断工具 ===\n")
    
    # 1. 测试 Chrome 实例管理
    print("1. 测试 Chrome 实例管理...")
    chrome_manager = ChromeInstanceManager()
    
    try:
        print("   启动独立 Chrome 实例...")
        host_port = await chrome_manager.launch_isolated_chrome()
        host, port = host_port.split(":")
        print(f"   ✓ Chrome 启动成功: {host}:{port}")
        
        # 2. 测试连接稳定性
        print("\n2. 测试连接稳定性...")
        connector = ChromeConnector(host=host, port=int(port))
        
        # 设置连接丢失回调
        connection_lost = False
        def on_connection_lost():
            nonlocal connection_lost
            connection_lost = True
            print(f"\n   ❌ 连接丢失！时间: {datetime.now()}")
        
        connector.set_connection_lost_callback(on_connection_lost)
        
        print("   连接到 Chrome...")
        await connector.connect()
        print("   ✓ 连接成功")
        
        # 3. 测试高负载场景
        print("\n3. 测试高负载场景...")
        print("   打开测试页面...")
        
        # 创建一个测试标签页
        create_resp = await connector.call("Target.createTarget", {
            "url": "https://t.signalplus.com"
        })
        target_id = create_resp.get("targetId")
        print(f"   ✓ 创建标签页: {target_id[:8]}")
        
        # 附加到目标
        print("   附加到目标...")
        attach_resp = await connector.call(
            "Target.attachToTarget",
            {"targetId": target_id, "flatten": True}
        )
        session_id = attach_resp["sessionId"]
        print(f"   ✓ 会话建立: {session_id[:8]}")
        
        # 启用网络监控
        print("   启用网络监控...")
        await connector.call("Network.enable", session_id=session_id)
        print("   ✓ 网络监控已启用")
        
        # 4. 监控连接状态
        print("\n4. 监控连接状态 (30秒)...")
        print("   请在浏览器中进行一些操作...")
        
        event_count = 0
        def count_event(params):
            nonlocal event_count
            event_count += 1
            if event_count % 100 == 0:
                print(f"   已接收 {event_count} 个事件...")
        
        # 注册事件处理器
        connector.on_event("Network.requestWillBeSent", count_event)
        connector.on_event("Network.responseReceived", count_event)
        
        # 监控 30 秒
        start_time = asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() - start_time < 30:
            if connection_lost:
                print("\n   ⚠️ 检测到连接丢失！")
                break
                
            # 定期发送 ping 命令测试连接
            try:
                await connector.call("Browser.getVersion")
                print(f"   [{datetime.now().strftime('%H:%M:%S')}] 连接正常, 事件数: {event_count}")
            except Exception as e:
                print(f"   ❌ Ping 失败: {e}")
                break
                
            await asyncio.sleep(5)
        
        # 5. 分析结果
        print("\n5. 诊断结果:")
        if connection_lost:
            print("   ❌ 连接不稳定 - WebSocket 连接中断")
            print("   可能原因:")
            print("   - Chrome 进程崩溃")
            print("   - 内存不足")
            print("   - 网络事件过载")
        else:
            print(f"   ✓ 连接稳定")
            print(f"   - 处理了 {event_count} 个事件")
            print(f"   - Chrome 进程正常: {chrome_manager.is_chrome_running()}")
        
        # 检查 Chrome 进程状态
        if chrome_manager.is_chrome_running():
            print("   ✓ Chrome 进程仍在运行")
        else:
            print("   ❌ Chrome 进程已退出")
            if chrome_manager.chrome_process:
                exit_code = chrome_manager.chrome_process.poll()
                print(f"   退出码: {exit_code}")
        
    except Exception as e:
        print(f"\n❌ 诊断过程出错: {e}")
        import traceback
        traceback.print_exc()
        
    finally:
        print("\n6. 清理...")
        if 'connector' in locals() and connector.websocket:
            await connector.disconnect()
            print("   ✓ 断开连接")
        if 'chrome_manager' in locals():
            await chrome_manager.cleanup()
            print("   ✓ Chrome 清理完成")

if __name__ == "__main__":
    asyncio.run(diagnose_issue())