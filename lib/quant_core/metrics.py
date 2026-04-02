"""Prometheus metrics for all services.

Each service initializes a MetricsRegistry and exposes metrics on a /metrics
endpoint. Prometheus scrapes these endpoints to collect system-wide data.

Usage:
    from quant_core.metrics import MetricsRegistry

    metrics = MetricsRegistry("alpha-engine")
    metrics.inc("signals_emitted", labels={"symbol": "BTCUSD"})
    metrics.observe("signal_latency_ms", 12.5)
    metrics.start_http_server(port=9090)
"""

from __future__ import annotations

import logging
import threading
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, HTTPServer

logger = logging.getLogger(__name__)


class MetricsRegistry:
    """Simple Prometheus-compatible metrics registry.

    Uses a lightweight custom implementation to avoid adding prometheus_client
    as a hard dependency. Exports in Prometheus text exposition format.
    """

    def __init__(self, service_name: str) -> None:
        self._service = service_name
        self._lock = threading.Lock()

        # counter_name -> {label_hash: value}
        self._counters: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        self._counter_labels: dict[str, dict[str, dict[str, str]]] = defaultdict(dict)

        # gauge_name -> {label_hash: value}
        self._gauges: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        self._gauge_labels: dict[str, dict[str, dict[str, str]]] = defaultdict(dict)

        # histogram_name -> {label_hash: [observations]}
        self._histograms: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
        self._hist_labels: dict[str, dict[str, dict[str, str]]] = defaultdict(dict)

        # Common labels added to everything
        self._common_labels = {"service": service_name}

    @staticmethod
    def _label_key(labels: dict[str, str]) -> str:
        return ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()))

    def inc(self, name: str, value: float = 1.0, labels: dict[str, str] | None = None) -> None:
        """Increment a counter."""
        all_labels = {**self._common_labels, **(labels or {})}
        key = self._label_key(all_labels)
        with self._lock:
            self._counters[name][key] += value
            self._counter_labels[name][key] = all_labels

    def set_gauge(self, name: str, value: float, labels: dict[str, str] | None = None) -> None:
        """Set a gauge value."""
        all_labels = {**self._common_labels, **(labels or {})}
        key = self._label_key(all_labels)
        with self._lock:
            self._gauges[name][key] = value
            self._gauge_labels[name][key] = all_labels

    def observe(self, name: str, value: float, labels: dict[str, str] | None = None) -> None:
        """Record a histogram observation."""
        all_labels = {**self._common_labels, **(labels or {})}
        key = self._label_key(all_labels)
        with self._lock:
            self._histograms[name][key].append(value)
            self._hist_labels[name][key] = all_labels

    def export(self) -> str:
        """Export all metrics in Prometheus text exposition format."""
        lines = []

        with self._lock:
            # Counters
            for name, values in self._counters.items():
                lines.append(f"# TYPE {name} counter")
                for key, val in values.items():
                    labels_str = self._counter_labels[name].get(key, {})
                    label_part = self._label_key(labels_str)
                    lines.append(f"{name}{{{label_part}}} {val}")

            # Gauges
            for name, values in self._gauges.items():
                lines.append(f"# TYPE {name} gauge")
                for key, val in values.items():
                    labels_str = self._gauge_labels[name].get(key, {})
                    label_part = self._label_key(labels_str)
                    lines.append(f"{name}{{{label_part}}} {val}")

            # Histograms (simplified: export sum and count)
            for name, values in self._histograms.items():
                lines.append(f"# TYPE {name} summary")
                for key, observations in values.items():
                    labels_str = self._hist_labels[name].get(key, {})
                    label_part = self._label_key(labels_str)
                    total = sum(observations)
                    count = len(observations)
                    lines.append(f"{name}_sum{{{label_part}}} {total}")
                    lines.append(f"{name}_count{{{label_part}}} {count}")

        lines.append("")
        return "\n".join(lines)

    def start_http_server(self, port: int = 9090) -> None:
        """Start a background HTTP server exposing /metrics."""
        registry = self

        class MetricsHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == "/metrics":
                    body = registry.export().encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/plain; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                elif self.path == "/health":
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(b'{"status":"ok"}')
                else:
                    self.send_response(404)
                    self.end_headers()

            def log_message(self, format, *args):
                pass  # Suppress access logs

        server = HTTPServer(("0.0.0.0", port), MetricsHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        logger.info("Metrics server started on http://0.0.0.0:%d/metrics", port)
