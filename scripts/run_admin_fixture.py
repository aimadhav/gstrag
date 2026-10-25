"""Disposable real-HTTP admin workflow with synthetic PDFs; no .env/provider calls.

Run this to demonstrate source review, snapshot preparation and answer review.
All accounts, PDFs and databases live in a new temporary directory, not the real corpus.
"""
import argparse
from pathlib import Path
import secrets
import tempfile
import textwrap

from docling_core.types.doc import DoclingDocument, DocItemLabel, ProvenanceItem, BoundingBox
from fastapi.staticfiles import StaticFiles
import uvicorn

from gst_rag.api import create_app
from gst_rag.auth import PASSWORDS, Settings
from gst_rag.ingestion import write_json
from gst_rag.notification_publication import Publications
from gst_rag.notification_sync import digest, run
from gst_rag.store import Store
from run_ui_fixture import FIXTURE_PASSWORD, FixtureDrafting, FixtureRetrieval

TEXTS = ['Notification No. 8/2025-Central Tax (Rate)', '1st January, 2025', '2nd January, 2025',
         'Synthetic operative clause: all illustrative conditions and exceptions are retained. Not GST advice.']


class FixtureTokenizer:
    def encode(self, text, **kwargs): return text.split()


def synthetic_pdf(lines):
    """One valid text-only PDF page, exclusively for the disposable UI fixture."""
    content = 'BT /F1 12 Tf 45 780 Td 18 TL\n'
    for line in [part for text in lines for part in textwrap.wrap(text, width=78)]:
        escaped = line.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
        content += '(' + escaped + ') Tj T*\n'
    content += 'ET'
    stream = content.encode('ascii')
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>', b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
               b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
               b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
               b'<< /Length ' + str(len(stream)).encode() + b' >>\nstream\n' + stream + b'\nendstream']
    body, offsets = b'%PDF-1.4\n', [0]
    for index, obj in enumerate(objects, 1):
        offsets.append(len(body)); body += f'{index} 0 obj\n'.encode() + obj + b'\nendobj\n'
    start = len(body)
    body += f'xref\n0 {len(offsets)}\n0000000000 65535 f \n'.encode()
    body += b''.join(f'{offset:010} 00000 n \n'.encode() for offset in offsets[1:])
    return body + f'trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n'.encode()


class FixtureFeed:
    def get(self, url, kind):
        if kind == 'pdf': return synthetic_pdf(['SYNTHETIC ADMIN UI FIXTURE - NOT A GOVERNMENT PDF', *TEXTS]), url
        return ('<table><tr><th>Notification No. &amp; Date of Issue</th><th>English</th><th>Hindi</th><th>Subject</th></tr>'
                '<tr><td>08/2025-Central Tax (Rate)</td><td><a href="/sites/default/files/synthetic.pdf">View</a></td>'
                '<td></td><td>Synthetic fixture only</td></tr></table>').encode(), url


class AdminFixtureRetrieval(FixtureRetrieval):
    def retrieve(self, *args):
        packet = super().retrieve(*args)
        packet['citations'][0].update(document_id='icai_book', source_refs=['#/texts/0'],
                                      excerpt='Synthetic icai_book evidence. No tax advice.')
        return packet


def fixture_parser(pdf, directory, metadata):
    directory.mkdir(parents=True, exist_ok=True)
    document = DoclingDocument(name='Synthetic admin source review')
    for text in TEXTS:
        document.add_text(label=DocItemLabel.TEXT, text=text, prov=ProvenanceItem(page_no=1,
                          charspan=(0, len(text)), bbox=BoundingBox(l=0, r=100, t=100, b=90, coord_origin='BOTTOMLEFT')))
    document.save_as_json(directory / 'docling.json')
    sha = digest(pdf.read_bytes()); kind = metadata.get('source_type', 'notification'); document_id = kind + '-' + sha[:16]
    write_json(directory / 'manifest.json', {'document_id': document_id, 'sha256': sha,
               'source_type': kind, 'plan_required': 'pro' if kind == 'firm_book' else 'plus', 'page_count': 1})
    return {'schema': 'notification-staging-v1', 'source_sha256': sha, 'document_id': document_id,
            'candidate': metadata, 'page_count': 1, 'docling_sha256': digest((directory / 'docling.json').read_bytes()),
            'review_status': 'pending_source_metadata_review', 'eligible_for_retrieval': False,
            'warnings': ['Synthetic parser for the admin HTTP fixture; not a real Docling conversion.'],
            'records': [{'chunk_id': document_id + ':1', 'document_id': document_id, 'source_type': kind,
                         'plan_required': 'pro' if kind == 'firm_book' else 'plus', 'text': TEXTS[3], 'embedding_text': TEXTS[3],
                         'headings': [], 'source_refs': ['#/texts/3'], 'token_count': 25, 'pages': [1], 'eligible_for_retrieval': False}]}


def main():
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--port', type=int, default=8011)
    parser.add_argument('--real-upload-parser', action='store_true', help='Use real local Docling only for browser uploads; seeded notifications remain synthetic')
    args = parser.parse_args(); project = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix='gst-admin-fixture-') as temporary:
        root = Path(temporary); sources, records = [], []
        upload_sample = root / 'fixture-upload-book.pdf'
        upload_sample.write_bytes(synthetic_pdf(['SYNTHETIC UPLOAD WORKFLOW TEST - NOT GST ADVICE', *TEXTS]))
        for kind, plan in [('icai_book', 'plus'), ('firm_book', 'pro')]:
            path = root / 'data/sources' / (kind + '.pdf'); path.parent.mkdir(parents=True, exist_ok=True)
            text = 'Synthetic ' + kind + ' evidence. No tax advice.'; path.write_bytes(synthetic_pdf([text]))
            sources.append({'document_id': kind, 'source_type': kind, 'name': 'Synthetic ' + kind,
                            'sha256': digest(path.read_bytes()), 'pdf_path': path.relative_to(root).as_posix(), 'page_count': 1})
            records.append({'chunk_id': kind + ':1', 'document_id': kind, 'source_type': kind, 'plan_required': plan,
                            'text': text, 'embedding_text': text, 'source_refs': ['#/texts/0'], 'pages': [1], 'headings': []})
        write_json(root / 'data/app/corpus.json', {'version': 'admin-fixture', 'sources': sources, 'records': records, 'links': []})
        def import_fixture(): return run(root / 'data/app/notification_sync', client=FixtureFeed(), sources=['cgst_rate'], parse=True, parser=fixture_parser)
        import_fixture()
        settings = Settings(root, root / 'fixture.sqlite3', secrets.token_urlsafe(48), generation='off',
                            notification_sync_enabled=True, notification_sync_secret=secrets.token_urlsafe(48), upload_worker_enabled=True)
        store = Store(settings.db_path); password = PASSWORDS.hash(FIXTURE_PASSWORD)
        admin = store.create_user('ui-admin', password, 'pro', 'admin'); user = store.create_user('ui-user', password, 'plus')
        app = create_app(settings, store, lambda: AdminFixtureRetrieval(), FixtureDrafting(),
                         Publications(root, tokenizer_factory=FixtureTokenizer), sync_runner=import_fixture,
                         upload_parser=None if args.real_upload_parser else fixture_parser)
        store.enqueue(user['id'], 'Which facts should a reviewer inspect?', '2023-03-01', ['other_gst'])
        app.mount('/app', StaticFiles(directory=project / 'frontend/dist', html=True))
        print('SYNTHETIC FIXTURE ONLY: ui-admin / ui-user; password: ' + FIXTURE_PASSWORD, flush=True)
        print('Temporary root (NOT real corpus): ' + str(root), flush=True)
        print('Synthetic upload test file: ' + str(upload_sample), flush=True)
        print(f'Open http://localhost:{args.port}/app/ . No hosted provider calls or real-source approvals; real-parser mode may download local model assets.', flush=True)
        uvicorn.run(app, host='127.0.0.1', port=args.port, access_log=False, log_level='warning')


if __name__ == '__main__': main()
