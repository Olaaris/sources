"""seedxp - decode per-skill experience tables from a local SEED installation.

The toolkit ships no game data.  Point it at a copy of the game you own and it
will inventory the install, unpack Unity bundles, recover XP tables and fit a
closed-form curve to each one.
"""

__version__ = "0.1.0"

__all__ = [
    "curves",
    "export",
    "inventory",
    "locate",
    "magic",
    "scan",
    "strings",
    "tables",
    "unityfs",
]
