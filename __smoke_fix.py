import sys
sys.path.insert(0, '.')
from app import app
URLS = [
    ('GET', '/admin/catalogos/clientes'),
    ('GET', '/embarques/empaque/movimiento'),
    ('GET', '/embarques'),
]
with app.test_client() as client:
    for metodo, url in URLS:
        r = client.get(url, follow_redirects=False)
        print('{:4s} {:45s} {}'.format(metodo, url[:45], r.status_code))
print('OK')
