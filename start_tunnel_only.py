# ============================================================
#  start_tunnel_only.py
#  Opens a public ngrok HTTPS tunnel to the dashboard that's
#  already running on localhost:5000 (does NOT start a second
#  Flask instance — avoids port conflicts with web_dashboard.py).
#
#  Usage:
#    python start_tunnel_only.py
#
#  Free tier: URL is random and changes every restart of THIS
#  script (the Flask dashboard itself can keep running).
# ============================================================

import time
from pyngrok import ngrok

if __name__ == "__main__":
    tunnel = ngrok.connect(5000, "http")
    public_url = tunnel.public_url

    print("\n" + "=" * 60)
    print("  TRADING BOT DASHBOARD — PUBLIC ACCESS")
    print("=" * 60)
    print(f"  Local:  http://localhost:5000")
    print(f"  Public: {public_url}")
    print("=" * 60)
    print("\n  Share the Public URL to monitor from any device.")
    print("  Press Ctrl+C to stop.\n")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down tunnel...")
        ngrok.disconnect(public_url)
        ngrok.kill()
