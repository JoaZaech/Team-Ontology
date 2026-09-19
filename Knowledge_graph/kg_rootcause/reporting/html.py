"""Self-contained HTML export; no Codex plugin or runtime paths required."""
from html import escape
from pathlib import Path


def standalone_document(fragment, title='Precomputed knowledge graph'):
    styles = (Path(__file__).resolve().parents[1] / 'frontend_contract/assets/standalone.css').read_text()
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>{escape(title)}</title><style>{styles}</style></head>'
        f'<body><main>{fragment}</main></body></html>\n'
    )
