"""Launch the game with TkAgg from a terminal or a Jupyter notebook."""

import matplotlib

# Select the backend before importing the UI so every launch uses the scaled canvas.
# PyInstaller also detects this literal backend name when collecting dependencies.
matplotlib.use("TkAgg")

from ballistic_lab.ui import TrajectoryUI
from ballistic_lab.settings import SettingsStore
from ballistic_lab.sound import SoundPlayer


def main():
    interface = TrajectoryUI(settings_store=SettingsStore())
    interface.audio = SoundPlayer(enabled=interface.sound_enabled,
                                  volume=interface.display_settings["sound_volume"])
    interface.show()
    return interface


if __name__ == "__main__":
    # Keep the interface and its callbacks alive in interactive notebooks.
    app = main()
