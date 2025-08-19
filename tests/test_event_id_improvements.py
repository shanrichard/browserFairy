"""Test improved event_id generation for deduplication."""

import pytest
from browserfairy.utils.event_id import make_event_id, make_network_event_id


class TestEventIdImprovements:
    """Test the improved event_id generation strategies."""
    
    def test_make_event_id_basic(self):
        """Test basic event_id generation remains unchanged."""
        id1 = make_event_id("memory", "example.com", "2025-08-19T10:00:00", 100, 200)
        id2 = make_event_id("memory", "example.com", "2025-08-19T10:00:00", 100, 200)
        id3 = make_event_id("memory", "example.com", "2025-08-19T10:00:01", 100, 200)
        
        # Same inputs should generate same ID
        assert id1 == id2
        # Different timestamp should generate different ID
        assert id1 != id3
        # Should be 20 characters (10 bytes hex)
        assert len(id1) == 20
    
    def test_network_event_id_uniqueness(self):
        """Test that network events with different properties get different IDs."""
        # Same request, different response sizes should get different IDs
        id1 = make_network_event_id(
            "network_request_complete",
            "example.com",
            "2025-08-19T10:00:00",
            "req123",
            status=200,
            responseSize=1000,
            encodedDataLength=900
        )
        
        id2 = make_network_event_id(
            "network_request_complete",
            "example.com",
            "2025-08-19T10:00:00",
            "req123",
            status=200,
            responseSize=1001,  # Different size
            encodedDataLength=900
        )
        
        # Different response sizes should generate different IDs
        assert id1 != id2
    
    def test_network_event_id_with_sequence(self):
        """Test that sequence numbers create unique IDs."""
        id1 = make_network_event_id(
            "network_request_complete",
            "example.com",
            "2025-08-19T10:00:00",
            "req123",
            sequence=1,
            status=200
        )
        
        id2 = make_network_event_id(
            "network_request_complete",
            "example.com",
            "2025-08-19T10:00:00",
            "req123",
            sequence=2,  # Different sequence
            status=200
        )
        
        # Different sequences should generate different IDs
        assert id1 != id2
    
    def test_network_request_start_id(self):
        """Test network_request_start event ID generation."""
        id1 = make_network_event_id(
            "network_request_start",
            "example.com",
            "2025-08-19T10:00:00",
            "req123",
            method="GET",
            url="https://example.com/api"
        )
        
        id2 = make_network_event_id(
            "network_request_start",
            "example.com",
            "2025-08-19T10:00:00",
            "req123",
            method="POST",  # Different method
            url="https://example.com/api"
        )
        
        # Same request ID but different methods should still be unique
        # (though in practice this shouldn't happen)
        assert id1 != id2
    
    def test_network_request_failed_id(self):
        """Test network_request_failed event ID generation."""
        id1 = make_network_event_id(
            "network_request_failed",
            "example.com",
            "2025-08-19T10:00:00",
            "req123",
            url="https://example.com/api",
            errorText="net::ERR_ABORTED"
        )
        
        id2 = make_network_event_id(
            "network_request_failed",
            "example.com",
            "2025-08-19T10:00:00",
            "req123",
            url="https://example.com/api",
            errorText="net::ERR_CONNECTION_REFUSED"  # Different error
        )
        
        # Different error texts should generate different IDs
        assert id1 != id2
    
    def test_duplicate_complete_events_detection(self):
        """Test that truly duplicate complete events can be detected."""
        # Simulate two identical complete events (CDP duplicate)
        id1 = make_network_event_id(
            "network_request_complete",
            "example.com",
            "2025-08-19T10:00:00.123",
            "req123",
            status=200,
            responseSize=5000,
            encodedDataLength=4800
        )
        
        id2 = make_network_event_id(
            "network_request_complete",
            "example.com",
            "2025-08-19T10:00:00.123",  # Same timestamp
            "req123",  # Same request ID
            status=200,  # Same status
            responseSize=5000,  # Same size
            encodedDataLength=4800  # Same encoded size
        )
        
        # Truly identical events should have same ID (can be deduplicated)
        assert id1 == id2
    
    def test_legitimate_multiple_complete_events(self):
        """Test that legitimate multiple complete events get different IDs."""
        # Simulate chunked response with multiple complete events
        id1 = make_network_event_id(
            "network_request_complete",
            "example.com",
            "2025-08-19T10:00:00.123",
            "req123",
            status=200,
            responseSize=5000,
            encodedDataLength=4800
        )
        
        # Second complete with more data (chunked response)
        id2 = make_network_event_id(
            "network_request_complete",
            "example.com",
            "2025-08-19T10:00:00.456",  # Later timestamp
            "req123",
            status=200,
            responseSize=10000,  # More data received
            encodedDataLength=9600
        )
        
        # Different sizes indicate legitimate separate events
        assert id1 != id2


class TestGCEventIds:
    """Test GC event ID generation."""
    
    def test_heap_decrease_gc_id(self):
        """Test heap-based GC detection event IDs."""
        # These should be treated as same event (deduplicatable)
        id1 = make_event_id(
            "gc_event",
            "example.com",
            "2025-08-19T10:00:00",
            "heap_decrease_gc",
            14.5,  # size decrease
            100.0  # current size
        )
        
        id2 = make_event_id(
            "gc_event",
            "example.com",
            "2025-08-19T10:00:00",
            "heap_decrease_gc",
            14.5,
            100.0
        )
        
        assert id1 == id2
        
        # Different decrease should be different event
        id3 = make_event_id(
            "gc_event",
            "example.com",
            "2025-08-19T10:00:00",
            "heap_decrease_gc",
            20.0,  # Different decrease
            100.0
        )
        
        assert id1 != id3


class TestCorrelationEventIds:
    """Test correlation event ID generation."""
    
    def test_correlation_id_uniqueness(self):
        """Test correlation event IDs are unique per correlation."""
        id1 = make_event_id(
            "correlation",
            "example.com",
            "2025-08-19T10:00:00",
            "console_error",
            "console_error_to_network_failure",
            2  # number of correlations
        )
        
        id2 = make_event_id(
            "correlation",
            "example.com",
            "2025-08-19T10:00:00",
            "console_error",
            "console_error_to_memory_spike",  # Different correlation type
            2
        )
        
        # Different correlation types should generate different IDs
        assert id1 != id2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])