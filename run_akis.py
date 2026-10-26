"""PyInstaller ve doğrudan çalıştırma için giriş noktası."""
import sys

from akis.app import main

if __name__ == "__main__":
    sys.exit(main())
