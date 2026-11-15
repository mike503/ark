"""Tool and archive schema versions — single source of truth."""

# Package / tool version (extractor CLI + viewer). Bump on user-visible behavior changes.
__version__ = "0.1.0"

# Integer schema version for archive.sqlite layout (tables/columns/indexes).
# Bump when migrations change what readers should expect; keep migrations additive.
SCHEMA_VERSION = 1
