"""Backward-compatible entry point for the native desktop application."""
from native_desktop import main
if __name__ == '__main__':
    raise SystemExit(main())
