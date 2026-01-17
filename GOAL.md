# Overview

This is a fork of a repository that was created to manage music on an iPod Shuffle 4th generation. The original repository is not being maintained and has some issues that I would like to fix. I would also like to add some new features to the project.


## Issues

- The script combines the CLI and core functionality into a single file.

# Primary Goal

- Separate the CLI and core library into separate files.
- A GUI that uses the core library (using `customtkinter`) that allows the user to select a directory of music files and a directory of playlists, and then transfer them to their iPod Shuffle 4th generation.
- A single-packaged executable that can be run on macOS/Windows/Linux (via PyInstaller) without requiring the user to install any dependencies.
