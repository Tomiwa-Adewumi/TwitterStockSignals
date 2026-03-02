import csv, json, sqlite3, sys

DB = sys.argv[1] if len(sys.argv) > 1 else "signals.db"

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row

# signals.csv
with open("signals.csv", "w", newline="") as f:
    rows = con.execute(
        "SELECT run_date, ticker, action, confidence, reasoning, source_tweet_urls "
        "FROM signals ORDER BY id DESC"
    ).fetchall()
    w = csv.writer(f)
    w.writerow(["date", "ticker", "action", "confidence", "reasoning", "tweet_urls"])
    for r in rows:
        urls = ", ".join(json.loads(r["source_tweet_urls"] or "[]"))
        w.writerow([r["run_date"], r["ticker"], r["action"], r["confidence"], r["reasoning"], urls])

# runs.csv
with open("runs.csv", "w", newline="") as f:
    rows = con.execute(
        "SELECT run_date, tweet_count, summary FROM runs ORDER BY id DESC"
    ).fetchall()
    w = csv.writer(f)
    w.writerow(["date", "tweet_count", "summary"])
    for r in rows:
        w.writerow([r["run_date"], r["tweet_count"], r["summary"]])

con.close()
