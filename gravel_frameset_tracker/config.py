"""
Configuration for the gravel frameset tracker module.
Part of the Preis-Tracker repo.
"""

# --- Notification thresholds (EUR) ---
THRESHOLD_ALUMINIUM_EUR = 350
THRESHOLD_CARBON_EUR = 450

# --- Scope filters ---
# Set to None to track all sizes instead of a single one.
FRAME_SIZE_FILTER = "56"

# New listings only. Set True to also allow used-marketplace adapters
# (none are implemented yet — this only matters if you add one, e.g.
# bikemarkt.mtb-news.de or Kleinanzeigen).
INCLUDE_USED_LISTINGS = False

# --- Model-discovery criteria ---
MIN_TIRE_CLEARANCE_MM = 32
MAX_TIRE_CLEARANCE_MM = 45

# Only these brands are eligible when discovering new models.
# Extend as needed — kept short deliberately ("well-known brands only").
KNOWN_BRANDS = [
    "Cervélo", "Cervelo", "Canyon", "Merida", "Orbea", "Trek", "Cannondale",
    "Focus", "Ridley", "3T", "Specialized", "Giant", "Scott", "BMC", "Wilier",
    "Look", "Pinarello", "Bianchi", "Cube",
]

# Curated sources checked each run for new-model mentions.
DISCOVERY_SOURCES = [
    "https://www.canyon.com/en-de/gravel/all-road/grail/",
    "https://www.cervelo.com/en/gravel",
    "https://www.merida-bikes.com/en/bikes/gravel",
    "https://www.bikeradar.com/advice/buyers-guides/best-gravel-bikes",
    "https://www.cyclist.co.uk/buying-guides/best-gravel-race-bikes",
]

# If True, discover_models.py merges candidates into models.json automatically.
# If False (default), candidates are written to candidates.json for manual review.
AUTO_APPROVE = False

# Paths
MODELS_FILE = "models.json"
CANDIDATES_FILE = "candidates.json"
