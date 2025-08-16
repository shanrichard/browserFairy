"""Chrome DevTools Protocol connector."""

import asyncio
import json
import logging
from typing import Any, Callable, Dict, List, Optional
import httpx
import websockets


logger = logging.getLogger(__name__)


class ChromeConnectionError(Exception):
    """Chrome connection related errors."""
    pass


class ChromeConnector:
    """Browser-level Chrome DevTools Protocol connection."""
    
    def __init__(self, host: str = "127.0.0.1", port: int = 9222):
        self.host = host
        self.port = port
        self.websocket = None
        self.next_id = 1
        self.pending_requests: Dict[int, asyncio.Future] = {}
        self.event_handlers: Dict[str, List[Callable]] = {}
        self.message_task: Optional[asyncio.Task] = None
        self.connection_lost_callback: Optional[Callable] = None
        # Default per-request response timeout (seconds) - increased for heavy pages
        self.call_timeout: float = 15.0
        
    async def connect(self, retries: int = 3) -> None:
        """Establish connection to Chrome DevTools Protocol with retry logic."""
        last_exception = None
        
        for attempt in range(retries):
            try:
                # Step 1: Discover WebSocket endpoint (refresh each time)
                ws_url = await self._discover_websocket_url()
                
                # Step 2: Connect to WebSocket with timeout
                # Important: Set ping_interval and ping_timeout to maintain connection
                # ping_interval=20: Send ping every 20 seconds
                # ping_timeout=10: Wait 10 seconds for pong response
                # max_size=100MB: Allow larger messages for heavy pages
                self.websocket = await asyncio.wait_for(
                    websockets.connect(
                        ws_url,
                        ping_interval=20,
                        ping_timeout=10,
                        max_size=100 * 1024 * 1024  # 100MB max message size
                    ), 
                    timeout=5.0
                )
                
                # Step 3: Start message handling
                self.message_task = asyncio.create_task(self._handle_messages())
                
                logger.info(f"Connected to Chrome successfully")
                return
                
            except asyncio.TimeoutError as e:
                last_exception = ChromeConnectionError("WebSocket connection timed out")
            except Exception as e:
                last_exception = ChromeConnectionError(f"Failed to connect to WebSocket: {e}")
            
            if attempt < retries - 1:
                # Exponential backoff: 1s, 2s, 4s
                delay = 2 ** attempt
                logger.warning(f"Connection attempt {attempt + 1} failed, retrying in {delay}s...")
                await asyncio.sleep(delay)
        
        # All retries failed
        raise last_exception
        
    async def _discover_websocket_url(self) -> str:
        """Discover Chrome's WebSocket debugger URL."""
        url = f"http://{self.host}:{self.port}/json/version"
        
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.get(url)
                response.raise_for_status()
                data = response.json()
        except httpx.ConnectError:
            import platform
            system = platform.system()
            if system == "Darwin":  # macOS
                cmd_example = "open -a 'Google Chrome' --args --remote-debugging-port=9222"
            elif system == "Windows":
                cmd_example = "chrome.exe --remote-debugging-port=9222"
            else:  # Linux and others
                cmd_example = "google-chrome --remote-debugging-port=9222"
                
            raise ChromeConnectionError(
                f"Could not connect to Chrome on {self.host}:{self.port}. "
                f"Please start Chrome with: {cmd_example}"
            )
        except httpx.TimeoutException:
            raise ChromeConnectionError(f"Connection to Chrome timed out")
        except Exception as e:
            raise ChromeConnectionError(f"Failed to discover Chrome endpoint: {e}")
            
        # Validate response structure
        if not isinstance(data, dict):
            raise ChromeConnectionError("Invalid response from Chrome debugger endpoint")
            
        if "Browser" not in data:
            raise ChromeConnectionError("Not a valid Chrome debugger endpoint")
            
        if "webSocketDebuggerUrl" not in data:
            raise ChromeConnectionError("Chrome debugger endpoint missing WebSocket URL")
            
        return data["webSocketDebuggerUrl"]
        
    async def call(self, method: str, params: Optional[Dict[str, Any]] = None, 
                   session_id: Optional[str] = None,
                   timeout: Optional[float] = None) -> Dict[str, Any]:
        """Send a Chrome DevTools Protocol command and wait for response."""
        if not self.websocket:
            raise ChromeConnectionError("Not connected to Chrome")
            
        # Prepare request
        request_id = self.next_id
        self.next_id += 1
        
        message = {
            "id": request_id,
            "method": method,
        }
        
        if params:
            message["params"] = params
            
        if session_id:
            message["sessionId"] = session_id
            
        # Create future for response
        future = asyncio.Future()
        self.pending_requests[request_id] = future
        
        try:
            # Send message
            await self.websocket.send(json.dumps(message))
            
            # Wait for response with timeout (use per-call override or default)
            wait_timeout = timeout if timeout is not None else self.call_timeout
            response = await asyncio.wait_for(future, timeout=wait_timeout)
            return response
            
        except asyncio.TimeoutError:
            self.pending_requests.pop(request_id, None)
            raise ChromeConnectionError(f"Timeout waiting for response to {method}")
        except Exception as e:
            self.pending_requests.pop(request_id, None)
            raise ChromeConnectionError(f"Error calling {method}: {e}")
            
    async def _handle_messages(self) -> None:
        """Handle incoming WebSocket messages."""
        try:
            async for message in self.websocket:
                try:
                    data = json.loads(message)
                    
                    # Handle responses (messages with id)
                    if "id" in data:
                        request_id = data["id"]
                        future = self.pending_requests.pop(request_id, None)
                        
                        if future and not future.done():
                            if "error" in data:
                                error_msg = data["error"].get("message", "Unknown error")
                                future.set_exception(ChromeConnectionError(error_msg))
                            else:
                                future.set_result(data.get("result", {}))
                    
                    # Handle events (messages without id)
                    elif "method" in data:
                        method = data["method"]
                        params = data.get("params", {}).copy()
                        
                        # Debug: Log all events with Runtime or Network prefix
                        if method.startswith("Runtime.") or method.startswith("Network."):
                            logger.debug(f"Event: {method}, sessionId in data: {data.get('sessionId')}")
                        
                        # Handle Target.receivedMessageFromTarget events
                        if method == "Target.receivedMessageFromTarget":
                            logger.debug(f"Received Target.receivedMessageFromTarget, sessionId={params.get('sessionId')}")
                            # Unpack the nested message from target session
                            session_id = params.get("sessionId")
                            message_str = params.get("message")
                            if session_id and message_str:
                                try:
                                    target_data = json.loads(message_str)
                                    if "method" in target_data:
                                        # Add sessionId to the params for filtering
                                        target_params = target_data.get("params", {}).copy()
                                        target_params["sessionId"] = session_id
                                        # Dispatch the unpacked event
                                        await self._dispatch_event(target_data["method"], target_params)
                                except json.JSONDecodeError:
                                    logger.warning(f"Failed to decode target message: {message_str[:100]}")
                        else:
                            # For flattened mode, sessionId is at the top level
                            # ✅ Critical fix: inject sessionId to params for monitor filtering
                            if "sessionId" in data:
                                params["sessionId"] = data["sessionId"]
                            
                            await self._dispatch_event(method, params)
                    
                except json.JSONDecodeError:
                    logger.warning("Received invalid JSON message")
                except Exception as e:
                    logger.warning(f"Error handling message: {e}")
                    
        except websockets.exceptions.ConnectionClosed:
            logger.info("WebSocket connection closed")
            # Notify upper layers about connection loss
            if self.connection_lost_callback:
                try:
                    if asyncio.iscoroutinefunction(self.connection_lost_callback):
                        await self.connection_lost_callback()
                    else:
                        self.connection_lost_callback()
                except Exception as e:
                    logger.warning(f"Error in connection lost callback: {e}")
        except Exception as e:
            logger.error(f"Error in message handler: {e}")
            # Notify upper layers about unexpected errors
            if self.connection_lost_callback:
                try:
                    if asyncio.iscoroutinefunction(self.connection_lost_callback):
                        await self.connection_lost_callback()
                    else:
                        self.connection_lost_callback()
                except Exception as cb_error:
                    logger.warning(f"Error in connection lost callback: {cb_error}")
            
    async def disconnect(self) -> None:
        """Close the WebSocket connection."""
        # Cancel message handling task
        if self.message_task:
            self.message_task.cancel()
            try:
                await self.message_task
            except asyncio.CancelledError:
                pass
            self.message_task = None
            
        # Close WebSocket
        if self.websocket:
            await self.websocket.close()
            self.websocket = None
            
        # Cancel pending requests
        for future in self.pending_requests.values():
            if not future.done():
                future.cancel()
        self.pending_requests.clear()
        
    async def get_browser_version(self) -> Dict[str, Any]:
        """Get Chrome browser version information."""
        return await self.call("Browser.getVersion")
    
    async def get_targets(self) -> Dict[str, Any]:
        """Get list of available targets."""
        return await self.call("Target.getTargets")
    
    def filter_page_targets(self, targets_response: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Filter targets to only include pages."""
        target_infos = targets_response.get("targetInfos", [])
        return [target for target in target_infos if target.get("type") == "page"]
    
    def on_event(self, method: str, handler: Callable[[Dict[str, Any]], None]) -> None:
        """Register an event handler for a specific method."""
        if method not in self.event_handlers:
            self.event_handlers[method] = []
        self.event_handlers[method].append(handler)
    
    def off_event(self, method: str, handler: Optional[Callable] = None) -> None:
        """Unregister event handler(s) for a specific method."""
        if method in self.event_handlers:
            if handler:
                try:
                    self.event_handlers[method].remove(handler)
                except ValueError:
                    pass
            else:
                self.event_handlers[method].clear()
    
    def set_connection_lost_callback(self, callback: Optional[Callable] = None) -> None:
        """Set callback to be called when connection is lost."""
        self.connection_lost_callback = callback
    
    async def _dispatch_event(self, method: str, params: Dict[str, Any]) -> None:
        """Dispatch an event to registered handlers."""
        if method in self.event_handlers:
            logger.debug(f"Dispatching {method} to {len(self.event_handlers[method])} handlers")
            for handler in self.event_handlers[method]:
                try:
                    # Call handler - can be sync or async
                    if asyncio.iscoroutinefunction(handler):
                        await handler(params)
                    else:
                        handler(params)
                except Exception as e:
                    logger.warning(f"Error in event handler for {method}: {e}")
    
    async def set_discover_targets(self, discover: bool = True) -> Dict[str, Any]:
        """Enable or disable target discovery events."""
        return await self.call("Target.setDiscoverTargets", {"discover": discover})
