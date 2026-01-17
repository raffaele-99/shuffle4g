import customtkinter
import os
import threading
import sys
import shutil
import time
from tkinter import filedialog, messagebox

# Import ipodshuffle modules
from .core import Shuffler
from .utils import make_dir_if_absent, check_unicode

customtkinter.set_appearance_mode("System")
customtkinter.set_default_color_theme("blue")

class RedirectText(object):
    def __init__(self, text_ctrl):
        self.output = text_ctrl

    def write(self, string):
        self.output.insert("end", string)
        self.output.see("end")

    def flush(self):
        pass

class App(customtkinter.CTk):
    def __init__(self):
        super().__init__()

        self.title("iPod Shuffle Manager")
        self.geometry("800x600")

        # Configure grid layout
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Sidebar
        self.sidebar_frame = customtkinter.CTkFrame(self, width=140, corner_radius=0)
        self.sidebar_frame.grid(row=0, column=0, rowspan=4, sticky="nsew")
        self.sidebar_frame.grid_rowconfigure(4, weight=1)

        self.logo_label = customtkinter.CTkLabel(self.sidebar_frame, text="iPod Shuffle", font=customtkinter.CTkFont(size=20, weight="bold"))
        self.logo_label.grid(row=0, column=0, padx=20, pady=(20, 10))

        self.appearance_mode_label = customtkinter.CTkLabel(self.sidebar_frame, text="Appearance Mode:", anchor="w")
        self.appearance_mode_label.grid(row=5, column=0, padx=20, pady=(10, 0))
        self.appearance_mode_optionemenu = customtkinter.CTkOptionMenu(self.sidebar_frame, values=["System", "Light", "Dark"],
                                                                       command=self.change_appearance_mode_event)
        self.appearance_mode_optionemenu.grid(row=6, column=0, padx=20, pady=(10, 10))

        # Main Content
        self.main_frame = customtkinter.CTkFrame(self)
        self.main_frame.grid(row=0, column=1, padx=20, pady=20, sticky="nsew")
        self.main_frame.grid_columnconfigure(1, weight=1)

        # Paths
        self.source_path_label = customtkinter.CTkLabel(self.main_frame, text="Local Music Folder:")
        self.source_path_label.grid(row=0, column=0, padx=10, pady=10, sticky="w")
        self.source_path_entry = customtkinter.CTkEntry(self.main_frame)
        self.source_path_entry.grid(row=0, column=1, padx=10, pady=10, sticky="ew")
        self.source_browse_btn = customtkinter.CTkButton(self.main_frame, text="Browse", command=self.browse_source)
        self.source_browse_btn.grid(row=0, column=2, padx=10, pady=10)

        self.ipod_path_label = customtkinter.CTkLabel(self.main_frame, text="iPod Mount Point:")
        self.ipod_path_label.grid(row=1, column=0, padx=10, pady=10, sticky="w")
        self.ipod_path_entry = customtkinter.CTkEntry(self.main_frame)
        self.ipod_path_entry.grid(row=1, column=1, padx=10, pady=10, sticky="ew")
        self.ipod_browse_btn = customtkinter.CTkButton(self.main_frame, text="Browse", command=self.browse_ipod)
        self.ipod_browse_btn.grid(row=1, column=2, padx=10, pady=10)

        # Options
        self.options_frame = customtkinter.CTkFrame(self.main_frame)
        self.options_frame.grid(row=2, column=0, columnspan=3, padx=10, pady=10, sticky="ew")

        self.track_voiceover_var = customtkinter.BooleanVar()
        self.track_voiceover_chk = customtkinter.CTkCheckBox(self.options_frame, text="Track Voiceover", variable=self.track_voiceover_var)
        self.track_voiceover_chk.grid(row=0, column=0, padx=10, pady=10)

        self.playlist_voiceover_var = customtkinter.BooleanVar()
        self.playlist_voiceover_chk = customtkinter.CTkCheckBox(self.options_frame, text="Playlist Voiceover", variable=self.playlist_voiceover_var)
        self.playlist_voiceover_chk.grid(row=0, column=1, padx=10, pady=10)

        self.rename_unicode_var = customtkinter.BooleanVar()
        self.rename_unicode_chk = customtkinter.CTkCheckBox(self.options_frame, text="Rename Unicode", variable=self.rename_unicode_var)
        self.rename_unicode_chk.grid(row=0, column=2, padx=10, pady=10)
        
        self.sync_files_var = customtkinter.BooleanVar(value=True)
        self.sync_files_chk = customtkinter.CTkCheckBox(self.options_frame, text="Copy/Sync Files", variable=self.sync_files_var)
        self.sync_files_chk.grid(row=0, column=3, padx=10, pady=10)

        self.gain_label = customtkinter.CTkLabel(self.options_frame, text="Track Gain (0-99):")
        self.gain_label.grid(row=1, column=0, padx=10, pady=10, sticky="e")
        self.gain_entry = customtkinter.CTkEntry(self.options_frame, width=50)
        self.gain_entry.grid(row=1, column=1, padx=10, pady=10, sticky="w")
        self.gain_entry.insert(0, "0")

        # Action
        self.run_btn = customtkinter.CTkButton(self.main_frame, text="Start Sync & Update", command=self.start_processing_thread)
        self.run_btn.grid(row=3, column=0, columnspan=3, padx=20, pady=20)

        # Log
        self.textbox = customtkinter.CTkTextbox(self.main_frame, width=250)
        self.textbox.grid(row=4, column=0, columnspan=3, padx=10, pady=10, sticky="nsew")
        self.main_frame.grid_rowconfigure(4, weight=1)

        # Try to detect iPod
        self.detect_ipod()

    def change_appearance_mode_event(self, new_appearance_mode: str):
        customtkinter.set_appearance_mode(new_appearance_mode)

    def browse_source(self):
        filename = filedialog.askdirectory()
        if filename:
            self.source_path_entry.delete(0, "end")
            self.source_path_entry.insert(0, filename)

    def browse_ipod(self):
        filename = filedialog.askdirectory()
        if filename:
            self.ipod_path_entry.delete(0, "end")
            self.ipod_path_entry.insert(0, filename)

    def detect_ipod(self):
        # Very basic detection for typical mount points
        potential = "/Volumes/IPOD"
        if os.path.exists(potential):
            self.ipod_path_entry.insert(0, potential)

    def start_processing_thread(self):
        self.run_btn.configure(state="disabled", text="Running...")
        threading.Thread(target=self.run_process).start()

    def run_process(self):
        # Redirect stdout
        old_stdout = sys.stdout
        sys.stdout = RedirectText(self.textbox)
        
        try:
            source = self.source_path_entry.get()
            ipod = self.ipod_path_entry.get()
            
            if not os.path.isdir(ipod):
                print("Error: Invalid iPod path.")
                return
            
            if self.sync_files_var.get():
                if not os.path.isdir(source):
                    print("Error: Invalid Source path for sync.")
                    return
                print("Syncing files...")
                self.sync_files(source, ipod)
            
            print("Starting Shuffle Update...")
            try:
                gain = int(self.gain_entry.get())
            except:
                gain = 0

            shuffle = Shuffler(ipod, 
                               track_voiceover=self.track_voiceover_var.get(),
                               playlist_voiceover=self.playlist_voiceover_var.get(),
                               rename=self.rename_unicode_var.get(),
                               trackgain=gain,
                               verbose=True) # Force verbose for GUI log
            
            shuffle.initialize()
            shuffle.populate()
            shuffle.write_database()
            print("Done!")
            
        except Exception as e:
            print(f"An error occurred: {e}")
            import traceback
            traceback.print_exc()
        finally:
            sys.stdout = old_stdout
            self.run_btn.configure(state="normal", text="Start Sync & Update")

    def sync_files(self, source, ipod_root):
        dest_dir = os.path.join(ipod_root, "iPod_Control", "Music")
        make_dir_if_absent(dest_dir)
        
        print(f"Copying from {source} to {dest_dir}")
        # shutil.copytree(source, dest_dir, dirs_exist_ok=True) if supported
        if sys.version_info >= (3, 8):
            shutil.copytree(source, dest_dir, dirs_exist_ok=True)
        else:
            for root, dirs, files in os.walk(source):
                rel_path = os.path.relpath(root, source)
                target_path = os.path.join(dest_dir, rel_path)
                make_dir_if_absent(target_path)
                for file in files:
                    s = os.path.join(root, file)
                    d = os.path.join(target_path, file)
                    if not os.path.exists(d) or os.stat(s).st_mtime - os.stat(d).st_mtime > 1:
                        shutil.copy2(s, d)
                        print(f"Copied {file}")
        
        # If Rename Unicode is on, check_unicode on destination
        if self.rename_unicode_var.get():
             check_unicode(dest_dir)

if __name__ == "__main__":
    app = App()
    app.mainloop()
