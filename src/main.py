from trader import run_cycle
from rain_trader import run_rain_cycle
from settler import settle_trades

if __name__ == "__main__":
    # Settle any previously placed trades that have resolved.
    # Run this FIRST so settlements always complete even if the trading phases
    # later time out (e.g., GitHub Actions runner cap).
    print("Settling resolved trades...")
    settle_trades()

    run_cycle()
    run_rain_cycle()
