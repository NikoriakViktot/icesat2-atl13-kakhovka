"""ICESat-2 ATL13 -> EVRS water-surface elevation pipeline for the Kakhovka reservoir."""

from __future__ import annotations

__version__ = "0.1.0"

# Regime ("period") labels used throughout the pipeline. Split on the 2023-06-06
# Kakhovka dam breach.
REGIME_PRE_BREACH = "PRE_BREACH"
REGIME_BREACH_DRAWDOWN = "BREACH_DRAWDOWN"
REGIME_POST_BREACH = "POST_BREACH"
REGIMES = (REGIME_PRE_BREACH, REGIME_BREACH_DRAWDOWN, REGIME_POST_BREACH)
