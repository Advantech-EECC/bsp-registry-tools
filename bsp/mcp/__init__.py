"""
MCP (Model Context Protocol) server for bsp-registry-tools.

This package exposes the BSP workflow (preset discovery, builds, CVE scans,
HIL tests, build-failure triage and layer-pin maintenance) to AI agents via
an MCP server (``bsp-mcp`` entry point).

The ``mcp`` SDK is an optional dependency (``pip install bsp-registry-tools[mcp]``,
Python 3.10+).  This module deliberately does not import the SDK so that
``import bsp.mcp`` stays safe on Python 3.8 or without the extra installed;
only :mod:`bsp.mcp.server` requires it.
"""
