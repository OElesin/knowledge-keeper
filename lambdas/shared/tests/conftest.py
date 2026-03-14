"""Configure sys.path so tests can import shared modules as 'shared.xxx'."""
import sys
from pathlib import Path

# Add lambdas/ to sys.path so `from shared.models import ...` works
_lambdas_dir = str(Path(__file__).resolve().parent.parent.parent)
if _lambdas_dir not in sys.path:
    sys.path.insert(0, _lambdas_dir)
