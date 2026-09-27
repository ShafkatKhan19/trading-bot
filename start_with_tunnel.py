# ============================================================
#  start_with_tunnel.py
#  Starts the Flask dashboard AND creates a public HTTPS tunnel
#  so you can access the dashboard from any device / browser.
#
#  Usage:
#    python start_with_tunnel.py
#
#  Free ngrok account gives you a stable subdomain.
#  Sign up at https://ngrok.com, then set your auth token:
#    python -c "from pyngrok import ngrok; ngrok.set_auth_token('YOUR_TOKEN')"
# ============================================================

import threading
import time
import webbrowser
from pyngrok import ngrok
import web_dashboard

def run_flask():
    web_dashboard.app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)

if __name__ == "__main__":
    # Start Flask in a background thread
    t = threading.Thread(target=run_flask, daemon=True)
    t.start()
    time.sleep(2)

    # Open ngrok tunnel on port 5000
    tunnel = ngrok.connect(5000, "http")
    public_url = tunnel.public_url

    print("\n" + "="*60)
    print("  TRADING BOT DASHBOARD — PUBLIC ACCESS")
    print("="*60)
    print(f"  Local:  http://localhost:5000")
    print(f"  Public: {public_url}")
    print("="*60)
    print("\n  Share the Public URL to monitor from any device.")
    print("  Press Ctrl+C to stop.\n")

    # Open local browser
    webbrowser.open("http://localhost:5000")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down tunnel...")
        ngrok.disconnect(public_url)
        ngrok.kill()
