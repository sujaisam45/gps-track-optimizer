"""Assemble the single-file web page: web/src/* -> docs/index.html (GitHub Pages).

    python web/export_samples.py   # only if the synthetic walks change
    python web/build.py
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
PROJ4 = ROOT / "vendor" / "proj4.js"   # proj4js 2.x, MIT licence, inlined so the page has no extra CDN

html = (SRC / "index.template.html").read_text(encoding="utf-8")
for marker, text in [
    ("/*LEAFLETCSS*/", (ROOT / "vendor" / "leaflet.css").read_text(encoding="utf-8")),
    ("/*CSS*/", (SRC / "styles.css").read_text(encoding="utf-8")),
    ("/*PROJ4*/", PROJ4.read_text(encoding="utf-8")),
    ("/*CORE*/", (SRC / "core.js").read_text(encoding="utf-8")),
    ("/*SAMPLES*/", (SRC / "samples.json").read_text(encoding="utf-8")),
    ("/*APP*/", (SRC / "app.js").read_text(encoding="utf-8")),
]:
    assert marker in html, marker
    html = html.replace(marker, text, 1)

out = ROOT.parent / "docs" / "index.html"
out.parent.mkdir(exist_ok=True)
out.write_text(html, encoding="utf-8")
print(f"wrote {out} ({out.stat().st_size / 1024:.0f} KB)")

# Second copy for a claude.ai Artifact preview: the host adds its own
# doctype/head/body, so keep only <title>, links, styles and the body content.
head = html.split("<head>", 1)[1].split("</head>", 1)[0]
head = "\n".join(l for l in head.splitlines() if 'charset' not in l and 'name="viewport"' not in l)
body = html.split("<body>", 1)[1].rsplit("</body>", 1)[0]
art = ROOT / "dist" / "gps-track-optimizer.html"
art.parent.mkdir(exist_ok=True)
art.write_text(head.strip() + "\n" + body, encoding="utf-8")
print(f"wrote {art}")
