"""Command-line interface for BrowserFairy."""

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import datetime
from typing import Optional, Callable

from .core.connector import ChromeConnector, ChromeConnectionError
from .utils.paths import ensure_data_directory
from .monitors.tabs import TabMonitor, extract_hostname
from .monitors.memory import MemoryMonitor, MemoryCollector
from .data.manager import DataManager
from .data.site_manager import SiteDataManager


def setup_logging(verbose: bool = False) -> None:
    """Setup logging configuration."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(levelname)s: %(message)s"
    )

# Module-level logger (used in comprehensive_data_callback)
logger = logging.getLogger(__name__)


async def test_connection(host: str, port: int) -> int:
    """Test connection to Chrome and display version information."""
    connector = ChromeConnector(host=host, port=port)
    
    try:
        print(f"Connecting to Chrome at {host}:{port}...")
        await connector.connect()
        print("✓ Connected successfully")
        
        print("Getting browser version...")
        version_info = await connector.get_browser_version()
        
        print("\nChrome Browser Information:")
        print(f"  Browser: {version_info.get('product', 'Unknown')}")
        print(f"  Protocol Version: {version_info.get('protocolVersion', 'Unknown')}")
        print(f"  User Agent: {version_info.get('userAgent', 'Unknown')}")
        print(f"  V8 Version: {version_info.get('jsVersion', 'Unknown')}")
        
        # Test data directory creation
        print("\nTesting data directory...")
        data_dir = ensure_data_directory()
        print(f"✓ Data directory ready: {data_dir}")
        
        return 0
        
    except ChromeConnectionError as e:
        print(f"✗ Connection failed: {e}")
        print("\nTroubleshooting:")
        print("1. Make sure Chrome is running with debug port enabled:")
        print("   chrome --remote-debugging-port=9222")
        print("2. Check if another process is using the port")
        print(f"3. Try a different port with --port option")
        return 1
        
    except Exception as e:
        print(f"✗ Unexpected error: {e}")
        return 1
        
    finally:
        if connector.websocket:
            await connector.disconnect()


async def show_chrome_info(host: str, port: int) -> int:
    """Show Chrome browser information in JSON format."""
    connector = ChromeConnector(host=host, port=port)
    
    try:
        await connector.connect()
        version_info = await connector.get_browser_version()
        
        # Output JSON format, keep CDP field names consistent
        print(json.dumps(version_info, indent=2))
        return 0
        
    except ChromeConnectionError as e:
        print(f"Connection failed: {e}", file=sys.stderr)
        return 1
        
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        return 1
        
    finally:
        if connector.websocket:
            await connector.disconnect()


async def list_tabs(host: str, port: int) -> int:
    """List Chrome tabs in JSON format."""
    connector = ChromeConnector(host=host, port=port)
    
    try:
        await connector.connect()
        targets_response = await connector.get_targets()
        page_targets = connector.filter_page_targets(targets_response)
        
        # Output only page targets, keep necessary fields
        tabs_info = []
        for target in page_targets:
            tabs_info.append({
                "targetId": target.get("targetId"),
                "title": target.get("title", ""),
                "url": target.get("url", ""),
                "type": target.get("type")
            })
        
        print(json.dumps(tabs_info, indent=2))
        return 0
        
    except ChromeConnectionError as e:
        print(f"Connection failed: {e}", file=sys.stderr)
        return 1
        
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        return 1
        
    finally:
        if connector.websocket:
            await connector.disconnect()


def print_tab_event(event_type: str, payload: dict) -> None:
    """Print tab event to stdout (CLI responsibility)."""
    timestamp = payload.get("timestamp", "")
    if timestamp:
        # Convert ISO timestamp to readable format
        try:
            dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            timestamp_str = dt.strftime("%Y-%m-%d %H:%M:%S")
        except:
            timestamp_str = timestamp[:19]  # Fallback to first 19 chars
    else:
        timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    hostname = payload.get("hostname", "")
    title = payload.get("title", "")[:50]  # Truncate long titles
    target_id = payload.get("targetId", "")[:8]
    
    print(f"[{timestamp_str}] {event_type}: {hostname} - {title} ({target_id})")


def print_memory_data(memory_data: dict) -> None:
    """Print memory data to stdout (CLI responsibility)."""
    timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    hostname = memory_data.get("hostname", "")
    js_heap = memory_data.get("memory", {}).get("jsHeap", {})
    used_mb = (js_heap.get("used", 0) or 0) / (1024 * 1024)  # Convert to MB
    dom_nodes = memory_data.get("memory", {}).get("domNodes", 0) or 0
    target_id = memory_data.get("targetId", "")[:8]
    
    print(f"[{timestamp_str}] MEMORY: {hostname} - JS Heap: {used_mb:.1f}MB, DOM: {dom_nodes} nodes ({target_id})")


async def monitor_tabs(host: str, port: int) -> int:
    """Monitor Chrome tabs in real-time."""
    connector = ChromeConnector(host=host, port=port)
    
    try:
        print(f"Connecting to Chrome at {host}:{port}...")
        await connector.connect()
        print("✓ Connected successfully")
        
        print("Starting tab monitoring... (Press Ctrl+C to stop)")
        monitor = TabMonitor(connector, event_callback=print_tab_event)
        
        # Start monitoring
        await monitor.start_monitoring()
        
        # Keep running until Ctrl+C
        try:
            while True:
                await asyncio.sleep(1.0)
        except KeyboardInterrupt:
            print("\nStopping monitoring...")
            
        return 0
        
    except ChromeConnectionError as e:
        print(f"Connection failed: {e}", file=sys.stderr)
        return 1
        
    except KeyboardInterrupt:
        print("\nMonitoring stopped by user.")
        return 0
        
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        return 1
        
    finally:
        # Cleanup
        try:
            if 'monitor' in locals():
                await monitor.stop_monitoring()
        except:
            pass
            
        if connector.websocket:
            await connector.disconnect()


async def monitor_memory(host: str, port: int, duration: Optional[int] = None) -> int:
    """Monitor Chrome memory usage in real-time."""
    connector = ChromeConnector(host=host, port=port)
    
    try:
        print(f"Connecting to Chrome at {host}:{port}...")
        await connector.connect()
        print("✓ Connected successfully")
        
        print("Starting memory monitoring... (Press Ctrl+C to stop)")
        
        # Create tab monitor and memory monitor
        tab_monitor = TabMonitor(connector)
        memory_monitor = MemoryMonitor(connector)
        
        # Set memory data callback for CLI output
        memory_monitor.set_data_callback(print_memory_data)
        
        # Tab event handler for memory monitor integration
        async def on_tab_event(event_type: str, payload: dict):
            target_id = payload["targetId"]
            hostname = payload["hostname"]
            url = payload.get("url", "")
            
            if event_type == "CREATED":
                await memory_monitor.create_collector(target_id, hostname)
                print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] TAB_CREATED: {hostname} - Started memory monitoring ({target_id[:8]})")
            elif event_type == "DESTROYED":
                await memory_monitor.remove_collector(target_id)
                print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] TAB_DESTROYED: {hostname} - Stopped memory monitoring ({target_id[:8]})")
            elif event_type == "URL_CHANGED":
                # Handle hostname changes by recreating collector
                collector = memory_monitor.collectors.get(target_id)
                if collector and collector.hostname != hostname:
                    await memory_monitor.remove_collector(target_id)
                    await memory_monitor.create_collector(target_id, hostname)
                elif collector:
                    # Same hostname, just update page info
                    collector.update_page_info(payload["url"], payload.get("title", ""))
                else:
                    # No collector yet (e.g. started as chrome://newtab then navigated to http/https)
                    await memory_monitor.create_collector(target_id, hostname)
                    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] TAB_UPGRADED: {hostname} - Started memory monitoring on URL change ({target_id[:8]})")
        
        # Set up tab monitor with memory integration
        tab_monitor.event_callback = on_tab_event
        
        # Start monitoring
        await tab_monitor.start_monitoring()
        
        # Initialize memory collectors for existing tabs
        current_targets = await tab_monitor.get_current_targets()
        await memory_monitor.initialize_collectors(current_targets)
        
        print(f"✓ Monitoring {memory_monitor.get_collector_count()} tabs")
        
        # Keep running until Ctrl+C or duration expires
        try:
            if duration:
                await asyncio.sleep(duration)
                print(f"\nMonitoring duration ({duration}s) completed.")
            else:
                while True:
                    await asyncio.sleep(1.0)
        except KeyboardInterrupt:
            print("\nStopping monitoring...")
            
        return 0
        
    except ChromeConnectionError as e:
        print(f"Connection failed: {e}", file=sys.stderr)
        return 1
        
    except KeyboardInterrupt:
        print("\nMonitoring stopped by user.")
        return 0
        
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        return 1
        
    finally:
        # Cleanup
        try:
            if 'memory_monitor' in locals():
                await memory_monitor.stop_all_collectors()
            if 'tab_monitor' in locals():
                await tab_monitor.stop_monitoring()
        except:
            pass
            
        if connector.websocket:
            await connector.disconnect()


async def start_data_collection(host: str, port: int, duration: Optional[int] = None) -> int:
    """启动完整的数据收集（内存+存储监控+文件写入）"""
    connector = ChromeConnector(host=host, port=port)
    
    try:
        print(f"Connecting to Chrome at {host}:{port}...")
        await connector.connect()
        print("✓ Connected to Chrome")
        
        # 初始化各组件（复用现有顺序）
        tab_monitor = TabMonitor(connector)
        memory_monitor = MemoryMonitor(connector) 
        data_manager = DataManager(connector)  # 新增
        
        # 启动数据管理
        await data_manager.start()
        print(f"✓ Data collection session: {data_manager.session_dir.name}")
        
        # 设置内存数据回调到文件写入
        async def memory_data_callback(memory_data: dict) -> None:
            await data_manager.write_memory_data(memory_data["hostname"], memory_data)
        
        memory_monitor.set_data_callback(memory_data_callback)
        
        # 复用现有的TabMonitor集成逻辑
        async def on_tab_event(event_type: str, payload: dict):
            target_id = payload["targetId"]
            hostname = payload["hostname"]
            
            if event_type == "CREATED":
                await memory_monitor.create_collector(target_id, hostname)
                print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] TAB_CREATED: {hostname} - Started monitoring ({target_id[:8]})")
            elif event_type == "DESTROYED":
                await memory_monitor.remove_collector(target_id)
                print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] TAB_DESTROYED: {hostname} - Stopped monitoring ({target_id[:8]})")
            elif event_type == "URL_CHANGED":
                # Handle hostname changes by recreating collector
                collector = memory_monitor.collectors.get(target_id)
                if collector and collector.hostname != hostname:
                    await memory_monitor.remove_collector(target_id)
                    await memory_monitor.create_collector(target_id, hostname)
                elif collector:
                    # Same hostname, just update page info
                    collector.update_page_info(payload["url"], payload.get("title", ""))
                else:
                    # No collector yet (tab started as chrome://newtab then navigated to web)
                    await memory_monitor.create_collector(target_id, hostname)
                    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] TAB_UPGRADED: {hostname} - Started monitoring on URL change ({target_id[:8]})")
        
        # 启动监控（复用现有流程）
        tab_monitor.event_callback = on_tab_event
        await tab_monitor.start_monitoring()
        
        # 初始化现有标签页
        current_targets = await tab_monitor.get_current_targets()
        await memory_monitor.initialize_collectors(current_targets)
        
        print(f"✓ Monitoring {memory_monitor.get_collector_count()} tabs with data collection")
        print(f"✓ Data directory: {data_manager.data_dir}")
        
        # 运行指定时间或直到Ctrl+C
        if duration:
            print(f"Running data collection for {duration} seconds...")
            await asyncio.sleep(duration)
            print(f"\nData collection duration ({duration}s) completed.")
        else:
            print("Data collection running... (Press Ctrl+C to stop)")
            try:
                while True:
                    await asyncio.sleep(1.0)
            except KeyboardInterrupt:
                print("\nStopping data collection...")
        
        return 0
        
    except ChromeConnectionError as e:
        print(f"Connection failed: {e}", file=sys.stderr)
        return 1
        
    except KeyboardInterrupt:
        print("\nData collection stopped by user.")
        return 0
        
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        return 1
        
    finally:
        # 清理（复用现有模式）
        try:
            if 'data_manager' in locals():
                await data_manager.stop()
            if 'memory_monitor' in locals():
                await memory_monitor.stop_all_collectors()
            if 'tab_monitor' in locals():
                await tab_monitor.stop_monitoring()
        except:
            pass
            
        if connector.websocket:
            await connector.disconnect()


async def comprehensive_data_callback(data_manager, data: dict):
    """Unified data routing callback - single exit point for comprehensive monitoring."""
    hostname = data.get("hostname", "unknown")
    data_type = data.get("type", "unknown")
    
    # Debug logging
    logger.debug(f"comprehensive_data_callback: type={data_type}, hostname={hostname}")
    
    try:
        if data_type == "memory":
            await data_manager.write_memory_data(hostname, data)
        elif data_type in ["console", "exception"]:
            await data_manager.write_console_data(hostname, data)
        elif data_type in ["network_request_complete", "network_request_failed", "network_request_start"]:
            await data_manager.write_network_data(hostname, data)
        elif data_type in [
            "domstorage_added", "domstorage_removed", "domstorage_updated", "domstorage_cleared"
        ]:
            await data_manager.write_storage_event(hostname, data)
        elif data_type == "correlation":
            await data_manager.write_correlation_data(hostname, data)
        elif data_type == "gc_event":
            await data_manager.write_gc_data(hostname, data)
        elif data_type == "longtask":
            await data_manager.write_longtask_data(hostname, data)
        elif data_type == "longtask_limitation":
            await data_manager.write_longtask_data(hostname, data)  # 同一文件
        else:
            logger.warning(f"Unknown data type for routing: {data_type}")
            
    except Exception as e:
        logger.error(f"Error writing {data_type} data to DataManager: {e}")


async def monitor_comprehensive(host: str, port: int, duration: Optional[int] = None,
                              status_callback: Optional[Callable] = None,
                              exit_event: Optional[asyncio.Event] = None,
                              config: Optional['MonitorConfig'] = None) -> int:
    """Start comprehensive monitoring - daemon support version."""
    connector = ChromeConnector(host=host, port=port)
    
    # Set connection lost callback for daemon mode
    if exit_event:
        connector.set_connection_lost_callback(lambda: exit_event.set())
    
    try:
        print(f"Connecting to Chrome at {host}:{port}...")
        await connector.connect()
        print("✓ Connected to Chrome")
        
        # Initialize components 
        tab_monitor = TabMonitor(connector)
        memory_monitor = MemoryMonitor(connector) 
        
        # Create DataManager with config data_dir if provided
        if config and config.data_dir:
            data_manager = DataManager(connector, data_dir=config.data_dir)
        else:
            data_manager = DataManager(connector)
        
        # Start data management
        await data_manager.start()
        print(f"✓ Comprehensive monitoring session: {data_manager.session_dir.name}")
        
        # Create unified data callback with optional filtering
        if config:
            # Create filtered callback wrapper
            original_callback = comprehensive_data_callback  # Capture reference via closure
            
            async def unified_filtered_callback(data):
                """Filter data based on config before calling original callback"""
                data_type = data.get('type', '')
                
                # Filter based on data type
                if data_type == 'memory':
                    if not config.should_collect('memory'):
                        return
                        
                elif data_type == 'console':
                    level = data.get('level', 'log')
                    if not config.should_collect('console', level):
                        return
                        
                elif data_type == 'exception':
                    if not config.should_collect('exception'):
                        return
                        
                elif data_type in ['network_request_start', 
                                 'network_request_complete', 
                                 'network_request_failed']:
                    # Map network subtypes
                    if data_type == 'network_request_failed':
                        if not config.should_collect('network', 'failed'):
                            return
                    elif data_type == 'network_request_complete':
                        if not config.should_collect('network', 'complete'):
                            return
                    elif data_type == 'network_request_start':
                        if not config.should_collect('network', 'start'):
                            return
                
                elif data_type == 'gc_event':
                    if not config.should_collect('gc'):
                        return
                
                # If not filtered, call original callback
                await original_callback(data_manager, data)
            
            unified_callback = unified_filtered_callback
        else:
            # No config, use original callback with partial
            from functools import partial
            unified_callback = partial(comprehensive_data_callback, data_manager)
        
        # Set comprehensive monitoring callback
        memory_monitor.set_data_callback(unified_callback)
        
        # Status callback for real-time feedback - use injected callback if provided
        if not status_callback:
            # Default print callback for foreground mode
            def status_callback(event_type: str, payload: dict) -> None:
                timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                if event_type == "console_error":
                    print(f"[{timestamp_str}] CONSOLE_ERROR: {payload.get('level', '')} - {payload.get('message', '')}")
                elif event_type == "large_request":
                    print(f"[{timestamp_str}] LARGE_REQUEST: {payload.get('url', '')} ({payload.get('size_mb', 0):.1f}MB)")
                elif event_type == "large_response":
                    print(f"[{timestamp_str}] LARGE_RESPONSE: {payload.get('url', '')} ({payload.get('size_mb', 0):.1f}MB)")
                elif event_type == "correlation_found":
                    print(f"[{timestamp_str}] CORRELATION: {payload.get('severity', '')} - {payload.get('count', 0)} correlations")
        
        # Tab event handler for comprehensive memory monitoring
        async def on_tab_event(event_type: str, payload: dict):
            target_id = payload["targetId"]
            hostname = payload["hostname"]
            
            if event_type == "CREATED":
                # Create collector with comprehensive monitoring enabled
                collector = MemoryCollector(
                    connector=connector,
                    target_id=target_id,
                    hostname=hostname,
                    data_callback=unified_callback,
                    enable_comprehensive=True,
                    status_callback=status_callback
                )
                await collector.attach()
                memory_monitor.collectors[target_id] = collector
                
                # Start collection manually
                collector.collection_task = asyncio.create_task(collector.start_collection())
                
                print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] TAB_CREATED: {hostname} - Comprehensive monitoring started ({target_id[:8]})")
                # Update initial page info and trigger page-level estimate immediately
                try:
                    url = payload.get("url", "")
                    title = payload.get("title", "")
                    collector.update_page_info(url, title)
                    origin = data_manager._extract_origin_from_url(url) if url else None
                    await data_manager.trigger_page_estimate(collector.session_id, origin, hostname)
                except Exception:
                    pass
                
            elif event_type == "DESTROYED":
                await memory_monitor.remove_collector(target_id)
                print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] TAB_DESTROYED: {hostname} - Monitoring stopped ({target_id[:8]})")
                
            elif event_type == "URL_CHANGED":
                # Handle hostname changes by recreating collector
                collector = memory_monitor.collectors.get(target_id)
                if collector and collector.hostname != hostname:
                    await memory_monitor.remove_collector(target_id)
                    # Recreate with new hostname
                    collector = MemoryCollector(
                        connector=connector,
                        target_id=target_id,
                        hostname=hostname,
                        data_callback=unified_callback,
                        enable_comprehensive=True,
                        status_callback=status_callback
                    )
                    await collector.attach()
                    memory_monitor.collectors[target_id] = collector
                    collector.collection_task = asyncio.create_task(collector.start_collection())
                elif collector:
                    # Same hostname, just update page info
                    collector.update_page_info(payload["url"], payload.get("title", ""))
                    # Trigger page-level estimate on URL change
                    try:
                        new_origin = data_manager._extract_origin_from_url(payload.get("url", ""))
                        await data_manager.trigger_page_estimate(collector.session_id, new_origin, hostname)
                    except Exception:
                        pass
                else:
                    # No collector yet (e.g., from chrome://newtab to https://...)
                    collector = MemoryCollector(
                        connector=connector,
                        target_id=target_id,
                        hostname=hostname,
                        data_callback=unified_callback,
                        enable_comprehensive=True,
                        status_callback=status_callback
                    )
                    await collector.attach()
                    memory_monitor.collectors[target_id] = collector
                    collector.collection_task = asyncio.create_task(collector.start_collection())
                    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] TAB_UPGRADED: {hostname} - Comprehensive monitoring started on URL change ({target_id[:8]})")
                    # Trigger page-level estimate after upgrade
                    try:
                        origin = data_manager._extract_origin_from_url(payload.get("url", ""))
                        await data_manager.trigger_page_estimate(collector.session_id, origin, hostname)
                    except Exception:
                        pass
        
        # Start monitoring
        tab_monitor.event_callback = on_tab_event
        await tab_monitor.start_monitoring()
        
        # Initialize comprehensive monitoring for existing tabs
        current_targets = await tab_monitor.get_current_targets()
        
        # DEBUG: Print initial targets
        print(f"[DEBUG] Initial targets found: {len(current_targets)}")
        for target_id, target_info in current_targets.items():
            print(f"[DEBUG] Initial target: {target_info.get('hostname')} - {target_info.get('url', '')[:50]} ({target_id[:8]})")
        
        for target_id, target_info in current_targets.items():
            hostname = target_info.get("hostname")
            if hostname:
                collector = MemoryCollector(
                    connector=connector,
                    target_id=target_id,
                    hostname=hostname,
                    data_callback=unified_callback,
                    enable_comprehensive=True,
                    status_callback=status_callback
                )
                await collector.attach()
                memory_monitor.collectors[target_id] = collector
                collector.collection_task = asyncio.create_task(collector.start_collection())
                # Update page info
                collector.update_page_info(
                    target_info.get("url", ""),
                    target_info.get("title", "")
                )
                # Trigger initial page-level estimate
                try:
                    origin = data_manager._extract_origin_from_url(target_info.get("url", ""))
                    await data_manager.trigger_page_estimate(collector.session_id, origin, hostname)
                except Exception:
                    pass
        
        print(f"✓ Comprehensive monitoring {memory_monitor.get_collector_count()} tabs")
        print(f"✓ Data directory: {data_manager.data_dir}")
        print("✓ Monitoring: Memory + Console + Network + GC + Correlations")
        
        # Run monitoring - support daemon mode exit_event
        if duration:
            print(f"Running comprehensive monitoring for {duration} seconds...")
            await asyncio.sleep(duration)
            print(f"\nComprehensive monitoring duration ({duration}s) completed.")
        else:
            print("Comprehensive monitoring running... (Press Ctrl+C to stop)")
            try:
                if exit_event:
                    # Daemon mode: wait for exit_event signal
                    await exit_event.wait()
                else:
                    # Foreground mode: keep original infinite loop
                    while True:
                        await asyncio.sleep(1.0)
            except KeyboardInterrupt:
                print("\nStopping comprehensive monitoring...")
        
        return 0
        
    except ChromeConnectionError as e:
        print(f"Connection failed: {e}", file=sys.stderr)
        return 1
        
    except KeyboardInterrupt:
        print("\nComprehensive monitoring stopped by user.")
        return 0
        
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        return 1
        
    finally:
        # Cleanup
        try:
            if 'data_manager' in locals():
                await data_manager.stop()
            if 'memory_monitor' in locals():
                await memory_monitor.stop_all_collectors()
            if 'tab_monitor' in locals():
                await tab_monitor.stop_monitoring()
        except:
            pass
            
        if connector.websocket:
            await connector.disconnect()


async def start_monitoring_service(log_file: Optional[str] = None, 
                                 duration: Optional[int] = None) -> int:
    """启动完整监控服务 - 极简封装"""
    from .service import BrowserFairyService
    from .utils.paths import ensure_data_directory
    
    # 设置默认日志文件
    if not log_file:
        data_dir = ensure_data_directory()
        log_file = str(data_dir / "monitor.log")
    
    # 创建并启动服务
    service = BrowserFairyService(log_file=log_file)
    
    print("BrowserFairy starting comprehensive monitoring...")
    print(f"Monitor log: {log_file}")
    print("Chrome will be launched automatically.")
    print("Close Chrome browser to stop monitoring.")
    
    return await service.start_monitoring(duration)


async def run_daemon_start_monitoring(log_file: Optional[str] = None, 
                                    duration: Optional[int] = None) -> int:
    """daemon模式的start_monitoring - 复用现有daemon框架"""
    import atexit
    from pathlib import Path
    
    # 设置文件路径（复用现有逻辑）
    data_dir = ensure_data_directory()
    pid_path = data_dir / "monitor.pid"
    if not log_file:
        log_file = str(data_dir / "monitor.log")
    else:
        log_file = os.path.expanduser(log_file)
    
    # 简单fork（复用现有daemon代码）
    pid = os.fork()
    if pid > 0:
        print("BrowserFairy daemon starting...")
        print(f"Monitor log: {log_file}")
        print("Close Chrome browser to stop monitoring.")
        sys.exit(0)
    
    # Child process: daemonize（复用现有逻辑）
    os.setsid()
    os.chdir('/')
    os.umask(0)
    
    # Redirect stdio（复用现有逻辑）
    with open('/dev/null', 'r') as dev_null_r, open('/dev/null', 'w') as dev_null_w:
        os.dup2(dev_null_r.fileno(), sys.stdin.fileno())
        os.dup2(dev_null_w.fileno(), sys.stdout.fileno())
        os.dup2(dev_null_w.fileno(), sys.stderr.fileno())
    
    # Write PID file（复用现有逻辑）
    with open(pid_path, 'w') as f:
        f.write(str(os.getpid()))
    
    # Register cleanup（复用现有逻辑）
    def cleanup():
        try:
            if pid_path.exists():
                pid_path.unlink()
        except:
            pass
    atexit.register(cleanup)
    
    # Create new event loop in child process
    import asyncio
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    # 调用start_monitoring_service而不是monitor_comprehensive
    try:
        return loop.run_until_complete(start_monitoring_service(log_file, duration))
    finally:
        loop.close()


async def monitor_single_site(host: str, port: int, duration: Optional[int] = None) -> int:
    """Minimal single-site monitor for https://t.signalplus.com.

    Connects to existing Chrome, opens the target URL, attaches a single session,
    and enables memory + console + network monitoring for that tab only.
    """
    connector = ChromeConnector(host=host, port=port)
    exit_event = asyncio.Event()

    # When connection to Chrome is lost, stop gracefully
    connector.set_connection_lost_callback(lambda: exit_event.set())

    TARGET_URL = "https://t.signalplus.com"
    HOSTNAME = "t.signalplus.com"

    try:
        print(f"Connecting to Chrome at {host}:{port}...")
        await connector.connect()
        print("✓ Connected to Chrome")

        # Create target (tab) with the URL
        create_resp = await connector.call("Target.createTarget", {"url": TARGET_URL})
        target_id = create_resp.get("targetId")
        if not target_id:
            print("Failed to create target for SignalPlus site", file=sys.stderr)
            return 1

        # Initialize data manager
        data_manager = DataManager(connector)
        await data_manager.start()
        print(f"✓ Session directory: {data_manager.session_dir}")

        # Create unified data callback using partial
        from functools import partial
        unified_callback = partial(comprehensive_data_callback, data_manager)

        # Status callback (minimal)
        def status_callback(event_type: str, payload: dict) -> None:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            if event_type == "console_error":
                print(f"[{ts}] CONSOLE_ERROR: {payload.get('level','')} {payload.get('message','')}")
            elif event_type == "large_request":
                print(f"[{ts}] LARGE_REQUEST: {payload.get('url','')} ({payload.get('size_mb',0):.1f}MB)")
            elif event_type == "large_response":
                print(f"[{ts}] LARGE_RESPONSE: {payload.get('url','')} ({payload.get('size_mb',0):.1f}MB)")

        # Create single collector for the site
        collector = MemoryCollector(
            connector=connector,
            target_id=target_id,
            hostname=HOSTNAME,
            data_callback=unified_callback,
            enable_comprehensive=True,
            status_callback=status_callback
        )

        await collector.attach()
        # Start memory collection
        collector.collection_task = asyncio.create_task(collector.start_collection())
        # Update initial page info
        collector.update_page_info(TARGET_URL, "")

        print(f"✓ Monitoring started for {TARGET_URL}")
        print("✓ Writing to:", data_manager.session_dir / HOSTNAME)

        # Run until duration or connection lost
        if duration and duration > 0:
            await asyncio.sleep(duration)
            print(f"\nSingle-site monitoring duration ({duration}s) completed.")
        else:
            print("Single-site monitoring running... (Close Chrome or Ctrl+C to stop)")
            try:
                await exit_event.wait()
            except KeyboardInterrupt:
                print("\nStopping single-site monitoring...")

        return 0

    except ChromeConnectionError as e:
        print(f"Connection failed: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        return 1
    finally:
        try:
            if 'data_manager' in locals():
                await data_manager.stop()
            if 'collector' in locals():
                await collector.stop_collection()
        except Exception:
            pass
        if connector.websocket:
            await connector.disconnect()


async def analyze_sites(hostname: Optional[str] = None) -> int:
    """分析网站数据"""
    manager = SiteDataManager()
    
    try:
        if hostname:
            # 分析特定网站
            print(f"分析网站: {hostname}")
            print("=" * 50)
            
            summary = manager.get_site_summary(hostname)
            print(f"网站: {summary['hostname']}")
            print(f"监控会话数: {len(summary['sessions'])}")
            print(f"总记录数: {summary['total_records']}")
            print(f"数据类型: {', '.join(summary['data_types'])}")
            
            # 显示每个会话的内存统计
            for session_info in summary['sessions']:
                session_id = session_info['session_id']
                print(f"\n会话 {session_id}:")
                
                if 'memory' in session_info['data_types']:
                    memory_stats = manager.get_site_memory_stats(session_id, hostname)
                    if memory_stats.get('count', 0) > 0:
                        avg_mb = int(memory_stats['avg'] / (1024 * 1024))  # 浮点转整数显示
                        max_mb = memory_stats['max'] // (1024 * 1024)
                        p95_mb = memory_stats['p95'] // (1024 * 1024)
                        print(f"  内存使用 (MB): 平均={avg_mb}, 最大={max_mb}, P95={p95_mb}, 数据点={memory_stats['count']}")
                    else:
                        print("  内存数据: 无有效数据")
                else:
                    print("  内存数据: 未监控")
                    
                print(f"  数据类型: {', '.join(session_info['data_types'])}")
            
        else:
            # 显示所有网站概览
            print("BrowserFairy 数据分析概览")
            print("=" * 50)
            
            sessions = manager.get_all_sessions()
            print(f"发现监控会话: {len(sessions)} 个")
            
            if not sessions:
                print("没有找到监控数据。请先运行 --monitor-comprehensive 或 --start-data-collection 进行数据收集。")
                return 0
            
            # 收集所有网站
            all_sites = set()
            for session_id in sessions:
                sites = manager.get_sites_for_session(session_id)
                all_sites.update(sites)
            
            if not all_sites:
                print("会话中没有找到网站数据。")
                return 0
            
            # 分组显示
            grouped_sites = manager.get_all_sites_grouped()
            print(f"\n监控网站组: {len(grouped_sites)} 个")
            
            for main_site, variants in grouped_sites.items():
                print(f"\n{main_site}:")
                if len(variants) > 1:
                    print(f"  域名变体: {', '.join(variants)}")
                else:
                    print(f"  域名: {variants[0]}")
                
                # 显示这个组的总体统计
                total_sessions = 0
                total_records = 0
                data_types = set()
                
                for variant in variants:
                    site_summary = manager.get_site_summary(variant)
                    total_sessions += len(site_summary['sessions'])
                    total_records += site_summary['total_records']
                    data_types.update(site_summary['data_types'])
                
                print(f"  监控会话: {total_sessions} 个")
                print(f"  总记录数: {total_records}")
                if data_types:
                    print(f"  数据类型: {', '.join(sorted(data_types))}")
        
        return 0
        
    except Exception as e:
        print(f"数据分析失败: {e}", file=sys.stderr)
        return 1


async def snapshot_storage_once(host: str, port: int, filter_hostname: Optional[str] = None,
                                max_value_len: int = 2048) -> int:
    """One-time DOMStorage snapshot for open page targets.

    - Connects to Chrome, lists page targets, optionally filters by hostname
    - For each selected page: attach, evaluate storage snapshot in page context,
      and write a single domstorage_snapshot record into storage.jsonl
    - No background tasks; minimal, safe, and side-effect free
    """
    connector = ChromeConnector(host=host, port=port)
    try:
        print(f"Connecting to Chrome at {host}:{port}...")
        await connector.connect()
        print("✓ Connected to Chrome")

        targets_response = await connector.get_targets()
        page_targets = connector.filter_page_targets(targets_response)

        # Select targets by optional hostname filter
        selected = []
        for t in page_targets:
            url = t.get("url", "")
            hn = extract_hostname(url) or ""
            if filter_hostname:
                if hn == (filter_hostname or "").lower():
                    selected.append((t.get("targetId"), hn, url))
            else:
                if hn:
                    selected.append((t.get("targetId"), hn, url))

        if not selected:
            print("No matching page targets found for snapshot.")
            return 0

        # Prepare data manager for writing
        data_manager = DataManager(connector)
        await data_manager.start()
        print(f"✓ Snapshot session: {data_manager.session_dir.name}")

        # JS snippet to capture estimate + local/session entries with truncation
        js = f"""
        (async () => {{
          try {{
            const MAX = {max_value_len};
            const trunc = v => {{
              try {{ v = String(v); }} catch (e) {{ v = '' + v; }}
              return v.length > MAX ? v.slice(0, MAX) + '...[truncated]' : v;
            }};
            const getEntries = s => {{
              try {{
                const out = [];
                const len = s.length || 0;
                for (let i = 0; i < len; i++) {{
                  const k = s.key(i);
                  out.push({{ key: k, value: trunc(s.getItem(k)) }});
                }}
                return out;
              }} catch (e) {{ return []; }}
            }};
            const est = (navigator.storage && navigator.storage.estimate) ? await navigator.storage.estimate() : {{}};
            return {{
              origin: (location && location.origin) || '',
              estimate: {{ quota: est.quota || 0, usage: est.usage || 0 }},
              local: getEntries(window.localStorage || {{}}),
              session: getEntries(window.sessionStorage || {{}})
            }};
          }} catch (e) {{ return {{ error: String(e) }}; }}
        }})()
        """.strip()

        # Snapshot each target
        for target_id, hostname, url in selected:
            try:
                # Attach to target
                resp = await connector.call("Target.attachToTarget", {"targetId": target_id, "flatten": True}, timeout=15.0)
                session_id = resp.get("sessionId")
                if not session_id:
                    print(f"Skip: failed to attach {target_id[:8]}")
                    continue

                # Evaluate in page context
                ev = await connector.call(
                    "Runtime.evaluate",
                    {"expression": js, "awaitPromise": True, "returnByValue": True},
                    session_id=session_id,
                    timeout=15.0
                )
                value = (ev or {}).get("result", {}).get("value", {}) or {}

                # Build snapshot record
                record = {
                    "type": "domstorage_snapshot",
                    "timestamp": datetime.now().isoformat(),
                    "hostname": hostname,
                    "targetId": target_id,
                    "origin": value.get("origin", ""),
                    "data": {
                        "estimate": value.get("estimate", {}),
                        "local": value.get("local", []),
                        "session": value.get("session", [])
                    }
                }

                await data_manager.write_storage_event(hostname, record)
                print(f"✓ Snapshot written for {hostname} ({target_id[:8]})")

            except Exception as e:
                print(f"Snapshot failed for target {target_id[:8]}: {e}")
            finally:
                # Detach best-effort
                try:
                    if 'session_id' in locals() and session_id:
                        await connector.call("Target.detachFromTarget", {"sessionId": session_id})
                except Exception:
                    pass

        await data_manager.stop()
        return 0

    except ChromeConnectionError as e:
        print(f"Connection failed: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        return 1
    finally:
        if connector.websocket:
            await connector.disconnect()


def get_default_host() -> str:
    """Get default host from environment or use 127.0.0.1."""
    return os.environ.get("CHROME_DEBUG_HOST", "127.0.0.1")


def get_default_port() -> int:
    """Get default port from environment or use 9222."""
    try:
        return int(os.environ.get("CHROME_DEBUG_PORT", "9222"))
    except ValueError:
        return 9222


async def main() -> None:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="BrowserFairy - Chrome performance monitoring tool"
    )
    
    parser.add_argument(
        "--test-connection",
        action="store_true",
        help="Test connection to Chrome and display version information"
    )
    
    parser.add_argument(
        "--chrome-info",
        action="store_true",
        help="Show Chrome browser information in JSON format"
    )
    
    parser.add_argument(
        "--list-tabs",
        action="store_true",
        help="List open Chrome tabs in JSON format"
    )
    
    parser.add_argument(
        "--monitor-tabs",
        action="store_true",
        help="Monitor Chrome tabs in real-time"
    )
    
    parser.add_argument(
        "--monitor-memory",
        action="store_true",
        help="Monitor Chrome memory usage in real-time"
    )
    
    parser.add_argument(
        "--start-data-collection",
        action="store_true",
        help="Start complete data collection (memory + storage monitoring + file writing)"
    )
    
    parser.add_argument(
        "--monitor-comprehensive",
        action="store_true",
        help="Start comprehensive monitoring (memory + console + network + correlations)"
    )
    
    parser.add_argument(
        "--monitor-signalplus",
        action="store_true",
        help="Monitor only https://t.signalplus.com in a single tab (minimal mode)"
    )
    
    parser.add_argument(
        "--start-monitoring",
        action="store_true", 
        help="Start complete monitoring service with automatic Chrome launch"
    )
    
    parser.add_argument(
        "--daemon",
        action="store_true",
        help="Run comprehensive monitoring in daemon mode (Unix only)"
    )
    
    parser.add_argument(
        "--log-file",
        type=str,
        help="Custom log file path for daemon mode"
    )

    # One-shot DOMStorage snapshot (manual, safe)
    parser.add_argument(
        "--snapshot-storage-once",
        action="store_true",
        help="Take a one-time DOMStorage snapshot (local/session + estimate) for open pages"
    )
    parser.add_argument(
        "--snapshot-hostname",
        type=str,
        help="Optional hostname filter for snapshot (only pages matching this hostname)"
    )
    parser.add_argument(
        "--snapshot-maxlen",
        type=int,
        default=2048,
        help="Max value length to capture in snapshot (default: 2048)"
    )
    
    parser.add_argument(
        "--data-dir",
        type=str,
        help="Directory to save monitoring data (default: ~/BrowserFairyData)"
    )
    
    parser.add_argument(
        "--output",
        type=str,
        default='all',
        help="Data types to collect: all, errors-only, performance, minimal, ai-debug, or comma-separated list"
    )
    
    parser.add_argument(
        "--duration",
        type=int,
        help="Duration in seconds for monitoring (default: unlimited)"
    )
    
    parser.add_argument(
        "--host",
        default=get_default_host(),
        help="Chrome debug host (default: 127.0.0.1 or CHROME_DEBUG_HOST env)"
    )
    
    parser.add_argument(
        "--port",
        type=int,
        default=get_default_port(),
        help="Chrome debug port (default: 9222 or CHROME_DEBUG_PORT env)"
    )
    
    parser.add_argument(
        "--analyze-sites",
        type=str,
        nargs="?",
        const="",
        help="Analyze website data (specify hostname or leave empty for overview)"
    )
    
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging"
    )
    
    args = parser.parse_args()
    setup_logging(args.verbose)
    
    if args.test_connection:
        exit_code = await test_connection(args.host, args.port)
        sys.exit(exit_code)
    elif args.chrome_info:
        exit_code = await show_chrome_info(args.host, args.port)
        sys.exit(exit_code)
    elif args.list_tabs:
        exit_code = await list_tabs(args.host, args.port)
        sys.exit(exit_code)
    elif args.monitor_tabs:
        exit_code = await monitor_tabs(args.host, args.port)
        sys.exit(exit_code)
    elif args.monitor_memory:
        exit_code = await monitor_memory(args.host, args.port, args.duration)
        sys.exit(exit_code)
    elif args.start_data_collection:
        exit_code = await start_data_collection(args.host, args.port, args.duration)
        sys.exit(exit_code)
    elif args.monitor_comprehensive:
        # Create config if new parameters are provided
        config = None
        if hasattr(args, 'data_dir') and args.data_dir:
            from .config import MonitorConfig
            config = MonitorConfig(
                data_dir=args.data_dir,
                output=args.output
            )
        elif hasattr(args, 'output') and args.output != 'all':
            from .config import MonitorConfig
            config = MonitorConfig(
                data_dir=None,
                output=args.output
            )
        
        if args.daemon:
            # Daemon mode (config not supported yet in daemon mode)
            if os.name != 'posix':
                print("Daemon mode not supported on Windows, running in foreground...")
                exit_code = await monitor_comprehensive(args.host, args.port, args.duration, config=config)
            else:
                exit_code = await run_daemon_comprehensive(args.host, args.port, args.duration, args.log_file)
        else:
            # Foreground mode: pass config if created
            exit_code = await monitor_comprehensive(args.host, args.port, args.duration, config=config)
        sys.exit(exit_code)
    elif args.monitor_signalplus:
        exit_code = await monitor_single_site(args.host, args.port, args.duration)
        sys.exit(exit_code)
    elif args.start_monitoring:
        if args.daemon:
            # daemon模式处理
            if os.name != 'posix':
                print("Daemon mode not supported on Windows, running in foreground...")
                exit_code = await start_monitoring_service(args.log_file, args.duration)
            else:
                exit_code = await run_daemon_start_monitoring(args.log_file, args.duration)
        else:
            # 前台模式
            exit_code = await start_monitoring_service(args.log_file, args.duration)
        sys.exit(exit_code)
    elif args.snapshot_storage_once:
        exit_code = await snapshot_storage_once(
            host=args.host,
            port=args.port,
            filter_hostname=args.snapshot_hostname,
            max_value_len=args.snapshot_maxlen
        )
        sys.exit(exit_code)
    elif args.analyze_sites is not None:
        # --analyze-sites was provided
        hostname = args.analyze_sites if args.analyze_sites else None
        exit_code = await analyze_sites(hostname)
        sys.exit(exit_code)
    else:
        parser.print_help()
        print("\nAvailable commands:")
        print("  --test-connection       Test Chrome connection")
        print("  --chrome-info           Show browser info (JSON)")
        print("  --list-tabs             List tabs (JSON)")
        print("  --monitor-tabs          Monitor tabs in real-time")
        print("  --monitor-memory        Monitor memory usage in real-time")
        print("  --start-data-collection Start data collection with file output")
        print("  --monitor-comprehensive Comprehensive monitoring (memory + console + network + correlations)")
        print("                         Add --daemon to run in background mode")
        print("  --monitor-signalplus    Monitor only https://t.signalplus.com (single-site minimal mode)")
        print("  --start-monitoring      Start complete monitoring service with automatic Chrome launch")
        print("                         Add --daemon to run in background mode")
        print("  --analyze-sites [HOST]  Analyze collected website data (specify hostname or leave empty for overview)")


async def run_daemon_comprehensive(host: str, port: int, duration: Optional[int] = None, 
                                  log_file: Optional[str] = None) -> int:
    """Minimal daemon wrapper for comprehensive monitoring."""
    import atexit
    from pathlib import Path
    
    # Set up file paths
    data_dir = ensure_data_directory()
    pid_path = data_dir / "monitor.pid"
    if not log_file:
        log_file = str(data_dir / "monitor.log")
    else:
        # Expand ~ in user-provided path
        log_file = os.path.expanduser(log_file)
    
    # Simple fork for daemon mode
    pid = os.fork()
    if pid > 0:
        # Parent process: show info and exit
        print("BrowserFairy daemon starting...")
        print(f"Monitor log: {log_file}")
        print("Close Chrome browser to stop monitoring.")
        sys.exit(0)
    
    # Child process: daemonize
    os.setsid()
    os.chdir('/')
    os.umask(0)
    
    # Redirect stdio to /dev/null
    with open('/dev/null', 'r') as dev_null_r, open('/dev/null', 'w') as dev_null_w:
        os.dup2(dev_null_r.fileno(), sys.stdin.fileno())
        os.dup2(dev_null_w.fileno(), sys.stdout.fileno())
        os.dup2(dev_null_w.fileno(), sys.stderr.fileno())
    
    # Write PID file
    with open(pid_path, 'w') as f:
        f.write(str(os.getpid()))
    
    # Register cleanup function
    def cleanup():
        try:
            if pid_path.exists():
                pid_path.unlink()
        except:
            pass
    atexit.register(cleanup)
    
    # Minimal log callback (write to file)
    def log_status(event_type: str, payload: dict) -> None:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        message = f"[{timestamp}] {event_type}: {payload}\n"
        try:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(message)
        except:
            pass  # Ignore write errors in daemon mode
    
    # Create new event loop in child process
    import asyncio
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    # Create exit event
    exit_event = asyncio.Event()
    
    # Call modified monitor_comprehensive
    try:
        return loop.run_until_complete(monitor_comprehensive(
            host=host, 
            port=port, 
            duration=duration,
            status_callback=log_status,
            exit_event=exit_event
        ))
    finally:
        loop.close()


def cli_entry_point():
    """Entry point for pip-installed command."""
    asyncio.run(main())


if __name__ == "__main__":
    asyncio.run(main())
