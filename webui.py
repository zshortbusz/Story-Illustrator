"""
webui.py: Top-level launcher for the Automated Story Illustrator (ASI) WebUI.
Usage:
    python webui.py
    python webui.py --port 5000 --host 127.0.0.1
"""

import sys
import argparse
from pipeline.web_server import create_app

def main():
    parser = argparse.ArgumentParser(description="Automated Story Illustrator (ASI) WebUI")
    parser.add_argument("--host", default="127.0.0.1", help="Host address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=5000, help="Port (default: 5000)")
    args = parser.parse_args()

    app = create_app()

    print("\n" + "=" * 76)
    print("      AUTOMATED STORY ILLUSTRATOR (ASI) - INTERACTIVE WEB DASHBOARD")
    print("=" * 76)
    print(f"\n[+] WebUI Server running at: http://{args.host}:{args.port}")
    print("[+] Open this URL in your web browser to review, edit, and orchestrate stories.")
    print("=" * 76 + "\n")

    app.run(host=args.host, port=args.port, debug=False)

if __name__ == "__main__":
    main()
