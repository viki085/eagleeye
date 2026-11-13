import pathlib
import sys

# Make shared test helpers (fake_redis) importable regardless of pytest import mode.
sys.path.insert(0, str(pathlib.Path(__file__).parent))
