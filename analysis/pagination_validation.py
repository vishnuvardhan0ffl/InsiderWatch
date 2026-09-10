

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

print("Project root:", PROJECT_ROOT)

from collectors.polymarket import (
    TradeQuery,
    collect_trades,
    save_trade_collection,
)
# ===== Code cell 3 =====
MARKET_ID = "0xd1e4e03a0129aad7b23e835bfb5c0166d7342fb98e91aa7dd0f3e6cb423d9c21"

print(MARKET_ID)

# ===== Code cell 4 =====
from datetime import datetime, timezone

start = int(
    datetime(
        2025,
        1,
        1,
        tzinfo=timezone.utc
    ).timestamp()
)

end = int(
    datetime(
        2026,
        4,
        28,
        10,
        59,
        59,
        tzinfo=timezone.utc
    ).timestamp()
)

print(start)
print(end)

# ===== Code cell 5 =====
query = TradeQuery(
    market=MARKET_ID,
    start=start,
    end=end,

    # Important:
    # explicitly include maker + taker records
    taker_only=False
)

# ===== Code cell 6 =====
trades, metadata = collect_trades(
    query,
    window_s=7 * 86400
)

# ===== Code cell 7 =====
print(
    "Total trades:",
    len(trades)
)

# ===== Code cell 8 =====
import pandas as pd

df = pd.DataFrame(
    trades
)

print(
    "Rows:",
    len(df)
)

# ===== Code cell 9 =====
duplicate_rows = (
    df.astype(str)
      .duplicated()
      .sum()
)

print(
    "Duplicate rows:",
    duplicate_rows
)

# ===== Code cell 10 =====
metadata[
    "duplicates_removed"
]

# ===== Code cell 11 =====
metadata["takerOnly"]

# ===== Code cell 12 =====
print(
    "API requests:",
    metadata["request_count"]
)

print(
    "Window splits:",
    metadata["window_split_count"]
)

print(
    "Raw records:",
    metadata["raw_records_received"]
)

print(
    "Final records:",
    metadata["final_trade_count"]
)

print(
    "Duplicates removed:",
    metadata["duplicates_removed"]
)

# ===== Code cell 13 =====
from pathlib import Path

PROJECT_ROOT = Path.cwd().parent

output_dir = PROJECT_ROOT / "data" / "raw" / "polymarket"

print("Project root:", PROJECT_ROOT)
print("Output folder:", output_dir)

# ===== Code cell 14 =====
save_trade_collection(
    trades,
    metadata,
    output_dir=output_dir,
    name="maduro_trades"
)
