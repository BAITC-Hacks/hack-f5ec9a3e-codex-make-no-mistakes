"""Local acceptance check against a fresh, isolated upload review database."""
import json
import os
import time
from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from replenishment.api.app import create_app

URL = 'postgresql+psycopg://replenishment:local_dev_only@127.0.0.1:55432/replenishment_upload_review_test'
os.environ['DATABASE_URL'] = URL
command.upgrade(Config('alembic.ini'), 'head')
engine = create_engine(URL)
report = []
with TestClient(create_app(engine)) as client:
    for filename in ('IEK (1).zip', 'Systeme electric (1).zip'):
        path = Path('C:/Users/User/Downloads') / filename
        started = time.monotonic()
        response = client.post('/api/v1/sources/upload', params={'filename': filename},
                               content=path.read_bytes(), headers={'content-type': 'application/octet-stream'})
        print(filename, response.status_code, flush=True)
        if response.status_code != 200:
            print(response.text, flush=True)
        response.raise_for_status()
        result = response.json()
        print(json.dumps(result, ensure_ascii=False), flush=True)
        assert all(row['status'] in ('imported', 'skipped') for row in result['results'])
        assert len(result['results']) == 6
        report.append({'archive': filename, 'seconds': round(time.monotonic() - started, 2), **result})
    for table in ('movements', 'monthly-sales', 'monthly-stock', 'shipment-lines', 'moq'):
        response = client.get('/api/v1/tables/' + table, params={'page_size': 1})
        response.raise_for_status()
        assert response.json()['total'] > 0
        print(table, response.json()['total'], flush=True)
    response = client.get('/api/v1/sources/export/moq.csv')
    response.raise_for_status()
    assert 'sku' in response.text.splitlines()[0]
    assert len(response.text.splitlines()) > 500
    replay = client.post('/api/v1/sources/upload', params={'filename': 'IEK (1).zip'},
                         content=Path('C:/Users/User/Downloads/IEK (1).zip').read_bytes())
    replay.raise_for_status()
    assert all(row['status'] == 'skipped' for row in replay.json()['results'])
    products = client.get('/api/v1/tables/catalog', params={'page_size': 1}).json()['items']
    print('catalog sample keys', list(products[0]), flush=True)
    movement = client.get('/api/v1/tables/movements', params={'page_size': 1}).json()['items'][0]
    prepared = client.post('/api/v1/planning/source-input', json={
        'product_ids': [movement['product_id']], 'planning_date': '2026-09-23',
        'warehouse': movement['warehouse_name'], 'normalizer_version': 'v1',
    })
    prepared.raise_for_status()
    assert prepared.json()['input']['rows']
    print('downstream source preparation passed', flush=True)
with engine.connect() as connection:
    counts = {table: connection.scalar(text('SELECT count(*) FROM ' + table)) for table in
              ('intake_workbooks', 'catalog_products', 'demand_movements', 'demand_monthly_sales',
               'inventory_monthly_stock', 'supply_shipment_lines')}
print(json.dumps(counts), flush=True)
Path('../artifacts/source-upload-verification.json').write_text(
    json.dumps({'archives': report, 'counts': counts}, ensure_ascii=False, indent=2), encoding='utf-8')
engine.dispose()
