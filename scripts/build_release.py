"""Build the Windows application and package the public release ZIP."""
from pathlib import Path
import hashlib
import shutil
import subprocess
import sys


def main():
    root = Path(__file__).resolve().parents[1]
    subprocess.run([sys.executable, str(root / "scripts" / "make_icon.py")], cwd=root, check=True)
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", str(root / "PDFLinker.spec")], cwd=root, check=True)
    target = root / "dist" / "PDFLinker"
    source = target / "source"
    source.mkdir(exist_ok=True)
    folders = ("pdflinker", "scripts", "docs")
    files = ("README.md", "LICENSE", "THIRD_PARTY_NOTICES.md", "pyproject.toml", "PDFLinker.spec", "launcher.py", "run.bat", ".gitignore", ".gitattributes")
    for folder in folders:
        shutil.copytree(root / folder, source / folder, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
    for name in files:
        shutil.copy2(root / name, source / name)
    for name in ("README.md", "LICENSE", "THIRD_PARTY_NOTICES.md"):
        shutil.copy2(root / name, target / name)
    for folder in ("docs",):
        shutil.copytree(root / folder, target / folder, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__"))
    copy_dependency_licences(target)
    archive = shutil.make_archive(str(root / "dist" / "PDFLinker-Windows"), "zip", root / "dist", "PDFLinker")
    with Path(archive).open("rb") as stream:
        checksum = hashlib.file_digest(stream, "sha256").hexdigest()
    Path(archive + ".sha256").write_text(f"{checksum}  {Path(archive).name}\n", encoding="ascii")
    print(f"Release: {archive}")


def copy_dependency_licences(target):
    import importlib.metadata
    licences = target / "licences"
    distributions = ("PySide6", "PySide6_Essentials", "PySide6_Addons", "shiboken6", "PyMuPDF", "openpyxl", "et-xmlfile", "xlrd", "numpy", "psutil", "PyYAML", "PyInstaller")
    for name in distributions:
        try:
            distribution = importlib.metadata.distribution(name)
        except importlib.metadata.PackageNotFoundError:
            continue
        for entry in distribution.files or []:
            parts = Path(str(entry)).parts
            if not any(part.lower().startswith(("license", "licence", "copying", "notice")) for part in parts):
                continue
            original = Path(distribution.locate_file(entry))
            if original.is_file():
                destination = licences / name / Path(*[part for part in parts if part not in ("..", ".")])
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(original, destination)
    python_licence = Path(sys.base_prefix) / "LICENSE.txt"
    if python_licence.is_file():
        (licences / "Python").mkdir(parents=True, exist_ok=True)
        shutil.copy2(python_licence, licences / "Python" / "LICENSE.txt")


if __name__ == "__main__":
    main()
