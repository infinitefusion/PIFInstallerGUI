import PyInstaller.__main__
import sys
import os

root = os.path.dirname(os.path.abspath(__file__))
resources = os.path.join(root, "resources")
entrypoint = os.path.join(root, "installer_ui.py")
bundled_wine = os.path.join(root, "vendor", "wine")
third_party_notices = os.path.join(root, "THIRD_PARTY_NOTICES.md")

sep = ";" if sys.platform == "win32" else ":"

icon = os.path.join(resources, "icon.ico" if sys.platform == "win32" else "icon.icns")

args = [
    entrypoint,
    "--name=PokemonInfiniteFusion-Launcher",
    f"--add-data={resources}{sep}resources",
    f"--add-data={third_party_notices}{sep}.",
    f"--distpath={os.path.join(root, 'dist')}",
    f"--workpath={os.path.join(root, 'build')}",
    f"--specpath={os.path.join(root, 'build', 'spec')}",
    "--clean",
    "--noconfirm",
]

args.append("--console" if os.environ.get("PIF_BUILD_CONSOLE") == "1" else "--windowed")

if sys.platform == "win32":
    args.append("--onefile")
elif sys.platform == "darwin":
    # A directory-backed .app is substantially easier to sign/notarize and
    # also permits an optional pre-bundled Wine runtime.
    args.append("--osx-bundle-identifier=net.infinitefusion.launcher")
    signing_identity = os.environ.get("PIF_CODESIGN_IDENTITY", "").strip()
    entitlements_file = os.environ.get("PIF_CODESIGN_ENTITLEMENTS", "").strip()
    if signing_identity:
        args.append(f"--codesign-identity={signing_identity}")
    if entitlements_file:
        if not os.path.isfile(entitlements_file):
            raise FileNotFoundError(
                f"PIF_CODESIGN_ENTITLEMENTS does not exist: {entitlements_file}"
            )
        args.append(f"--osx-entitlements-file={entitlements_file}")

if os.path.isdir(bundled_wine):
    args.append(f"--add-data={bundled_wine}{sep}wine")

if os.path.isfile(icon):
    args.append(f"--icon={icon}")

PyInstaller.__main__.run(args)
