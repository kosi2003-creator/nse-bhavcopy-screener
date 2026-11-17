import os
import time
from io import StringIO
from datetime import datetime, timezone, timedelta
import pandas as pd
from curl_cffi import requests as cffi_requests
import yfinance as yf

# --- CONFIGURATION ---
MIN_MCAP_CR = 1000
MAX_MCAP_CR = 30000
OUTPUT_DIR = "reports"
MCAP_CACHE_FILE = "mcap_master_cache.csv"
CACHE_MAX_AGE_DAYS = 7

os.makedirs(OUTPUT_DIR, exist_ok=True)

def get_ist_now():
    return datetime.now(timezone(timedelta(hours=5, minutes=30)))

def fetch_nse_bhavcopy():
    date_str = get_ist_now().strftime("%d%m%Y")
    url = f"https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{date_str}.csv"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer": "https://www.nseindia.com/all-reports"
    }
    
    session = cffi_requests.Session(impersonate="chrome")
    session.get("https://www.nseindia.com", headers=headers, timeout=15)
    time.sleep(1)
    
    resp = session.get(url, headers=headers, timeout=20)
    if resp.status_code != 200:
        print(f"Bhavcopy not available for {date_str} (HTTP {resp.status_code}). Likely a market holiday.")
        return None, date_str
    
    df = pd.read_csv(StringIO(resp.text))
    df.columns = df.columns.str.strip()
    df['SYMBOL'] = df['SYMBOL'].str.strip()
    df['SERIES'] = df['SERIES'].str.strip()
    
    df = df[df['SERIES'] == 'EQ'].copy()
    for col in ['OPEN_PRICE', 'HIGH_PRICE', 'LOW_PRICE', 'CLOSE_PRICE', 'TTL_TRD_QNTY', 'DELIV_QTY', 'DELIV_PER']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
    return df, date_str

def get_market_caps(symbols):
    if os.path.exists(MCAP_CACHE_FILE):
        file_age = (time.time() - os.path.getmtime(MCAP_CACHE_FILE)) / 86400
        if file_age < CACHE_MAX_AGE_DAYS:
            print("Using cached Market Cap master...")
            return pd.read_csv(MCAP_CACHE_FILE)

    print("Refreshing Market Cap master from Yahoo Finance...")
    records = []
    ns_symbols = [f"{s}.NS" for s in symbols]
    for i in range(0, len(ns_symbols), 100):
        batch = ns_symbols[i:i+100]
        tickers = yf.Tickers(" ".join(batch))
        for sym, ns_sym in zip(symbols[i:i+100], batch):
            try:
                mcap = tickers.tickers[ns_sym].fast_info.get("marketCap")
                if mcap:
                    records.append({"SYMBOL": sym, "MCAP_CR": round(mcap / 1e7, 2)})
            except Exception:
                continue
        time.sleep(0.5)

    mcap_df = pd.DataFrame(records)
    mcap_df.to_csv(MCAP_CACHE_FILE, index=False)
    return mcap_df

def run_pipeline():
    bhav_df, date_str = fetch_nse_bhavcopy()
    if bhav_df is None:
        return
    
    mcap_df = get_market_caps(bhav_df['SYMBOL'].tolist())
    merged = pd.merge(bhav_df, mcap_df, on="SYMBOL", how="inner")
    
    universe = merged[
        (merged['MCAP_CR'] >= MIN_MCAP_CR) & 
        (merged['MCAP_CR'] <= MAX_MCAP_CR)
    ].sort_values(by="DELIV_PER", ascending=False)
    
    out_file = os.path.join(OUTPUT_DIR, f"bhavcopy_1000_30000cr_{date_str}.csv")
    universe.to_csv(out_file, index=False)
    print(f"Success: Saved {len(universe)} stocks to {out_file}")

if __name__ == "__main__":
    run_pipeline()
