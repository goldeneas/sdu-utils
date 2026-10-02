"""Cheap-trip scanner for the Odense (DK) <-> Salerno (IT) corridor.

Modules
-------
ground      Curated ground-transfer model (Odense -> airports, Italy -> Salerno).
live_rail   Live rail/bus lookups (DSB/Rejseplanen, Transitous, Trainline).
ryanair     Live Ryanair public fare feed (route discovery + cheapest per day).
scan        CLI that joins fares with ground legs and ranks round-trips.
config      TOML configuration for the periodic watcher.
notify      ntfy (and stdout) notification channels.
state       Persistent deal memory so alerts only fire on changes.
watch       Periodic scanner: detects deals and pushes a notification.
"""

__version__ = "1.0.0"
