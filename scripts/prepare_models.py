"""Install the pinned Medium data files before building or running from source."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pdflinker.model_packs import PackManager, bundled_model_directory


def main():
    manager = PackManager(root=bundled_model_directory())
    if manager.installed('medium-v1', verify=True):
        print('Bundled Medium models are ready.')
        return
    archive = ROOT / 'dist' / 'model-packs' / 'PDFLinker-Medium-v1.zip'
    if archive.is_file():
        print('Preparing bundled Medium models from the local archive...', flush=True)
        manager.install_archive('medium-v1', archive)
    else:
        print('Downloading pinned Medium models for the application bundle...', flush=True)
        manager.download('medium-v1')
    print('Bundled Medium models verified and ready.')


if __name__ == '__main__':
    main()
