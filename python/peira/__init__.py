"""peira: benchmarking decision models under attack."""

# NB: the repo ALWAYS carries 0.0.0. The signed git release tag (vX.Y.Z)
# is the single source of truth; scripts/release/stamp.py stamps the tag
# version into build trees at publish time. See docs/Release.md.
__version__ = "0.0.0"

from peira.adapters.base import AdapterOutput, BaseAdapter
from peira.schema import AttackedVariant, BenignVariant, Case

__all__ = [
    "AdapterOutput",
    "AttackedVariant",
    "BaseAdapter",
    "BenignVariant",
    "Case",
    "__version__",
]
