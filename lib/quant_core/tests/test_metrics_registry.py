"""Tests for quant_core.metrics — Prometheus-compatible metrics registry."""

from __future__ import annotations

import re
import threading
from unittest.mock import MagicMock, patch

from quant_core.metrics import MetricsRegistry


class TestMetricsRegistryCounter:
    """Test counter metric behavior."""

    def test_inc_increments_counter_by_default_value(self):
        """Counter increments by 1 when no value provided."""
        metrics = MetricsRegistry("test-service")
        metrics.inc("requests_total")
        metrics.inc("requests_total")

        assert metrics._counters["requests_total"]['service="test-service"'] == 2.0

    def test_inc_increments_by_custom_value(self):
        """Counter increments by specified value."""
        metrics = MetricsRegistry("test-service")
        metrics.inc("bytes_transferred", 512.5)
        metrics.inc("bytes_transferred", 256.5)

        assert metrics._counters["bytes_transferred"]['service="test-service"'] == 769.0

    def test_multiple_increments_accumulate(self):
        """Multiple increments accumulate correctly."""
        metrics = MetricsRegistry("test-service")
        for _ in range(5):
            metrics.inc("counter_name", 10)

        assert metrics._counters["counter_name"]['service="test-service"'] == 50.0

    def test_counter_with_labels_creates_separate_series(self):
        """Different label sets create separate counter series."""
        metrics = MetricsRegistry("test-service")

        metrics.inc("requests", 1, labels={"endpoint": "/api/v1"})
        metrics.inc("requests", 1, labels={"endpoint": "/api/v2"})
        metrics.inc("requests", 5, labels={"endpoint": "/api/v1"})

        counter_values = metrics._counters["requests"]
        assert len(counter_values) == 2

        # Verify values by checking the keys
        keys = list(counter_values.keys())
        assert any('endpoint="/api/v1"' in k for k in keys)
        assert any('endpoint="/api/v2"' in k for k in keys)

        # Check accumulated values
        v1_key = next(k for k in keys if 'endpoint="/api/v1"' in k)
        v2_key = next(k for k in keys if 'endpoint="/api/v2"' in k)
        assert counter_values[v1_key] == 6.0
        assert counter_values[v2_key] == 1.0

    def test_counter_labels_includes_service_label(self):
        """Counter labels automatically include service label."""
        metrics = MetricsRegistry("alpha-engine")
        metrics.inc("trades", 1, labels={"symbol": "BTCUSD"})

        keys = list(metrics._counters["trades"].keys())
        assert len(keys) == 1
        key = keys[0]
        assert 'service="alpha-engine"' in key
        assert 'symbol="BTCUSD"' in key


class TestMetricsRegistryGauge:
    """Test gauge metric behavior."""

    def test_set_gauge_sets_absolute_value(self):
        """Gauge sets value to absolute amount, not accumulating."""
        metrics = MetricsRegistry("test-service")
        metrics.set_gauge("temperature", 72.5)
        assert metrics._gauges["temperature"]['service="test-service"'] == 72.5

    def test_set_gauge_overwrites_previous_value(self):
        """Gauge overwrites previous value instead of accumulating."""
        metrics = MetricsRegistry("test-service")
        metrics.set_gauge("memory_usage", 100.0)
        metrics.set_gauge("memory_usage", 150.0)
        metrics.set_gauge("memory_usage", 125.0)

        assert metrics._gauges["memory_usage"]['service="test-service"'] == 125.0

    def test_gauge_with_labels_creates_separate_series(self):
        """Different label sets create separate gauge series."""
        metrics = MetricsRegistry("test-service")

        metrics.set_gauge("cpu_usage", 45.2, labels={"core": "0"})
        metrics.set_gauge("cpu_usage", 62.1, labels={"core": "1"})

        gauge_values = metrics._gauges["cpu_usage"]
        assert len(gauge_values) == 2

        keys = list(gauge_values.keys())
        core0_key = next(k for k in keys if 'core="0"' in k)
        core1_key = next(k for k in keys if 'core="1"' in k)

        assert gauge_values[core0_key] == 45.2
        assert gauge_values[core1_key] == 62.1

    def test_gauge_labels_includes_service_label(self):
        """Gauge labels automatically include service label."""
        metrics = MetricsRegistry("data-service")
        metrics.set_gauge("db_connections", 23, labels={"pool": "main"})

        keys = list(metrics._gauges["db_connections"].keys())
        assert len(keys) == 1
        key = keys[0]
        assert 'service="data-service"' in key
        assert 'pool="main"' in key


class TestMetricsRegistryHistogram:
    """Test histogram metric behavior."""

    def test_observe_records_single_observation(self):
        """Histogram observe records a single observation."""
        metrics = MetricsRegistry("test-service")
        metrics.observe("response_time_ms", 42.5)

        observations = metrics._histograms["response_time_ms"]['service="test-service"']
        assert len(observations) == 1
        assert observations[0] == 42.5

    def test_observe_records_multiple_observations(self):
        """Histogram observe records multiple observations in order."""
        metrics = MetricsRegistry("test-service")
        values = [10.5, 20.3, 15.1, 30.0, 25.5]

        for val in values:
            metrics.observe("latency", val)

        observations = metrics._histograms["latency"]['service="test-service"']
        assert len(observations) == 5
        assert observations == values

    def test_histogram_with_labels_creates_separate_series(self):
        """Different label sets create separate histogram series."""
        metrics = MetricsRegistry("test-service")

        metrics.observe("request_duration", 100, labels={"method": "GET"})
        metrics.observe("request_duration", 200, labels={"method": "POST"})
        metrics.observe("request_duration", 120, labels={"method": "GET"})

        hist_values = metrics._histograms["request_duration"]
        assert len(hist_values) == 2

        keys = list(hist_values.keys())
        get_key = next(k for k in keys if 'method="GET"' in k)
        post_key = next(k for k in keys if 'method="POST"' in k)

        assert hist_values[get_key] == [100, 120]
        assert hist_values[post_key] == [200]

    def test_histogram_labels_includes_service_label(self):
        """Histogram labels automatically include service label."""
        metrics = MetricsRegistry("worker-service")
        metrics.observe("task_duration", 5.0, labels={"task_type": "process"})

        keys = list(metrics._histograms["task_duration"].keys())
        assert len(keys) == 1
        key = keys[0]
        assert 'service="worker-service"' in key
        assert 'task_type="process"' in key


class TestMetricsRegistryExport:
    """Test export to Prometheus text format."""

    def test_export_counter_with_type_annotation(self):
        """Exported counter includes TYPE annotation."""
        metrics = MetricsRegistry("test-service")
        metrics.inc("test_counter", 5)

        output = metrics.export()
        assert "# TYPE test_counter counter" in output
        assert 'test_counter{service="test-service"} 5.0' in output

    def test_export_gauge_with_type_annotation(self):
        """Exported gauge includes TYPE annotation."""
        metrics = MetricsRegistry("test-service")
        metrics.set_gauge("test_gauge", 42.5)

        output = metrics.export()
        assert "# TYPE test_gauge gauge" in output
        assert 'test_gauge{service="test-service"} 42.5' in output

    def test_export_histogram_as_summary(self):
        """Exported histogram appears as summary with _sum and _count suffixes."""
        metrics = MetricsRegistry("test-service")
        metrics.observe("test_histogram", 10.0)
        metrics.observe("test_histogram", 20.0)
        metrics.observe("test_histogram", 30.0)

        output = metrics.export()
        assert "# TYPE test_histogram summary" in output
        assert 'test_histogram_sum{service="test-service"} 60.0' in output
        assert 'test_histogram_count{service="test-service"} 3' in output

    def test_export_includes_service_label(self):
        """Export output includes service label from constructor."""
        metrics = MetricsRegistry("my-service")
        metrics.inc("counter")
        metrics.set_gauge("gauge", 1.0)
        metrics.observe("histogram", 1.0)

        output = metrics.export()
        assert 'service="my-service"' in output

    def test_export_multiple_metrics_coexist(self):
        """Export output includes multiple metric types together."""
        metrics = MetricsRegistry("mixed-service")
        metrics.inc("counter_metric", 10)
        metrics.set_gauge("gauge_metric", 25.0)
        metrics.observe("histogram_metric", 5.0)

        output = metrics.export()
        assert "# TYPE counter_metric counter" in output
        assert "# TYPE gauge_metric gauge" in output
        assert "# TYPE histogram_metric summary" in output
        assert "counter_metric" in output
        assert "gauge_metric" in output
        assert "histogram_metric" in output

    def test_export_multiple_label_sets(self):
        """Export output includes all label variations."""
        metrics = MetricsRegistry("test-service")
        metrics.inc("requests", 10, labels={"code": "200"})
        metrics.inc("requests", 5, labels={"code": "404"})

        output = metrics.export()
        assert 'requests{code="200",service="test-service"} 10.0' in output
        assert 'requests{code="404",service="test-service"} 5.0' in output

    def test_export_labels_sorted_alphabetically(self):
        """Exported labels are sorted alphabetically."""
        metrics = MetricsRegistry("test-service")
        metrics.inc("metric", 1, labels={"z": "last", "a": "first", "m": "middle"})

        output = metrics.export()
        # Labels should be sorted: a, m, service, z
        assert 'metric{a="first",m="middle",service="test-service",z="last"}' in output

    def test_export_valid_prometheus_format(self):
        """Export produces valid Prometheus text exposition format."""
        metrics = MetricsRegistry("test-service")
        metrics.inc("counter", 5)
        metrics.set_gauge("gauge", 10.5)
        metrics.observe("histogram", 2.5)

        output = metrics.export()

        # Should end with newline
        assert output.endswith("\n")

        # Should have TYPE lines for each metric
        assert re.search(r"^# TYPE counter counter$", output, re.MULTILINE)
        assert re.search(r"^# TYPE gauge gauge$", output, re.MULTILINE)
        assert re.search(r"^# TYPE histogram summary$", output, re.MULTILINE)

        # Should have metric lines with values
        assert re.search(r"^counter\{.*\} \d+\.?\d*$", output, re.MULTILINE)
        assert re.search(r"^gauge\{.*\} \d+\.?\d*$", output, re.MULTILINE)

    def test_export_with_float_values(self):
        """Export correctly handles float values."""
        metrics = MetricsRegistry("test-service")
        metrics.inc("counter", 1.5)
        metrics.set_gauge("gauge", 3.14159)

        output = metrics.export()
        assert "1.5" in output
        assert "3.14159" in output

    def test_export_empty_registry(self):
        """Empty registry exports empty string."""
        metrics = MetricsRegistry("test-service")
        output = metrics.export()

        assert output == ""

    def test_export_with_special_characters_in_labels(self):
        """Export handles label values with special characters."""
        metrics = MetricsRegistry("test-service")
        metrics.inc("requests", 1, labels={"path": "/api/v1/users/123"})

        output = metrics.export()
        assert 'path="/api/v1/users/123"' in output

    def test_export_histogram_count_is_integer(self):
        """Histogram count in export is an integer."""
        metrics = MetricsRegistry("test-service")
        metrics.observe("histogram", 1.5)
        metrics.observe("histogram", 2.5)
        metrics.observe("histogram", 3.0)

        output = metrics.export()
        # Count should be 3, not 3.0
        assert 'histogram_count{service="test-service"} 3' in output


class TestMetricsRegistryHTTPServer:
    """Test HTTP server functionality."""

    def test_start_http_server_creates_thread(self):
        """start_http_server starts a background thread."""
        metrics = MetricsRegistry("test-service")

        # Mock HTTPServer to avoid actually binding to a port
        with patch("quant_core.metrics.HTTPServer") as mock_http_server:
            mock_instance = MagicMock()
            mock_http_server.return_value = mock_instance

            metrics.start_http_server(port=9090)

            # Verify HTTPServer was instantiated with correct address and port
            mock_http_server.assert_called_once()
            call_args = mock_http_server.call_args
            assert call_args[0][0] == ("0.0.0.0", 9090)

            # Verify serve_forever was started
            mock_instance.serve_forever.assert_called_once()

    def test_start_http_server_thread_is_daemon(self):
        """HTTP server thread is a daemon thread."""
        metrics = MetricsRegistry("test-service")

        with patch("quant_core.metrics.HTTPServer") as mock_http_server:
            mock_instance = MagicMock()
            mock_http_server.return_value = mock_instance

            with patch("quant_core.metrics.threading.Thread") as mock_thread:
                mock_thread_instance = MagicMock()
                mock_thread.return_value = mock_thread_instance

                metrics.start_http_server(port=8888)

                # Verify Thread was created as daemon
                mock_thread.assert_called_once()
                call_kwargs = mock_thread.call_args[1]
                assert call_kwargs.get("daemon") is True

                # Verify start was called
                mock_thread_instance.start.assert_called_once()

    def test_start_http_server_with_custom_port(self):
        """start_http_server accepts custom port."""
        metrics = MetricsRegistry("test-service")

        with patch("quant_core.metrics.HTTPServer") as mock_http_server:
            mock_instance = MagicMock()
            mock_http_server.return_value = mock_instance

            metrics.start_http_server(port=12345)

            call_args = mock_http_server.call_args
            assert call_args[0][0] == ("0.0.0.0", 12345)

    def test_start_http_server_default_port(self):
        """start_http_server uses port 9090 by default."""
        metrics = MetricsRegistry("test-service")

        with patch("quant_core.metrics.HTTPServer") as mock_http_server:
            mock_instance = MagicMock()
            mock_http_server.return_value = mock_instance

            metrics.start_http_server()

            call_args = mock_http_server.call_args
            assert call_args[0][0] == ("0.0.0.0", 9090)


class TestMetricsRegistryThreadSafety:
    """Test thread safety of metrics operations."""

    def test_concurrent_counter_increments(self):
        """Multiple threads can safely increment counters."""
        metrics = MetricsRegistry("test-service")

        def increment_counter():
            for _ in range(100):
                metrics.inc("counter", 1)

        threads = [threading.Thread(target=increment_counter) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        counter_value = metrics._counters["counter"]['service="test-service"']
        assert counter_value == 500.0

    def test_concurrent_gauge_updates(self):
        """Multiple threads can safely update gauges."""
        metrics = MetricsRegistry("test-service")
        results = []

        def update_gauge(value):
            for _ in range(50):
                metrics.set_gauge("gauge", value)
            results.append(value)

        threads = [threading.Thread(target=update_gauge, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Gauge should have final value from one of the threads
        gauge_value = metrics._gauges["gauge"]['service="test-service"']
        assert gauge_value in results

    def test_concurrent_histogram_observations(self):
        """Multiple threads can safely observe values."""
        metrics = MetricsRegistry("test-service")

        def observe_values(start_val):
            for i in range(50):
                metrics.observe("histogram", start_val + i)

        threads = [threading.Thread(target=observe_values, args=(i * 100,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        observations = metrics._histograms["histogram"]['service="test-service"']
        assert len(observations) == 250

    def test_export_during_updates(self):
        """Export can safely run while metrics are being updated."""
        metrics = MetricsRegistry("test-service")

        def update_metrics():
            for i in range(100):
                metrics.inc("counter", 1)
                metrics.set_gauge("gauge", i)
                metrics.observe("histogram", i)

        def export_metrics():
            exports = []
            for _ in range(50):
                exports.append(metrics.export())
            return exports

        thread1 = threading.Thread(target=update_metrics)
        thread2 = threading.Thread(target=export_metrics)

        thread1.start()
        thread2.start()

        thread1.join()
        thread2.join()

        # Verify final export is valid
        final_export = metrics.export()
        assert "# TYPE counter counter" in final_export
        assert "# TYPE gauge gauge" in final_export
        assert "# TYPE histogram summary" in final_export


class TestMetricsRegistryLabelKey:
    """Test label key generation."""

    def test_label_key_sorts_alphabetically(self):
        """Label keys are sorted alphabetically."""
        key1 = MetricsRegistry._label_key({"z": "val", "a": "val", "m": "val"})
        assert key1 == 'a="val",m="val",z="val"'

    def test_label_key_escapes_quotes(self):
        """Label values with quotes are handled correctly."""
        # The implementation uses f-strings, so quotes in values should be escaped
        key = MetricsRegistry._label_key({"key": 'value"with"quotes'})
        assert 'value"with"quotes' in key

    def test_label_key_empty_dict(self):
        """Label key for empty dict is empty string."""
        key = MetricsRegistry._label_key({})
        assert key == ""

    def test_label_key_single_label(self):
        """Label key for single label produces correct format."""
        key = MetricsRegistry._label_key({"service": "test"})
        assert key == 'service="test"'


class TestMetricsRegistryIntegration:
    """Integration tests combining multiple features."""

    def test_complete_workflow(self):
        """Complete workflow with all metric types."""
        metrics = MetricsRegistry("integration-test")

        # Add various metrics
        metrics.inc("api_calls", 100, labels={"endpoint": "/users"})
        metrics.inc("api_calls", 50, labels={"endpoint": "/posts"})
        metrics.set_gauge("active_connections", 42)
        metrics.observe("response_time_ms", 10.5, labels={"endpoint": "/users"})
        metrics.observe("response_time_ms", 20.3, labels={"endpoint": "/users"})

        output = metrics.export()

        # Verify all metrics are present
        assert "# TYPE api_calls counter" in output
        assert "# TYPE active_connections gauge" in output
        assert "# TYPE response_time_ms summary" in output

        # Verify values
        assert 'api_calls{endpoint="/users",service="integration-test"} 100.0' in output
        assert 'api_calls{endpoint="/posts",service="integration-test"} 50.0' in output
        assert 'active_connections{service="integration-test"} 42' in output
        assert 'response_time_ms_sum{endpoint="/users",service="integration-test"} 30.8' in output
        assert 'response_time_ms_count{endpoint="/users",service="integration-test"} 2' in output

    def test_real_world_metrics_scenario(self):
        """Simulates a real-world metrics collection scenario."""
        metrics = MetricsRegistry("trading-engine")

        # Simulate signal generation
        for symbol in ["BTCUSD", "ETHUSDT"]:
            metrics.inc("signals_emitted", labels={"symbol": symbol})
            metrics.inc("signals_emitted", labels={"symbol": symbol})

        # Simulate order execution
        metrics.observe("order_latency_ms", 12.5, labels={"action": "buy"})
        metrics.observe("order_latency_ms", 15.3, labels={"action": "sell"})

        # Simulate position tracking
        metrics.set_gauge("active_positions", 2)

        output = metrics.export()

        # Verify realistic metrics are present
        assert "signals_emitted" in output
        assert "order_latency_ms" in output
        assert "active_positions" in output
        assert "BTCUSD" in output
        assert "ETHUSDT" in output
