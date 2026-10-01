"""Central configuration: paths, dataset subset, dates, and all assumptions."""
from pathlib import Path

# --- Paths (relative to project root) ---
ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
RAW_SUBSET_DIR = RAW_DIR / "m5_subset"  # small immutable raw extract (FOODS_3 x 3 stores)
RAW_TMP_DIR = RAW_DIR / "_tmp"          # scratch area for the downloaded zip, deleted after extraction
PROCESSED_DIR = ROOT / "data" / "processed"
OUTPUT_DIR = ROOT / "outputs"
POWERBI_DIR = OUTPUT_DIR / "powerbi"
FIGURES_DIR = ROOT / "reports" / "figures"
SALES_CLEAN_PATH = PROCESSED_DIR / "sales_clean.csv"

# --- Data source ---
M5_URL = "https://github.com/Nixtla/m5-forecasts/raw/main/datasets/m5.zip"  # public Nixtla mirror of M5

# --- Subset ---
STORES = ["CA_1", "TX_1", "WI_1"]  # one store per state
DEPT = "FOODS_3"                   # highest-volume, fast-moving department
N_ITEMS = 50                       # up to 50 eligible items by units, ranked on data up to the first backtest origin (41 qualify)
HISTORY_START = "2014-05-22"       # start of the 732-day history window (inclusive, 2016 is a leap year)
AS_OF_DATE = "2016-05-22"          # last day of history (M5 d_1941)
SEED = 42                          # fixed seed (synthetic inventory snapshot only)

# --- Forecasting / backtest ---
HORIZON = 28                       # forecast horizon in days
BACKTEST_ORIGINS = ["2016-02-28", "2016-03-27", "2016-04-24"]  # rolling-origin fold train ends
SELECTION_TOLERANCE_PP = 1.0       # pick the simplest model whose overall WAPE is within this many pct points of the best

# --- Item eligibility (fast movers only) ---
ELIGIBILITY_DAYS = 365             # window length ending at the first backtest origin
MAX_ZERO_SHARE = 0.20              # item must have zero-sales share <= this in EVERY store within the window
LAUNCH_CHECK_DAYS = 28             # item must sell >= 1 unit within the first 28 days of history in EVERY store (listed from the start)

# --- Cleaning ---
STOCKOUT_RUN_DAYS = 7              # zero-sales runs >= 7 days are flagged as likely stockouts
OUTLIER_IQR_MULT = 3.0             # outlier day = units > Q3 + 3*IQR within its series (flagged, never removed)

# --- Inventory assumptions (every value below is an ASSUMPTION, not derived from the dataset) ---
SERVICE_LEVEL = 0.95                                 # ASSUMPTION: target cycle service level; Z via scipy.stats.norm.ppf
LEAD_TIME_DAYS = {"CA_1": 5, "TX_1": 7, "WI_1": 10}  # ASSUMPTION: illustrative supplier lead time per store (days)
ORDER_CYCLE_DAYS = 7                                 # ASSUMPTION: T, days of cover ordered beyond the lead time
CASE_PACK = 6                                        # ASSUMPTION: illustrative units per case (M5 has no pack sizes); 1 disables
SYNTHETIC_DAYS_OF_SUPPLY = (0, 45)                   # ASSUMPTION: synthetic on-hand = U(0,45) days x mean forecast (M5 has no inventory); 45 > OVERSTOCK_DAYS so all flags can occur
OVERSTOCK_DAYS = 30                                  # ASSUMPTION: days_of_cover above this is flagged OVERSTOCK
RUN_DATE = "2016-05-23"                              # ASSUMPTION: list runs the morning after the last observed sales day
OPEN_ORDERS = 0                                      # ASSUMPTION: no open orders, so inventory position = on-hand
