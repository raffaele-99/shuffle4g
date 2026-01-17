import sys
import os
import signal
import argparse

try:
    import mutagen
except ImportError:
    mutagen = None

from .utils import Text2Speech, check_unicode
from .core import Shuffler

def nonnegative_int(string):
    try:
        intval = int(string)
    except ValueError:
        raise argparse.ArgumentTypeError("'%s' must be an integer" % string)

    if intval < 0 or intval > 99:
        raise argparse.ArgumentTypeError("Track gain value should be in range 0-99")
    return intval

def checkPathValidity(path):
    if not os.path.isdir(path):
        print("Error finding IPod directory. Maybe it is not connected or mounted?")
        sys.exit(1)

    if not os.access(path, os.W_OK):
        print('Unable to get write permissions in the IPod directory')
        sys.exit(1)

def handle_interrupt(signal, frame):
    print("Interrupt detected, exiting...")
    sys.exit(1)

def main():
    signal.signal(signal.SIGINT, handle_interrupt)

    parser = argparse.ArgumentParser(description=
    'Python script for building the Track and Playlist database '
    'for the newer gen IPod Shuffle. Version 1.5')

    parser.add_argument('-t', '--track-voiceover', action='store_true',
    help='Enable track voiceover feature')

    parser.add_argument('-p', '--playlist-voiceover', action='store_true',
    help='Enable playlist voiceover feature')

    parser.add_argument('-u', '--rename-unicode', action='store_true',
    help='Rename files causing unicode errors, will do minimal required renaming')

    parser.add_argument('-g', '--track-gain', type=nonnegative_int, default='0',
    help='Specify volume gain (0-99) for all tracks; '
    '0 (default) means no gain and is usually fine; '
    'e.g. 60 is very loud even on minimal player volume')

    parser.add_argument('-d', '--auto-dir-playlists', type=int, default=None, const=-1, nargs='?',
    help='Generate automatic playlists for each folder recursively inside '
    '"IPod_Control/Music/". You can optionally limit the depth: '
    '0=root, 1=artist, 2=album, n=subfoldername, default=-1 (No Limit).')

    parser.add_argument('-i', '--auto-id3-playlists', type=str, default=None, metavar='ID3_TEMPLATE', const='{artist}', nargs='?',
    help='Generate automatic playlists based on the id3 tags of any music '
    'added to the iPod. You can optionally specify a template string '
    'based on which id3 tags are used to generate playlists. For eg. '
    '\'{artist} - {album}\' will use the pair of artist and album to group '
    'tracks under one playlist. Similarly \'{genre}\' will group tracks based '
    'on their genre tag. Default template used is \'{artist}\'')

    parser.add_argument('-v', '--verbose', action='store_true',
    help='Show verbose output of database generation.')

    parser.add_argument('path', help='Path to the IPod\'s root directory')

    result = parser.parse_args()

    # Enable verbose printing if desired
    verboseprint = print if result.verbose else lambda *a, **k: None

    checkPathValidity(result.path)

    if result.rename_unicode:
        check_unicode(result.path)

    if not mutagen:
        print("Warning: No mutagen found. Database will not contain any album nor artist information.")

    verboseprint("Playlist voiceover requested:", result.playlist_voiceover)
    verboseprint("Track voiceover requested:", result.track_voiceover)
    if (result.track_voiceover or result.playlist_voiceover):
        if not Text2Speech.check_support():
            print("Error: Did not find any voiceover program. Voiceover disabled.")
            result.track_voiceover = False
            result.playlist_voiceover = False
        else:
            verboseprint("Voiceover available.")

    shuffle = Shuffler(result.path,
                       track_voiceover=result.track_voiceover,
                       playlist_voiceover=result.playlist_voiceover,
                       rename=result.rename_unicode,
                       trackgain=result.track_gain,
                       auto_dir_playlists=result.auto_dir_playlists,
                       auto_id3_playlists=result.auto_id3_playlists,
                       verbose=result.verbose)
    shuffle.initialize()
    shuffle.populate()
    shuffle.write_database()

if __name__ == '__main__':
    main()
