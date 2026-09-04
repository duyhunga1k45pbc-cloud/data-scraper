"""Version-addressable extractor runtimes.

M11 freezes historical extractor implementations behind explicit version keys.
New extraction behavior must use a new module/version instead of changing the
implementation registered for an already-persisted extractor version.
"""
