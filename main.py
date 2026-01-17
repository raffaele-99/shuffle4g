#!/usr/bin/env python3
import sys
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
