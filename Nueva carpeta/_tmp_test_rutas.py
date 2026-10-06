"""
Script de prueba temporal para validar las rutas del módulo de embarques.
Usa el test_client de Flask (no arranca servidor HTTP real).
"""
import json
import sys
from app import app, db, Usuario  # noqa: F401 (importación usada implícitamente por el contexto)

client = app.test_client()

def check(label, cond, extra=''):
    """Mini helper de aserción soft."""
    status = 'OK' if cond else 'FAIL'
    print(f'  [{status}] {label} {extra}')
    return 0 if cond else 1

fails = 0

# === 1. RUTAS PÚBLICAS (sin sesión) ===
print('\n=== RUTAS SIN LOGIN (deben redirigir a login) ===')
for ruta in ['/', '/embarques', '/entrada', '/historial']:
    r = client.get(ruta, follow_redirects=False)
    fails += check(f'GET {ruta} -> 302', r.status_code == 302, f'status={r.status_code}')

# === 2. LOGIN ADMIN ===
print('\n=== LOGIN COMO ADMIN ===')
r = client.post('/login', data={'usuario': 'admin', 'password': 'admin123'}, follow_redirects=True)
fails += check('POST /login (admin) -> 200 dashboard', r.status_code == 200, f'status={r.status_code}')

# === 3. MÓDULO EMBARQUES ===
print('\n=== MODULO EMBARQUES (ADMIN) ===')

# 3.1 Listado
r = client.get('/embarques')
fails += check(f'GET /embarques -> 200 ({len(r.data)} bytes)', r.status_code == 200, '')

# 3.2 Nuevo embarque (formulario)
r = client.get('/embarques/nuevo')
if r.status_code != 200:
    print('  --- body (primeros 2500 chars) ---')
    print(r.data.decode('utf-8', errors='replace')[:2500])
fails += check(f'GET /embarques/nuevo -> 200 ({len(r.data)} bytes)', r.status_code == 200)

# 3.3 Detalle de embarque no existente -> 404
r = client.get('/embarques/999999')
fails += check('GET /embarques/999999 -> 404', r.status_code == 404, f'status={r.status_code}')

# 3.4 Editar embarque no existente -> 404
r = client.get('/embarques/999999/editar')
fails += check('GET /embarques/999999/editar -> 404', r.status_code == 404, f'status={r.status_code}')

# 3.5 Cancelar (POST) sin body redirige a detalle; lo hacemos con id 999999 para 404
r = client.post('/embarques/999999/cancelar', follow_redirects=False)
fails += check('POST /embarques/999999/cancelar -> 404', r.status_code == 404, f'status={r.status_code}')

# 3.6 Exportar Excel
r = client.get('/embarques/exportar')
ct = r.headers.get('Content-Type', '')
ok_exp = (r.status_code == 200
          and ('openxmlformats' in ct or 'spreadsheetml' in ct))
fails += check('GET /embarques/exportar -> Excel 200', ok_exp, f'status={r.status_code} ct={ct}')

# 3.7 Cuadre de galonaje
r = client.get('/embarques/cuadre')
fails += check(f'GET /embarques/cuadre -> 200 ({len(r.data)} bytes)', r.status_code == 200)

# 3.8 API lotes (JSON)
r = client.get('/api/embarques/lotes')
try:
    data = json.loads(r.data.decode('utf-8'))
    n = len(data.get('lotes', []))
    ok_api = r.status_code == 200 and 'lotes' in data
except Exception as e:
    ok_api = False
    n = f'err:{e}'
fails += check(f'GET /api/embarques/lotes -> JSON lotes ({n})', ok_api, f'status={r.status_code}')

# === 4. CATÁLOGOS DE ADMIN ===
print('\n=== CATALOGOS ADMIN ===')
for cat in ['productos_embarque', 'transportistas', 'operadores', 'unidades_transporte', 'lavaderos', 'facilitadores']:
    r = client.get(f'/admin/catalogos/{cat}')
    ok = r.status_code == 200
    if not ok:
        print(f'  --- ERROR catalogo {cat}, status={r.status_code}, preview body: ---')
        print(r.data.decode('utf-8', errors='replace')[:1500])
    fails += check(f'GET /admin/catalogos/{cat} -> 200', ok, f'status={r.status_code} tam={len(r.data)}')

# === 5. PERMISOS DE ROL INVITADO ===
print('\n=== PERMISOS INVITADO ===')
inv = app.test_client()
r = inv.post('/login', data={'usuario': 'invitado', 'password': 'invitado123'}, follow_redirects=False)
fails += check('Login invitado -> redirect', r.status_code == 302)

# Permitidos:
for ruta, metodo in [('/embarques', 'GET'), ('/embarques/exportar', 'GET'),
                     ('/embarques/cuadre', 'GET'), ('/api/embarques/lotes', 'GET')]:
    r = inv.get(ruta) if metodo == 'GET' else inv.post(ruta, data={})
    # 200 si permitido, 302 si redirect a login (no está logueado)
    ok_p = r.status_code == 200
    fails += check(f'Invitado {metodo} {ruta} -> 200 (lectura permitida)', ok_p, f'status={r.status_code}')

# No permitidos (redirect):
for ruta, metodo in [('/embarques/nuevo', 'GET'), ('/embarques/nuevo', 'POST'),
                     ('/embarques/1/editar', 'GET'), ('/embarques/1/cancelar', 'POST'),
                     ('/admin/catalogos/productos_embarque', 'GET')]:
    r = inv.get(ruta) if metodo == 'GET' else inv.post(ruta, data={})
    # Debe ser 302 redirect por acceso denegado
    ok_b = r.status_code == 302
    fails += check(f'Invitado {metodo} {ruta} -> 302 bloqueado', ok_b, f'status={r.status_code}')

# === 6. VALIDACIÓN DE FORMULARIO (SERVIDOR) ===
print('\n=== VALIDACION SERVIDOR - FORMULARIO INVALIDO ===')
# Enviar POST sin datos para provocar validaciones servidor (no error 500)
with app.test_client() as c:
    c.post('/login', data={'usuario': 'admin', 'password': 'admin123'})
    r = c.post('/embarques/nuevo', data={}, follow_redirects=False)
    # Flash de errores con redirect a la misma página (302) o repinta 200 con mensajes. Nunca 500.
    ok_val = r.status_code in (200, 302)
    fails += check(f'POST /embarques/nuevo vacio -> no 500 (status={r.status_code})', ok_val)

print('\n=============================================')
print(f'Total FALLOS: {fails}')
sys.exit(0 if fails == 0 else 1)
