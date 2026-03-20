"""
examples/autopilot_basic.py — Basic usage examples for the autopilot library

Run from the BrickellQuant root:
    python -m tools.autopilot.examples.basic
"""

from tools.autopilot import AutopilotClient, AutopilotDB


def main():
    # ── 1. Simple scrape ───────────────────────────────────────────────────────
    print("=" * 60)
    print("1. MARKETPLACE LISTING (featured, popular, leaderboard, teams)")
    print("=" * 60)

    # Default: rotates Chrome/Safari/Firefox TLS fingerprints per request
    client = AutopilotClient()
    listing = client.get_marketplace()
    print(listing.summary())

    # ── 2. Top performers ──────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("2. LEADERBOARD — TOP 5 BY 1-YEAR PERFORMANCE")
    print("=" * 60)
    for entry in listing.top_by_span("ONE_YEAR", n=5):
        print(
            f"  #{entry.rank}  {entry.title:<40s}"
            f"  {entry.span_performance_pct:+6.1f}%"
            f"  AUM=${entry.total_aum / 1e6:.1f}M"
        )

    # ── 3. Single portfolio with full daily history ────────────────────────────
    print("\n" + "=" * 60)
    print("3. SINGLE PORTFOLIO — Pelosi Tracker+ (full daily history)")
    print("=" * 60)

    p = client.get_portfolio(team_key=1, portfolio_key=8735)
    print(p.summary())
    print()

    all_time = p.get_span("ALL_TIME")
    print(f"  Daily series: {all_time.num_data_points} trading days")
    print(f"  From {all_time.start_date.date()} to {all_time.end_date.date()}")
    print(f"\n  Last 5 days:")
    for day in all_time.cumulative_performance[-5:]:
        print(
            f"    {day.date.date()}  "
            f"daily={day.daily_return_pct:+.3f}%  "
            f"cumul={day.cumulative_pct:+.2f}%"
        )

    # ── 4. Custom fingerprint + proxy ──────────────────────────────────────────
    print("\n" + "=" * 60)
    print("4. CUSTOM TLS FINGERPRINT (Safari 18.0)")
    print("=" * 60)

    client_safari = AutopilotClient(
        impersonate="safari180",   # Safari 18.0 TLS fingerprint
        # proxy="socks5://127.0.0.1:9050",  # Tor/SOCKS proxy (uncomment to use)
        delay=0.5,
    )
    entries = client_safari.get_sitemap()
    print(f"  Fetched sitemap as Safari 18.0: {len(entries)} portfolios")
    client_safari.close()

    # ── 5. Save to SQLite ──────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("5. SAVE TO SQLITE")
    print("=" * 60)

    db = AutopilotDB("autopilot.db")

    # Marketplace data (teams, leaderboard, featured, popular)
    client.sync_marketplace(db, verbose=True)

    # One specific portfolio with daily returns
    db.upsert_portfolio(p, include_daily=True)

    print(f"\n  {db}")

    # ── 6. Query the DB ────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("6. QUERY THE DB")
    print("=" * 60)

    print("\n  Top 5 by AUM:")
    for row in db.top_portfolios_by_aum(5):
        print(f"    {row['title']:<35s}  AUM=${row['total_aum'] / 1e6:.1f}M")

    print("\n  ONE_YEAR leaderboard from DB:")
    for row in db.get_leaderboard("ONE_YEAR"):
        pct = (row["span_performance"] or 0) * 100
        print(f"    #{row['rank']}  {row['title']:<35s}  {pct:+.1f}%")

    print("\n  Daily returns (Pelosi Tracker+ ALL_TIME, last 5):")
    for row in db.get_daily_returns(8735, "ALL_TIME")[-5:]:
        print(f"    {row['date'][:10]}  {row['cumulative'] * 100:+.2f}%")

    # ── 7. Full sync (all 36 portfolios) ───────────────────────────────────────
    # Uncomment to run a full sync (takes ~30-60 seconds with politeness delay)
    #
    # print("\n" + "=" * 60)
    # print("7. FULL SYNC — ALL 36 PORTFOLIOS")
    # print("=" * 60)
    # counts = client.sync_all(db, delay=0.5, verbose=True)
    # print(counts)

    client.close()
    print("\n✅ Done.")


if __name__ == "__main__":
    main()
