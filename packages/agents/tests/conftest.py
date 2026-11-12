import pathlib
import sys

# Make `fakes` importable regardless of pytest import mode.
sys.path.insert(0, str(pathlib.Path(__file__).parent))
