"""
Tests for http_client.py: latency stats, request kind, analytics.
Run with: python -m pytest tests/test_http_client.py -v
"""
import sys
import os
import time
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from yandex_maps_parser.http_client import (
    _record_latency,
    _get_latency_stats,
    _request_kind,
    _stats_count_request,
    get_analytics,
    get_stats,
    reset_stats,
)


class TestRequestKind:
    def test_search_maps(self):
        assert _request_kind("https://search-maps.yandex.ru/v1/?text=test") == "search"

    def test_geocode(self):
        assert _request_kind("https://geocode-maps.yandex.ru/1.x/?geocode=test") == "geocode"

    def test_detail_page(self):
        assert _request_kind("https://yandex.ru/maps/org/12345") == "detail"

    def test_other(self):
        assert _request_kind("https://example.com/something") == "other"

    def test_aggregator(self):
        assert _request_kind("https://taplink.cc/salon") == "other"


class TestLatencyStats:
    def setup_method(self):
        """Reset latency window before each test."""
        from yandex_maps_parser import http_client
        http_client._latency_window.clear()
        http_client._latency_version = 0
        http_client._latency_cache_version = 0

    def test_empty_window(self):
        """Empty window should return zeros."""
        avg, p50, p95 = _get_latency_stats()
        assert avg == 0.0
        assert p50 == 0.0
        assert p95 == 0.0

    def test_single_value(self):
        """Single latency should be avg=p50=p95=value."""
        _record_latency(1.5)
        avg, p50, p95 = _get_latency_stats()
        assert abs(avg - 1.5) < 0.01
        assert abs(p50 - 1.5) < 0.01
        assert abs(p95 - 1.5) < 0.01

    def test_multiple_values(self):
        """Multiple latencies should compute correct stats."""
        latencies = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
        for lat in latencies:
            _record_latency(lat)
        avg, p50, p95 = _get_latency_stats()
        assert abs(avg - 0.55) < 0.01
        assert p50 > 0.0  # median should be middle value
        assert p95 >= p50  # p95 should be >= p50

    def test_caching_works(self):
        """Second call should return cached values if window unchanged."""
        _record_latency(2.0)
        avg1, p50_1, p95_1 = _get_latency_stats()
        avg2, p50_2, p95_2 = _get_latency_stats()
        assert avg1 == avg2
        assert p50_1 == p50_2
        assert p95_1 == p95_2

    def test_cache_invalidation(self):
        """Adding a new latency should invalidate cache."""
        _record_latency(1.0)
        avg1, _, _ = _get_latency_stats()
        _record_latency(100.0)
        avg2, _, _ = _get_latency_stats()
        assert avg2 > avg1  # new value should change average

    def test_window_overflow(self):
        """Window should cap at 200 entries."""
        for i in range(250):
            _record_latency(float(i))
        avg, _, _ = _get_latency_stats()
        # Should only contain last 200 values (50.0 to 249.0)
        assert avg > 50.0
        from yandex_maps_parser import http_client
        assert len(http_client._latency_window) == 200


class TestStatsCounting:
    def setup_method(self):
        reset_stats()

    def test_request_counting(self):
        """Requests should be counted by kind."""
        _stats_count_request("https://search-maps.yandex.ru/v1/")
        _stats_count_request("https://search-maps.yandex.ru/v1/")
        _stats_count_request("https://yandex.ru/maps/org/123")
        stats = get_stats()
        assert stats["requests"] == 3
        assert stats["by_kind"]["search"] == 2
        assert stats["by_kind"]["detail"] == 1

    def test_analytics_rps(self):
        """Analytics should report RPS target."""
        reset_stats()
        analytics = get_analytics()
        assert "rps_target" in analytics
        assert "rps_actual" in analytics
        assert analytics["rps_target"] > 0


class TestMemoryStats:
    def test_memory_in_stats(self):
        """Stats should include memory info if tracemalloc available."""
        stats = get_stats()
        assert "memory_mb" in stats
        assert "memory_peak_mb" in stats
