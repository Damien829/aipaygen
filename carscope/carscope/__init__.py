"""CarScope — an AI-assisted OBD-II diagnostic tool you own and control.

CarScope talks directly to a vehicle's OBD-II / CAN bus through a standard
adapter (ELM327 to start). It reads and clears diagnostic trouble codes,
streams and logs live sensor data, and — optionally — uses Claude to help
interpret what it finds.

It is a standalone tool: it does not touch, modify, or depend on any
commercial scan tool or its software. Use it only on vehicles you own or are
authorized to service.
"""

__version__ = "0.1.0"
