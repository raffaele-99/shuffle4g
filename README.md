# shuffle4g

Desktop app to manage an iPod Shuffle 4th Generation.

<div justify="center">
<img width="1135" height="765" alt="Screenshot 2026-01-17 at 3 53 03 pm" src="https://github.com/user-attachments/assets/7b0c9e78-48f1-40c6-b87e-21a079c24c9b" />
</div>

This is just a GUI repackage of an existing tool, **the actual hard work was done by [nims11/IPod-Shuffle-4g](https://github.com/nims11/IPod-Shuffle-4g).**

## What works

- moving mp3s to ipod and rebuilding the internal database a la itunes style

## TODO

- separate file copying from database creation (so users can rebuild databases of connected ipods without having to choose a source mp3 folder)
- detect when an ipod is connected via USB + display connection status indicator
- validate that the selected destination volume is actually an ipod
- implement filesystem support to display what mp3s are on the ipod
- add some sort of "check status" feature that checks if there any "ghost" mp3s on the ipod (i.e. mp3s that do not have entries in the internal database)
- allow users to safely eject ipod disk from within the app
