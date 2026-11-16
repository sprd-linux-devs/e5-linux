"""Stage E5 torch code in image-owned paths used by both full and diff updates."""
from pathlib import Path

HERE = Path(__file__).resolve().parent


def stage(root):
    root = Path(root)
    marker = root / 'etc/e5/device-profile'
    if not marker.is_file() or marker.read_text().strip() != 'e5':
        return
    app = root / 'usr/share/e5-infoscreen/builtin-apps/torch'
    app.mkdir(parents=True, exist_ok=True)
    for source in (HERE / 'infoscreen-torch').iterdir():
        if source.is_file():
            target = app / source.name
            target.write_bytes(source.read_bytes().replace(b'\r\n', b'\n'))
            target.chmod(0o644)
    for source, destination, mode in (
        ('torch-start', 'usr/libexec/e5-torch-start', 0o755),
        ('torch.modules', 'etc/modules.d/e5-torch', 0o644),
    ):
        target = root / destination
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((HERE / source).read_bytes().replace(b'\r\n', b'\n'))
        target.chmod(mode)
    web = root / 'usr/share/e5-infoscreen/www/plugins/torch'
    web.parent.mkdir(parents=True, exist_ok=True)
    if web.is_symlink():
        web.unlink()
    elif web.exists():
        raise ValueError('Torch web entry occupied; use a clean owned staging root')
    web.symlink_to('../../builtin-apps/torch')
