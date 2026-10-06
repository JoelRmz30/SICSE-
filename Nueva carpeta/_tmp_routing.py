import sys, os
sys.path.insert(0, '.')
lines = []
try:
    from app import app as application
    application.config['TESTING'] = True
    application.config['SERVER_NAME'] = None
    client = application.test_client()

    def test_get(url, expected_statuses):
        try:
            r = client.get(url, follow_redirects=False)
            lines.append(f'GET {url} -> status={r.status_code}')
            if r.status_code not in expected_statuses:
                lines.append(f'  -> ESPERADO: {expected_statuses}')
        except Exception as e:
            lines.append(f'GET {url} EXCEPTION: {e}')

    test_get('/login', {200})
    test_get('/', {302, 200})
    test_get('/dashboard', {302})
    test_get('/entrada', {302})
    test_get('/salida', {302})
    test_get('/reproceso', {302})
    test_get('/historial', {302})
    test_get('/embarques', {302})
    test_get('/embarques/nuevo', {302})
    test_get('/embarques/exportar', {302})
    test_get('/embarques/cuadre', {302})
    test_get('/embarques/1', {302})
    test_get('/embarques/1/editar', {302})
    test_get('/api/embarques/lotes', {302})
    test_get('/admin/catalogos/productos_embarque', {302})
except Exception as e:
    lines.append(f'TEST FATAL: {e}')
    import traceback
    lines.append(traceback.format_exc())

with open('c:/xampp/htdocs/DUAL/sistema_gestor de silos/_routing_test.txt', 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines))
