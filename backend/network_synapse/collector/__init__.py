"""Collector block — backend access to the SuzieQ telemetry stack.

The Collector (NAF reference architecture) gathers operational state from the
containerlab fabric (Issue #169). This package is the backend's Python entry
point to that data: a REST client for the SuzieQ API plus drift scoring and
a Prometheus exporter built on top of it (Issue #74).
"""
