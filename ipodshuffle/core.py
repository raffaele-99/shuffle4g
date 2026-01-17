import collections
import struct
import os
import hashlib
import urllib.parse
import shutil
import re
import sys

try:
    import mutagen
except ImportError:
    mutagen = None

from .utils import Text2Speech, make_dir_if_absent, validate_unicode, get_relpath, is_path_prefix, audio_ext, list_ext

def group_tracks_by_id3_template(tracks, template):
    grouped_tracks_dict = {}
    template_vars = set(re.findall(r'{.*?}', template))
    for track in tracks:
        try:
            id3_dict = mutagen.File(track, easy=True)
        except:
            id3_dict = {}

        key = template
        single_var_present = False
        for var in template_vars:
            val = id3_dict.get(var[1:-1], [''])[0]
            if len(val) > 0:
                single_var_present = True
            key = key.replace(var, val)

        if single_var_present:
            if key not in grouped_tracks_dict:
                grouped_tracks_dict[key] = []
            grouped_tracks_dict[key].append(track)

    return sorted(grouped_tracks_dict.items())

class Record(object):

    def __init__(self, parent):
        self.parent = parent
        self._struct = collections.OrderedDict([])
        self._fields = {}
        self.track_voiceover = parent.track_voiceover
        self.playlist_voiceover = parent.playlist_voiceover
        self.rename = parent.rename
        self.trackgain = parent.trackgain

    def __getitem__(self, item):
        if item not in list(self._struct.keys()):
            raise KeyError
        return self._fields.get(item, self._struct[item][1])

    def __setitem__(self, item, value):
        self._fields[item] = value

    def construct(self):
        output = bytes()
        for i in list(self._struct.keys()):
            (fmt, default) = self._struct[i]
            output += struct.pack("<" + fmt, self._fields.get(i, default))
        return output

    def text_to_speech(self, text, dbid, playlist = False):
        if self.track_voiceover and not playlist or self.playlist_voiceover and playlist:
            # Create the voiceover wav file
            fn = ''.join(format(x, '02x') for x in reversed(dbid))
            path = os.path.join(self.base, "iPod_Control", "Speakable", "Tracks" if not playlist else "Playlists", fn + ".wav")
            
            verbose_callback = print if self.shuffledb.verbose else lambda *a, **k: None
            return Text2Speech.text2speech(path, text, verboseprint=verbose_callback)
        return False

    def path_to_ipod(self, filename):
        if os.path.commonprefix([os.path.abspath(filename), self.base]) != self.base:
            # raise IOError("Cannot get Ipod filename, since file is outside the IPOD path")
            # Relaxed check or relative path handling? 
            # Original code raised IOError.
            # If we are syncing files, they should be on the iPod now.
            # But let's check if we can support partial paths or if we strictly require abspath match.
            raise IOError(f"Cannot get Ipod filename, since file {filename} is outside the IPOD path {self.base}")
        baselen = len(self.base)
        if self.base.endswith(os.path.sep):
            baselen -= 1
        ipodname = "/".join(os.path.abspath(filename)[baselen:].split(os.path.sep))
        return ipodname

    def ipod_to_path(self, ipodname):
        return os.path.abspath(os.path.join(self.base, os.path.sep.join(ipodname.split("/"))))

    @property
    def shuffledb(self):
        parent = self.parent
        while parent.__class__ != Shuffler:
            parent = parent.parent
        return parent

    @property
    def base(self):
        return self.shuffledb.path

    @property
    def tracks(self):
        return self.shuffledb.tracks

    @property
    def albums(self):
        return self.shuffledb.albums

    @property
    def artists(self):
        return self.shuffledb.artists

    @property
    def lists(self):
        return self.shuffledb.lists

class TunesSD(Record):
    def __init__(self, parent):
        Record.__init__(self, parent)
        self.track_header = TrackHeader(self)
        self.play_header = PlaylistHeader(self)
        self._struct = collections.OrderedDict([
                           ("header_id", ("4s", b"bdhs")), # shdb
                           ("unknown1", ("I", 0x02000003)),
                           ("total_length", ("I", 64)),
                           ("total_number_of_tracks", ("I", 0)),
                           ("total_number_of_playlists", ("I", 0)),
                           ("unknown2", ("Q", 0)),
                           ("max_volume", ("B", 0)),
                           ("voiceover_enabled", ("B", int(self.track_voiceover))),
                           ("unknown3", ("H", 0)),
                           ("total_tracks_without_podcasts", ("I", 0)),
                           ("track_header_offset", ("I", 64)),
                           ("playlist_header_offset", ("I", 0)),
                           ("unknown4", ("20s", b"\x00" * 20)),
                                               ])

    def construct(self):
        # The header is a fixed length, so no need to calculate it
        self.track_header.base_offset = 64
        track_header = self.track_header.construct()

        # The playlist offset will depend on the number of tracks
        self.play_header.base_offset = self.track_header.base_offset + len(track_header)
        play_header = self.play_header.construct(self.track_header.tracks)
        self["playlist_header_offset"] = self.play_header.base_offset

        self["total_number_of_tracks"] = self.track_header["number_of_tracks"]
        self["total_tracks_without_podcasts"] = self.track_header["number_of_tracks"]
        self["total_number_of_playlists"] = self.play_header["number_of_playlists"]

        output = Record.construct(self)
        return output + track_header + play_header

class TrackHeader(Record):
    def __init__(self, parent):
        self.base_offset = 0
        Record.__init__(self, parent)
        self._struct = collections.OrderedDict([
                           ("header_id", ("4s", b"hths")), # shth
                           ("total_length", ("I", 0)),
                           ("number_of_tracks", ("I", 0)),
                           ("unknown1", ("Q", 0)),
                                             ])

    def construct(self):
        self["number_of_tracks"] = len(self.tracks)
        self["total_length"] = 20 + (len(self.tracks) * 4)
        output = Record.construct(self)

        # Construct the underlying tracks
        track_chunk = bytes()
        for i in self.tracks:
            track = Track(self)
            if self.shuffledb.verbose:
                print("[*] Adding track", i)
            track.populate(i)
            output += struct.pack("I", self.base_offset + self["total_length"] + len(track_chunk))
            track_chunk += track.construct()
        return output + track_chunk

class Track(Record):

    def __init__(self, parent):
        Record.__init__(self, parent)
        self._struct = collections.OrderedDict([
                           ("header_id", ("4s", b"rths")), # shtr
                           ("header_length", ("I", 0x174)),
                           ("start_at_pos_ms", ("I", 0)),
                           ("stop_at_pos_ms", ("I", 0)),
                           ("volume_gain", ("I", int(self.trackgain))),
                           ("filetype", ("I", 1)),
                           ("filename", ("256s", b"\x00" * 256)),
                           ("bookmark", ("I", 0)),
                           ("dontskip", ("B", 1)),
                           ("remember", ("B", 0)),
                           ("unintalbum", ("B", 0)),
                           ("unknown", ("B", 0)),
                           ("pregap", ("I", 0x200)),
                           ("postgap", ("I", 0x200)),
                           ("numsamples", ("I", 0)),
                           ("unknown2", ("I", 0)),
                           ("gapless", ("I", 0)),
                           ("unknown3", ("I", 0)),
                           ("albumid", ("I", 0)),
                           ("track", ("H", 1)),
                           ("disc", ("H", 0)),
                           ("unknown4", ("Q", 0)),
                           ("dbid", ("8s", 0)),
                           ("artistid", ("I", 0)),
                           ("unknown5", ("32s", b"\x00" * 32)),
                           ])

    def populate(self, filename):
        self["filename"] = self.path_to_ipod(filename).encode('utf-8')

        if os.path.splitext(filename)[1].lower() in (".m4a", ".m4b", ".m4p", ".aa"):
            self["filetype"] = 2

        text = os.path.splitext(os.path.basename(filename))[0]

        # Try to get album and artist information with mutagen
        if mutagen:
            audio = None
            try:
                audio = mutagen.File(filename, easy = True)
            except:
                print("Error calling mutagen. Possible invalid filename/ID3Tags (hyphen in filename?)")
            if audio:
                # Note: Rythmbox IPod plugin sets this value always 0.
                self["stop_at_pos_ms"] = int(audio.info.length * 1000)

                artist = audio.get("artist", ["Unknown"])[0]
                if artist in self.artists:
                    self["artistid"] = self.artists.index(artist)
                else:
                    self["artistid"] = len(self.artists)
                    self.artists.append(artist)

                album = audio.get("album", ["Unknown"])[0]
                if album in self.albums:
                    self["albumid"] = self.albums.index(album)
                else:
                    self["albumid"] = len(self.albums)
                    self.albums.append(album)

                if audio.get("title", "") and audio.get("artist", ""):
                    text = " - ".join(audio.get("title", "") + audio.get("artist", ""))

        # Handle the VoiceOverData
        if isinstance(text, str):
            text = text.encode('utf-8', 'ignore')
        self["dbid"] = hashlib.md5(text).digest()[:8]
        self.text_to_speech(text, self["dbid"])

class PlaylistHeader(Record):
    def __init__(self, parent):
        self.base_offset = 0
        Record.__init__(self, parent)
        self._struct = collections.OrderedDict([
                          ("header_id", ("4s", b"hphs")), #shph
                          ("total_length", ("I", 0)),
                          ("number_of_playlists", ("I", 0)),
                          ("number_of_non_podcast_lists", ("2s", b"\xFF\xFF")),
                          ("number_of_master_lists", ("2s", b"\x01\x00")),
                          ("number_of_non_audiobook_lists", ("2s", b"\xFF\xFF")),
                          ("unknown2", ("2s", b"\x00" * 2)),
                                              ])

    def construct(self, tracks):
        # Build the master list
        masterlist = Playlist(self)
        if self.shuffledb.verbose:
            print("[+] Adding master playlist")
        masterlist.set_master(tracks)
        chunks = [masterlist.construct(tracks)]

        # Build all the remaining playlists
        playlistcount = 1
        for i in self.lists:
            playlist = Playlist(self)
            if self.shuffledb.verbose:
                print("[+] Adding playlist", (i[0] if type(i) == type(()) else i))
            playlist.populate(i)
            
            # Catch errors in logic or bad playlists
            try:
                construction = playlist.construct(tracks)
                if playlist["number_of_songs"] > 0:
                    playlistcount += 1
                    chunks += [construction]
                else:
                    print("Error: Playlist does not contain a single track. Skipping playlist.")
            except Exception as e:
                print(f"Error constructing playlist: {e}")

        self["number_of_playlists"] = playlistcount
        self["total_length"] = 0x14 + (self["number_of_playlists"] * 4)
        # Start the header

        output = Record.construct(self)
        offset = self.base_offset + self["total_length"]

        for i in range(len(chunks)):
            output += struct.pack("I", offset)
            offset += len(chunks[i])

        return output + b"".join(chunks)

class Playlist(Record):
    def __init__(self, parent):
        self.listtracks = []
        Record.__init__(self, parent)
        self._struct = collections.OrderedDict([
                          ("header_id", ("4s", b"lphs")), # shpl
                          ("total_length", ("I", 0)),
                          ("number_of_songs", ("I", 0)),
                          ("number_of_nonaudio", ("I", 0)),
                          ("dbid", ("8s", b"\x00" * 8)),
                          ("listtype", ("I", 2)),
                          ("unknown1", ("16s", b"\x00" * 16))
                                              ])

    def set_master(self, tracks):
        # By default use "All Songs" builtin voiceover (dbid all zero)
        # Else generate alternative "All Songs" to fit the speaker voice of other playlists
        if self.playlist_voiceover and (Text2Speech.valid_tts['pico2wave'] or Text2Speech.valid_tts['espeak'] or Text2Speech.valid_tts['say']):
            self["dbid"] = hashlib.md5(b"masterlist").digest()[:8]
            self.text_to_speech("All songs", self["dbid"], True)
        self["listtype"] = 1
        self.listtracks = tracks

    def populate_m3u(self, data):
        listtracks = []
        for i in data:
            if not i.startswith("#"):
                path = i.strip()
                if self.rename:
                    path = validate_unicode(path)
                listtracks.append(path)
        return listtracks

    def populate_pls(self, data):
        sorttracks = []
        for i in data:
            dataarr = i.strip().split("=", 1)
            if dataarr[0].lower().startswith("file"):
                num = int(dataarr[0][4:])
                filename = urllib.parse.unquote(dataarr[1]).strip()
                if filename.lower().startswith('file://'):
                    filename = filename[7:]
                if self.rename:
                    filename = validate_unicode(filename)
                sorttracks.append((num, filename))
        listtracks = [ x for (_, x) in sorted(sorttracks) ]
        return listtracks

    def populate_directory(self, playlistpath, recursive = True):
        # Add all tracks inside the folder and its subfolders recursively.
        # Folders containing no music and only a single Album
        # would generate duplicated playlists. That is intended and "wont fix".
        # Empty folders (inside the music path) will generate an error -> "wont fix".
        listtracks = []
        for (dirpath, dirnames, filenames) in os.walk(playlistpath):
            dirnames.sort()

            # Ignore any hidden directories
            if "/." not in dirpath:
                for filename in sorted(filenames, key = lambda x: x.lower()):
                    # Only add valid music files to playlist
                    if os.path.splitext(filename)[1].lower() in audio_ext:
                        fullPath = os.path.abspath(os.path.join(dirpath, filename))
                        listtracks.append(fullPath)
            if not recursive:
                break
        return listtracks

    def remove_relatives(self, relative, filename):
        base = os.path.dirname(os.path.abspath(filename))
        if not os.path.exists(relative):
            relative = os.path.join(base, relative)
        fullPath = relative
        return fullPath

    def populate(self, obj):
        # Create a playlist of the folder and all subfolders
        if type(obj) == type(()):
            self.listtracks = obj[1]
            text = obj[0]
        else:
            filename = obj
            if os.path.isdir(filename):
                self.listtracks = self.populate_directory(filename)
                text = os.path.splitext(os.path.basename(filename))[0]
            else:
                # Read the playlist file
                with open(filename, 'r', errors="replace") as f:
                    data = f.readlines()

                extension = os.path.splitext(filename)[1].lower()
                if extension == '.pls':
                    self.listtracks = self.populate_pls(data)
                elif extension == '.m3u':
                    self.listtracks = self.populate_m3u(data)
                else:
                    raise Exception("Unknown playlist extension")

                # Ensure all paths are not relative to the playlist file
                for i in range(len(self.listtracks)):
                    self.listtracks[i] = self.remove_relatives(self.listtracks[i], filename)
                text = os.path.splitext(os.path.basename(filename))[0]

        # Handle the VoiceOverData
        self["dbid"] = hashlib.md5(text.encode('utf-8')).digest()[:8]
        self.text_to_speech(text, self["dbid"], True)

    def construct(self, tracks):
        self["total_length"] = 44 + (4 * len(self.listtracks))
        self["number_of_songs"] = 0

        chunks = bytes()
        for i in self.listtracks:
            path = self.ipod_to_path(i)
            position = -1
            try:
                position = tracks.index(path)
            except:
                # Print an error if no track was found.
                # Empty playlists are handeled in the PlaylistHeader class.
                print("Error: Could not find track \"" + path + "\".")
                print("Maybe its an invalid FAT filesystem name. Please fix your playlist. Skipping track.")
            if position > -1:
                chunks += struct.pack("I", position)
                self["number_of_songs"] += 1
        self["number_of_nonaudio"] = self["number_of_songs"]

        output = Record.construct(self)
        return output + chunks

class Shuffler(object):
    def __init__(self, path, track_voiceover=False, playlist_voiceover=False, rename=False, trackgain=0, auto_dir_playlists=None, auto_id3_playlists=None, verbose=False):
        self.path = os.path.abspath(path)
        self.tracks = []
        self.albums = []
        self.artists = []
        self.lists = []
        self.tunessd = None
        self.track_voiceover = track_voiceover
        self.playlist_voiceover = playlist_voiceover
        self.rename = rename
        self.trackgain = trackgain
        self.auto_dir_playlists = auto_dir_playlists
        self.auto_id3_playlists = auto_id3_playlists
        self.verbose = verbose

    def initialize(self):
      # remove existing voiceover files (they are either useless or will be overwritten anyway)
      for dirname in ('iPod_Control/Speakable/Playlists', 'iPod_Control/Speakable/Tracks'):
          shutil.rmtree(os.path.join(self.path, dirname), ignore_errors=True)
      for dirname in ('iPod_Control/iTunes', 'iPod_Control/Music', 'iPod_Control/Speakable/Playlists', 'iPod_Control/Speakable/Tracks'):
          make_dir_if_absent(os.path.join(self.path, dirname))

    def dump_state(self):
        print("Shuffle DB state")
        print("Tracks", self.tracks)
        print("Albums", self.albums)
        print("Artists", self.artists)
        print("Playlists", self.lists)

    def populate(self):
        self.tunessd = TunesSD(self)
        for (dirpath, dirnames, filenames) in os.walk(self.path):
            dirnames.sort()
            relpath = get_relpath(dirpath, self.path)
            # Ignore the speakable directory and any hidden directories
            if not is_path_prefix("iPod_Control/Speakable", relpath) and "/." not in dirpath:
                for filename in sorted(filenames, key = lambda x: x.lower()):
                    # Ignore hidden files
                    if not filename.startswith("."):
                        fullPath = os.path.abspath(os.path.join(dirpath, filename))
                        if os.path.splitext(filename)[1].lower() in audio_ext:
                            self.tracks.append(fullPath)
                        if os.path.splitext(filename)[1].lower() in list_ext:
                            self.lists.append(fullPath)

            # Create automatic playlists in music directory.
            # Ignore the (music) root and any hidden directories.
            if self.auto_dir_playlists and "iPod_Control/Music/" in dirpath and "/." not in dirpath:
                # Only go to a specific depth. -1 is unlimted, 0 is ignored as there is already a master playlist.
                depth = dirpath[len(self.path) + len(os.path.sep):].count(os.path.sep) - 1
                if self.auto_dir_playlists < 0 or depth <= self.auto_dir_playlists:
                    self.lists.append(os.path.abspath(dirpath))

        if self.auto_id3_playlists != None:
            if mutagen:
                for grouped_list in group_tracks_by_id3_template(self.tracks, self.auto_id3_playlists):
                    self.lists.append(grouped_list)
            else:
                print("Error: No mutagen found. Cannot generate auto-id3-playlists.")
                sys.exit(1)

    def write_database(self):
        print("Writing database. This may take a while...")
        with open(os.path.join(self.path, "iPod_Control", "iTunes", "iTunesSD"), "wb") as f:
            try:
                f.write(self.tunessd.construct())
            except IOError as e:
                print("I/O error({0}): {1}".format(e.errno, e.strerror))
                print("Error: Writing iPod database failed.")
                sys.exit(1)

        print("Database written successfully:")
        print("Tracks", len(self.tracks))
        print("Albums", len(self.albums))
        print("Artists", len(self.artists))
        print("Playlists", len(self.lists))
