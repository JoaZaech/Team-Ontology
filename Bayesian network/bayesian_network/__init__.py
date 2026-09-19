"""Offline expert Bayesian advisory prototype; never a fraud classifier."""
from pathlib import Path
import sys

# Reuse the existing graph's timestamp, money and summary contracts.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent / "Knowledge_graph"))
VERSION = "bayesian-prototype-1"
