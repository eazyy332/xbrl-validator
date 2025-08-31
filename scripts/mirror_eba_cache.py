import os
import sys
import zipfile
import shutil
from pathlib import Path

ROOT = Path('assets/work/eba-package')
CACHE = Path('assets/cache/http')
CACHE.mkdir(parents=True, exist_ok=True)

HOST_MARKERS = [
	'www.eba.europa.eu/',
	'www.eurofiling.info/',
	'www.xbrl.org/',
]

PRIORITY_PREFIXES = [
	'eu/fr/xbrl/crr/fws/corep/cir-680-2014/2019-04-30/',
	'eu/fr/xbrl/dict/met/',
	'eu/fr/xbrl/dict/dim/',
	'eu/fr/xbrl/dict/dom/',
	'eu/fr/xbrl/func/',
	'eu/fr/xbrl/val/',
	'eu/fr/xbrl/ext/',
]

def should_copy(rel: str) -> bool:
	# Prioritize key subtrees; allow any www.* by default to reduce IOerrors
	return True


def main() -> int:
	if not ROOT.exists():
		print(f'zip root not found: {ROOT}', file=sys.stderr)
		return 1

	zips = [ROOT / n for n in os.listdir(ROOT) if n.lower().endswith('.zip')]
	copied = 0
	skipped = 0
	scanned = 0
	for zp in zips:
		try:
			with zipfile.ZipFile(zp) as z:
				for name in z.namelist():
					scanned += 1
					if name.endswith('/'):
						continue
					rel = None
					for marker in HOST_MARKERS:
						if marker in name:
							rel = name.split(marker, 1)[1]
							host = marker.rstrip('/')
							break
					if rel is None:
						continue
					if not should_copy(rel):
						continue
					# Preserve host directory under cache/http so Arelle offline resolver finds it
					out_path = CACHE / host / rel
					out_path.parent.mkdir(parents=True, exist_ok=True)
					try:
						with z.open(name) as src, open(out_path, 'wb') as dst:
							shutil.copyfileobj(src, dst)
						copied += 1
					except Exception:
						skipped += 1
		except zipfile.BadZipFile:
			skipped += 1
	print(f'zips={len(zips)} scanned={scanned} copied={copied} skipped={skipped}')
	return 0


if __name__ == '__main__':
	sys.exit(main())
