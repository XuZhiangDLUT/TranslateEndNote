# -*- coding: utf-8 -*-
"""
TranslateEndNote Web UI Launcher

This script launches the configuration web UI and handles proper cleanup.
"""

import os
import sys
import argparse
import atexit
import signal
import time
import threading
import webbrowser
from pathlib import Path

# Add the project root to the Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from webui.config_webui import ConfigWebUI


def signal_handler(signum, frame):
    """Handle shutdown signals"""
    print(f"\nReceived signal {signum}, shutting down...")
    sys.exit(0)


def _open_browser(host, port):
    """Open web browser to the specified address"""
    try:
        time.sleep(2)  # Wait for server to start
        url = f"http://{host}:{port}"
        webbrowser.open(url)
        print(f"Browser opened to {url}")
    except Exception as e:
        print(f"Failed to open browser: {e}")


def cleanup():
    """Cleanup function called on exit"""
    print("Cleaning up resources...")
    # Additional cleanup if needed


def main():
    """Main entry point for the web UI launcher"""
    
    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Register cleanup function
    atexit.register(cleanup)
    
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="TranslateEndNote Web UI")
    parser.add_argument("--config", "-c", help="配置文件路径")
    parser.add_argument("--port", "-p", type=int, default=7861, help="端口号 (默认: 7860)")
    parser.add_argument("--host", default="127.0.0.1", help="服务器地址 (默认: 127.0.0.1)")
    parser.add_argument("--share", action="store_true", help="生成公网分享链接")
    parser.add_argument("--debug", action="store_true", help="启用调试模式")
    
    args = parser.parse_args()
    
    # Print startup information
    print("=" * 60)
    print("TranslateEndNote Configuration Web UI")
    print("=" * 60)
    print(f"Working Directory: {os.getcwd()}")
    print(f"Python Version: {sys.version}")
    
    if args.config:
        print(f"Config File: {args.config}")
    
    print(f"Server Address: {args.host}:{args.port}")
    if args.share:
        print("Public share link will be generated")
    
    if args.debug:
        print("Debug mode enabled")
    
    print("=" * 60)
    
    try:
        # Create and launch the web UI
        ui = ConfigWebUI(args.config)
        
        print("\nStarting Web UI...")
        print("Tip: Press Ctrl+C to stop the server")
        
        # Launch the UI
        ui.launch(
            server_name=args.host,
            port=args.port,
            share=args.share
        )
        
        # Auto-open browser after a short delay
        if not args.share:  # Don't auto-open for share mode as it has different URL
            browser_thread = threading.Thread(target=_open_browser, args=(args.host, args.port))
            browser_thread.daemon = True
            browser_thread.start()
        
        # Keep the script running
        print("Web UI started successfully")
        print("Hold Ctrl+C to stop the service...")
        
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nUser requested stop...")
            
    except Exception as e:
        print(f"Startup failed: {e}")
        if args.debug:
            import traceback
            traceback.print_exc()
        sys.exit(1)
    
    finally:
        print("Program ended")


if __name__ == "__main__":
    main()