#!/usr/bin/env python3
import sys
import os

# Add src to path so we can import shuffle4g when running directly
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from shuffle4g import cli, gui

def main():
    if len(sys.argv) > 1:
        # If arguments are provided, assume CLI mode
        cli.main()
    else:
        # Otherwise, launch the GUI
        app = gui.App()
        app.mainloop()

if __name__ == "__main__":
    main()
