#!/usr/bin/env python3
"""Debug script to check available GC-related metrics from Performance.getMetrics"""

import asyncio
import json
from browserfairy.core.connector import ChromeConnector

async def debug_gc_metrics():
    """Check what GC-related metrics are available from Chrome CDP"""
    connector = ChromeConnector()
    
    try:
        print("Connecting to Chrome...")
        await connector.connect()
        
        # Get targets
        targets_response = await connector.get_targets()
        page_targets = connector.filter_page_targets(targets_response)
        
        if not page_targets:
            print("No page targets found. Please open a Chrome tab.")
            return
        
        target = page_targets[0]
        target_id = target["targetId"]
        
        print(f"Attaching to target: {target_id}")
        attach_response = await connector.call(
            "Target.attachToTarget",
            {"targetId": target_id, "flatten": True}
        )
        session_id = attach_response["sessionId"]
        
        # Enable Performance domain
        await connector.call("Performance.enable", session_id=session_id)
        
        # Get all available metrics
        print("\nGetting Performance.getMetrics()...")
        metrics_response = await connector.call("Performance.getMetrics", session_id=session_id)
        
        # Filter and display GC-related metrics
        all_metrics = metrics_response.get("metrics", [])
        
        print(f"\nTotal metrics available: {len(all_metrics)}")
        print("\nAll available metrics:")
        for metric in all_metrics:
            name = metric["name"]
            value = metric["value"]
            print(f"  {name}: {value}")
        
        print("\nPotential GC-related metrics:")
        gc_keywords = ["gc", "garbage", "heap", "collect", "major", "minor"]
        for metric in all_metrics:
            name_lower = metric["name"].lower()
            if any(keyword in name_lower for keyword in gc_keywords):
                print(f"  🎯 {metric['name']}: {metric['value']}")
        
        # Clean up
        await connector.call("Target.detachFromTarget", {"sessionId": session_id})
        
    except Exception as e:
        print(f"Error: {e}")
    finally:
        if connector.websocket:
            await connector.disconnect()

if __name__ == "__main__":
    asyncio.run(debug_gc_metrics())