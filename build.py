import PyInstaller.__main__
import sys
import os

root = os.path.dirname(os.path.abspath(__file__))
resources = os.path.join(root, "resources")

sep = ";" if sys.platform == "win32" else ":"

icon = os.path.join(resources, "icon.ico" if sys.platform == "win32" else "icon.icns")

args = [
    "installer_ui.py",
    "--name=PokemonInfiniteFusion-Installer",
    "--onefile",
    "--windowed",
    f"--add-data={resources}{sep}resources",
    "--clean",
    "--noconfirm",
]

if os.path.isfile(icon):
    args.append(f"--icon={icon}")

PyInstaller.__main__.run(args)