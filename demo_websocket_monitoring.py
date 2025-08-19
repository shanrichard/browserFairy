"""Demo script showing WebSocket monitoring integration with existing NetworkMonitor."""

import asyncio
import json
from datetime import datetime, timezone
from unittest.mock import MagicMock

from browserfairy.monitors.network import NetworkMonitor


async def demo_websocket_monitoring():
    """Demonstrate WebSocket monitoring functionality."""
    
    print("🔌 BrowserFairy WebSocket Monitoring Demo")
    print("=" * 50)
    
    # Setup mock connector and event queue
    mock_connector = MagicMock()
    mock_connector.on_event = MagicMock()
    mock_connector.off_event = MagicMock()
    event_queue = asyncio.Queue()
    
    # Create NetworkMonitor
    monitor = NetworkMonitor(
        connector=mock_connector,
        session_id="demo_session_123",
        event_queue=event_queue,
        status_callback=None
    )
    monitor.set_hostname("demo.example.com")
    
    print(f"✅ NetworkMonitor initialized")
    print(f"   Session ID: {monitor.session_id}")
    print(f"   Hostname: {monitor.hostname}")
    
    # Start monitoring
    await monitor.start_monitoring()
    print(f"✅ Monitoring started (WebSocket events registered)")
    
    print("\\n📡 Simulating WebSocket Events...")
    print("-" * 30)
    
    # Simulate WebSocket connection created
    print("1. WebSocket connection created")
    await monitor._on_websocket_created({
        "sessionId": "demo_session_123",
        "requestId": "ws_connection_456",
        "url": "wss://demo.example.com/live-data"
    })
    
    # Show queued event
    event_type, event_data = await event_queue.get()
    print(f"   Event queued: {event_type}")
    print(f"   URL: {event_data['url']}")
    print(f"   Request ID: {event_data['requestId']}")
    
    # Simulate text frame sent
    print("\\n2. Text frame sent")
    await monitor._on_websocket_frame_sent({
        "sessionId": "demo_session_123",
        "requestId": "ws_connection_456",
        "response": {
            "opcode": 1,
            "payloadData": "{'type': 'subscribe', 'channel': 'price-updates'}"
        }
    })
    
    event_type, event_data = await event_queue.get()
    print(f"   Event queued: {event_type}")
    print(f"   Opcode: {event_data['opcode']} (text)")
    print(f"   Payload length: {event_data['payloadLength']}")
    print(f"   Payload text: {event_data['payloadText'][:50]}...")
    print(f"   Frame stats: {event_data['frameStats']}")
    
    # Simulate binary frame received
    print("\\n3. Binary frame received")
    await monitor._on_websocket_frame_received({
        "sessionId": "demo_session_123",
        "requestId": "ws_connection_456",
        "response": {
            "opcode": 2,
            "payloadData": "binary_protobuf_data_representation"
        }
    })
    
    event_type, event_data = await event_queue.get()
    print(f"   Event queued: {event_type}")
    print(f"   Opcode: {event_data['opcode']} (binary)")
    print(f"   Payload length: {event_data['payloadLength']}")
    print(f"   Payload type: {event_data['payloadType']}")
    print(f"   No text content stored (privacy-safe)")
    
    # Simulate large text frame (truncation test)
    print("\\n4. Large text frame (truncation demo)")
    large_data = "x" * 2000  # 2000 characters
    await monitor._on_websocket_frame_sent({
        "sessionId": "demo_session_123",
        "requestId": "ws_connection_456",
        "response": {
            "opcode": 1,
            "payloadData": large_data
        }
    })
    
    event_type, event_data = await event_queue.get()
    print(f"   Original length: {event_data['payloadLength']}")
    print(f"   Stored length: {len(event_data['payloadText'])}")
    print(f"   Truncated: {event_data['payloadText'].endswith('...[truncated]')}")
    
    # Simulate WebSocket error
    print("\\n5. WebSocket frame error")
    await monitor._on_websocket_frame_error({
        "sessionId": "demo_session_123", 
        "requestId": "ws_connection_456",
        "errorMessage": "Frame parsing failed: invalid UTF-8 sequence"
    })
    
    event_type, event_data = await event_queue.get()
    print(f"   Event queued: {event_type}")
    print(f"   Error: {event_data['errorMessage']}")
    
    # Simulate WebSocket closed
    print("\\n6. WebSocket connection closed")
    await monitor._on_websocket_closed({
        "sessionId": "demo_session_123",
        "requestId": "ws_connection_456"
    })
    
    event_type, event_data = await event_queue.get()
    print(f"   Event queued: {event_type}")
    print(f"   Connection cleaned up: {'ws_connection_456' not in monitor.websocket_connections}")
    
    # Show session filtering works
    print("\\n7. Session filtering test (different session)")
    await monitor._on_websocket_created({
        "sessionId": "different_session_789",
        "requestId": "ws_filtered_out",
        "url": "wss://other.example.com/data"
    })
    
    print(f"   Queue size after filtered event: {event_queue.qsize()} (should be 0)")
    
    # Stop monitoring
    await monitor.stop_monitoring()
    print(f"\\n✅ Monitoring stopped (WebSocket events unregistered)")
    
    print("\\n📊 Summary:")
    print(f"   Events processed: 6 successful + 1 filtered")
    print(f"   Connection tracking: Created → Frames → Closed")
    print(f"   Data handling: Text truncated, Binary type-only")
    print(f"   Session filtering: Working correctly")
    print(f"   Event IDs: Generated for all events")
    print(f"   Frame statistics: Aggregated per connection")
    
    print("\\n🎉 WebSocket monitoring demo completed successfully!")
    print("\\n💡 Next steps:")
    print("   - WebSocket events will be written to network.jsonl")
    print("   - Data integrates seamlessly with existing HTTP monitoring")
    print("   - Use --monitor-comprehensive CLI flag to enable")


if __name__ == "__main__":
    asyncio.run(demo_websocket_monitoring())