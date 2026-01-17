import os
import errno
import hashlib
import subprocess
import re
import tempfile
import shutil

audio_ext = (".mp3", ".m4a", ".m4b", ".m4p", ".aa", ".wav")
list_ext = (".pls", ".m3u")

def make_dir_if_absent(path):
    try:
        os.makedirs(path)
    except OSError as exc:
        if exc.errno != errno.EEXIST:
            raise

def raises_unicode_error(string):
    try:
        string.encode('latin-1')
        return False
    except (UnicodeEncodeError, UnicodeDecodeError):
        return True

def hash_error_unicode(item):
    item_bytes = item.encode('utf-8')
    return "".join(["{0:02X}".format(ord(x)) for x in reversed(hashlib.md5(item_bytes).hexdigest()[:8])])

def validate_unicode(path):
    path_list = path.split('/')
    last_raise = False
    for i in range(len(path_list)):
        if raises_unicode_error(path_list[i]):
            path_list[i] = hash_error_unicode(path_list[i])
            last_raise = True
        else:
            last_raise = False
    extension = os.path.splitext(path)[1].lower()
    return "/".join(path_list) + (extension if last_raise and extension in audio_ext else '')

def exec_exists_in_path(command):
    with open(os.devnull, 'w') as FNULL:
        try:
            with open(os.devnull, 'r') as RFNULL:
                subprocess.call([command], stdout=FNULL, stderr=subprocess.STDOUT, stdin=RFNULL)
                return True
        except OSError as e:
            return False

def splitpath(path):
    return path.split(os.sep)

def get_relpath(path, basepath):
    commonprefix = os.sep.join(os.path.commonprefix(list(map(splitpath, [path, basepath]))))
    return os.path.relpath(path, commonprefix)

def is_path_prefix(prefix, path):
    return prefix == os.sep.join(os.path.commonprefix(list(map(splitpath, [prefix, path]))))

def check_unicode(path):
    ret_flag = False # True if there is a recognizable file within this level
    try:
        items = os.listdir(path)
    except OSError:
        return False # Cannot read directory

    for item in items:
        full_path = os.path.join(path, item)
        if os.path.isfile(full_path):
            if os.path.splitext(item)[1].lower() in audio_ext+list_ext:
                ret_flag = True
                if raises_unicode_error(item):
                    src = full_path
                    dest = os.path.join(path, hash_error_unicode(item)) + os.path.splitext(item)[1].lower()
                    print('Renaming %s -> %s' % (src, dest))
                    os.rename(src, dest)
        elif os.path.isdir(full_path):
            ret_flag = (check_unicode(full_path) or ret_flag)
            if ret_flag and raises_unicode_error(item):
                src = full_path
                new_name = hash_error_unicode(item)
                dest = os.path.join(path, new_name)
                print('Renaming %s -> %s' % (src, dest))
                os.rename(src, dest)
    return ret_flag

class Text2Speech(object):
    valid_tts = {'pico2wave': True, 'RHVoice': True, 'espeak': True, 'say': True}

    @staticmethod
    def check_support():
        voiceoverAvailable = False

        # Check for macOS say voiceover
        if not exec_exists_in_path("say"):
            Text2Speech.valid_tts['say'] = False
            # print("Warning: macOS say not found, voicever won't be generated using it.")
        else:
            voiceoverAvailable = True

        # Check for pico2wave voiceover
        if not exec_exists_in_path("pico2wave"):
            Text2Speech.valid_tts['pico2wave'] = False
            # print("Warning: pico2wave not found, voicever won't be generated using it.")
        else:
            voiceoverAvailable = True

        # Check for espeak voiceover
        if not exec_exists_in_path("espeak"):
            Text2Speech.valid_tts['espeak'] = False
            # print("Warning: espeak not found, voicever won't be generated using it.")
        else:
            voiceoverAvailable = True

        # Check for Russian RHVoice voiceover
        if not exec_exists_in_path("RHVoice"):
            Text2Speech.valid_tts['RHVoice'] = False
            # print("Warning: RHVoice not found, Russian voicever won't be generated.")
        else:
            voiceoverAvailable = True

        # Return if we at least found one voiceover program.
        # Otherwise this will result in silent voiceover for tracks and "Playlist N" for playlists.
        return voiceoverAvailable

    @staticmethod
    def text2speech(out_wav_path, text, verboseprint=lambda *a, **k: None):
        # Skip voiceover generation if a track with the same name is used.
        # This might happen with "Track001" or "01. Intro" names for example.
        if os.path.isfile(out_wav_path):
            verboseprint("Using existing", out_wav_path)
            return True

        # ensure we deal with unicode later
        if not isinstance(text, str):
            text = str(text, 'utf-8')
        lang = Text2Speech.guess_lang(text)
        if lang == "ru-RU":
            return Text2Speech.rhvoice(out_wav_path, text)
        else:
            if Text2Speech.pico2wave(out_wav_path, text):
                return True
            elif Text2Speech.espeak(out_wav_path, text):
                return True
            elif Text2Speech.say(out_wav_path, text):
                return True
            else:
                return False

    # guess-language seems like an overkill for now
    @staticmethod
    def guess_lang(unicodetext):
        lang = 'en-GB'
        if re.search("[А-Яа-я]", unicodetext) is not None:
            lang = 'ru-RU'
        return lang

    @staticmethod
    def pico2wave(out_wav_path, unicodetext):
        if not Text2Speech.valid_tts['pico2wave']:
            return False
        subprocess.call(["pico2wave", "-l", "en-GB", "-w", out_wav_path, '--', unicodetext])
        return True

    @staticmethod
    def say(out_wav_path, unicodetext):
        if not Text2Speech.valid_tts['say']:
            return False
        subprocess.call(["say", "-o", out_wav_path, '--data-format=LEI16', '--file-format=WAVE', '--', unicodetext])
        return True

    @staticmethod
    def espeak(out_wav_path, unicodetext):
        if not Text2Speech.valid_tts['espeak']:
            return False
        subprocess.call(["espeak", "-v", "english_rp", "-s", "150", "-w", out_wav_path, '--', unicodetext])
        return True

    @staticmethod
    def rhvoice(out_wav_path, unicodetext):
        if not Text2Speech.valid_tts['RHVoice']:
            return False

        tmp_file = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp_file.close()

        proc = subprocess.Popen(["RHVoice", "--voice=Elena", "--variant=Russian", "--volume=100", "-o", tmp_file.name], stdin=subprocess.PIPE)
        proc.communicate(input=unicodetext.encode('utf-8'))
        # make a little bit louder to be comparable with pico2wave
        subprocess.call(["sox", tmp_file.name, out_wav_path, "norm"])

        os.remove(tmp_file.name)
        return True
