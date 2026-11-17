import sys
from pathlib import Path

# black_week/*.py import each other as top-level modules (like gravel_frameset_tracker)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
