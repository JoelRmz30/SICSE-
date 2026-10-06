"""
Script temporal de integración para probar el submit real de embarques.
1. Asegura catálogos mínimos de prueba.
2. Crea 3 embarques (pipa, caja, tambor) con datos válidos.
3. Prueba validaciones negativas (cita inválida, sello duplicado, tiempos desorden).
Todo vía test_client de Flask (no servidor HTTP real).
"""
import sys
import random
from app import app, db
from app import (ProductoEmbarque, Cliente, Transportista, Operador,
                 UnidadTransporte, Lavadero, Facilitador,
                 Embarque, EmbarqueSello, EmbarqueLote, Lote, InventarioSilo)


def check(label, cond, extra=''):
    status = 'OK' if cond else 'FAIL'
    print(f'  [{status}] {label} {extra}')
    return 0 if cond else 1


fails = 0

# ===== Datos base =====
SUFIJO = f'{random.randint(100, 999):03d}'  # sufijo aleatorio para evitar unique colisiones
CITA_PIPA = f'2101-CITA-{900000 + int(SUFIJO)}'
CITA_CAJA = f'2101-CITA-{910000 + int(SUFIJO)}'
CITA_TAMBOR = f'2101-CITA-{920000 + int(SUFIJO)}'
ORDEN = '2101-OT000001'
SELLO_PRUEBA = f'SLLO{SUFIJO}'

with app.app_context():
    # 1. Crear / obtener catálogos de prueba
    def get_or_create(cls, defaults, **filters):
        inst = cls.query.filter_by(**filters).first()
        if not inst:
            inst = cls(**{**filters, **defaults})
            db.session.add(inst)
            db.session.flush()
        return inst

    producto = get_or_create(ProductoEmbarque,
        {'descripcion': 'CONCENTRADO TEMPLE NARANJA',
         'variedad': 'VALENCIA', 'tipo': 'concentrado', 'unidad_medida': 'KG'},
        item='PT1701P004T')

    cliente = get_or_create(Cliente,
        {'codigo': f'CP{SUFIJO}',
         'nombre_cliente': 'CLIENTE PRUEBA EMBARQUES',
         'direccion': 'CARR 100 KM 10',
         'pais': 'MEXICO',
         'contacto': 'JUAN PEREZ',
         'email': f'cliente{SUFIJO}@test.com',
         'telefono': '8110000000'},
        codigo=f'CP{SUFIJO}')

    transportista = get_or_create(Transportista, {},
        nombre=f'TRANSPORTISTA PRUEBA {SUFIJO}')

    operador = get_or_create(Operador,
        {'id_transportista': transportista.id_transportista},
        nombre=f'OPERADOR PRUEBA {SUFIJO}')

    tractor = get_or_create(UnidadTransporte, {'tipo': 'tractor'},
        placa=f'TRAC{SUFIJO}')
    remolque = get_or_create(UnidadTransporte, {'tipo': 'remolque'},
        placa=f'REM{SUFIJO}')

    lavadero = get_or_create(Lavadero, {},
        nombre=f'LAVADERO PRUEBA {SUFIJO}')

    facilitador = get_or_create(Facilitador, {},
        nombre=f'FACILITADOR PRUEBA {SUFIJO}')

    # Buscar un lote existente con codigo_lote que cumpla regex y con inventario
    lote = (Lote.query
            .join(InventarioSilo, InventarioSilo.id_lote == Lote.id_lote)
            .filter(InventarioSilo.galones > 0)
            .order_by(Lote.id_lote.desc())
            .first())
    if not lote:
        print('  [!] No se encontró lote con inventario. Creando lote ficticio para pruebas...')
        # Crear lote mínimo (con estado_producto existente)
        from app import EstadoProducto
        ep = EstadoProducto.query.first()
        if not ep:
            ep = EstadoProducto(nombre_estado='PENDIENTE', descripcion='TEMP')
            db.session.add(ep); db.session.flush()
        lote = Lote(
            codigo_lote=f'005-20260115-{SUFIJO}01',
            id_estado=ep.id_estado,
            fecha_lote=__import__('datetime').datetime(2026, 1, 15).date(),
            brix=65.5, relacion=5.5, ph=3.5, acidez=1.2, pulpa=12,
            observaciones='LOTE DE PRUEBA INTEGRACION'
        )
        db.session.add(lote); db.session.flush()
        # inventario ficticio
        from app import Silo
        silo = Silo.query.first()
        if not silo:
            silo = Silo(nombre_silo='SILO_TMP', capacidad_galones=100000)
            db.session.add(silo); db.session.flush()
        inv = InventarioSilo(id_silo=silo.id_silo, id_lote=lote.id_lote, galones=50000.0)
        db.session.add(inv); db.session.flush()

    print(f'\n  [INFO] Catálogos OK: producto={producto.id_producto} cliente={cliente.id_cliente} '
          f'lote={lote.codigo_lote}')
    db.session.commit()


# ===== Test: crear 3 embarques con datos válidos =====
def construir_form_comun(cita, tipo_unidad, turno=1):
    from datetime import datetime, timedelta
    hoy = datetime.now()
    llegada = (hoy - timedelta(hours=6)).strftime('%Y-%m-%dT%H:%M')
    entrada = (hoy - timedelta(hours=5)).strftime('%Y-%m-%dT%H:%M')
    pesado_i = (hoy - timedelta(hours=4)).strftime('%Y-%m-%dT%H:%M')
    pesado_s = (hoy - timedelta(hours=2)).strftime('%Y-%m-%dT%H:%M')
    docu = (hoy - timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M')
    salida = hoy.strftime('%Y-%m-%dT%H:%M')
    return {
        'fecha_embarque': hoy.strftime('%Y-%m-%d'),
        'estatus': 'cargado',
        'num_cita': cita,
        'num_orden': ORDEN,
        'ticket': f'ALA9{SUFIJO}{cita[-2:]}',
        'packing': f'2101-{990000 + int(SUFIJO) + int(cita[-3:]) % 1000:06d}'[:10],
        'turno': str(turno),
        'id_producto': str(producto.id_producto),
        'id_cliente': str(cliente.id_cliente),
        'tipo_unidad': tipo_unidad,
        'id_transportista': str(transportista.id_transportista),
        'id_operador': str(operador.id_operador),
        'id_tractor': str(tractor.id_unidad),
        'id_remolque': str(remolque.id_unidad),
        'temperatura_c': '2.5',
        'id_facilitador': str(facilitador.id_facilitador),
        'observaciones': 'PRUEBA INTEGRACIÓN',
        't_llegada': llegada, 't_entrada': entrada,
        't_pesado_inicial': pesado_i, 't_pesaje_salida': pesado_s,
        't_documentacion': docu, 't_salida': salida,
        'lotes_ids[]': [str(lote.id_lote)],
        'lotes_cantidades[]': ['250.5'],
    }


print('\n=== PRUEBAS DE ALTA - 3 TIPOS DE UNIDAD ===')
with app.test_client() as c:
    c.post('/login', data={'usuario': 'admin', 'password': 'admin123'})

    # Embarque 1: PIPA JUMBO
    form = construir_form_comun(CITA_PIPA, 'pipa_jumbo')
    form['id_lavadero'] = str(lavadero.id_lavadero)
    form['sellos_lavado'] = f'{SELLO_PRUEBA}-1,{SELLO_PRUEBA}-2'
    form['sello_valvula'] = f'{SELLO_PRUEBA}-V'
    form['sellos_escotilla'] = f'{SELLO_PRUEBA}-E1 {SELLO_PRUEBA}-E2'
    r = c.post('/embarques/nuevo', data=form, follow_redirects=False)
    ok = r.status_code in (200, 302) and r.status_code != 500
    # Verificar que no haya flash danger (de error)
    with c.session_transaction() as sess:
        flashed = sess.get('_flashes', [])
        has_danger = any(cat == 'danger' for cat, msg in flashed)
    fails += check('Alta PIPA JUMBO -> OK (sin danger flash)',
                   ok and not has_danger,
                   f'status={r.status_code} danger={has_danger}')

    # Embarque 2: CAJA REFRIGERADA
    form = construir_form_comun(CITA_CAJA, 'caja_refrigerada')
    form['sellos_puerta_trasera'] = f'{SELLO_PRUEBA}-PT1,{SELLO_PRUEBA}-PT2'
    r = c.post('/embarques/nuevo', data=form, follow_redirects=False)
    with c.session_transaction() as sess:
        flashed = sess.get('_flashes', [])
        has_danger = any(cat == 'danger' for cat, msg in flashed)
    fails += check('Alta CAJA REFRIGERADA -> OK',
                   r.status_code != 500 and not has_danger,
                   f'status={r.status_code} danger={has_danger}')

    # Embarque 3: TAMBORES
    form = construir_form_comun(CITA_TAMBOR, 'tambores')
    form['check_list'] = 'on'
    form['lote_tambor'] = f'LTT{SUFIJO}01'
    r = c.post('/embarques/nuevo', data=form, follow_redirects=False)
    with c.session_transaction() as sess:
        flashed = sess.get('_flashes', [])
        has_danger = any(cat == 'danger' for cat, msg in flashed)
    fails += check('Alta TAMBORES -> OK',
                   r.status_code != 500 and not has_danger,
                   f'status={r.status_code} danger={has_danger}')


# ===== Verificar persistencia: embarques + embarque_lotes =====
with app.app_context():
    for cita in [CITA_PIPA, CITA_CAJA, CITA_TAMBOR]:
        emb = Embarque.query.filter_by(num_cita=cita).first()
        if emb:
            n_lotes = len(emb.lotes)
            suma = emb.cantidad_total
            fails += check(f'Embarque {cita}: lotes={n_lotes} total={suma}',
                           emb is not None and n_lotes >= 1 and float(suma) > 0)
            # Verificar auditoría
            fails += check(f'  id_capturista={emb.id_capturista} actualizado_por={emb.actualizado_por}',
                           emb.id_capturista is not None)


# ===== PRUEBAS NEGATIVAS =====
print('\n=== PRUEBAS NEGATIVAS - VALIDACIONES SERVIDOR ===')
with app.test_client() as c:
    c.post('/login', data={'usuario': 'admin', 'password': 'admin123'})

    # 1. Cita con formato inválido
    form = construir_form_comun('CITA-MAL', 'caja_seca')
    r = c.post('/embarques/nuevo', data=form, follow_redirects=False)
    with c.session_transaction() as sess:
        flashed = sess.get('_flashes', [])
        has_danger = any(cat == 'danger' for cat, msg in flashed)
    fails += check('Cita inválida -> flash danger (sin error 500)',
                   r.status_code != 500 and has_danger,
                   f'status={r.status_code} danger={has_danger}')

    # 2. Cita duplicada (usar CITA_PIPA que ya se guardó)
    form = construir_form_comun(CITA_PIPA, 'caja_seca')
    r = c.post('/embarques/nuevo', data=form, follow_redirects=False)
    with c.session_transaction() as sess:
        flashed = sess.get('_flashes', [])
        msgs = [msg for cat, msg in flashed if cat == 'danger']
        has_unicidad = any('cita ya está registrado' in m for m in msgs)
    fails += check('Cita duplicada -> mensaje de unicidad (sin 500)',
                   r.status_code != 500 and has_unicidad,
                   f'status={r.status_code}')

    # 3. Tiempos desordenados: llegada > salida
    form = construir_form_comun(f'2101-CITA-{950000 + int(SUFIJO)}', 'caja_seca')
    from datetime import datetime, timedelta
    hoy = datetime.now()
    form['t_llegada'] = (hoy + timedelta(hours=2)).strftime('%Y-%m-%dT%H:%M')
    form['t_salida'] = hoy.strftime('%Y-%m-%dT%H:%M')
    r = c.post('/embarques/nuevo', data=form, follow_redirects=False)
    with c.session_transaction() as sess:
        flashed = sess.get('_flashes', [])
        msgs = [msg for cat, msg in flashed if cat == 'danger']
        has_tiempo = any('no puede ser posterior' in m for m in msgs)
    fails += check('Tiempos desordenados -> flash error orden (sin 500)',
                   r.status_code != 500 and has_tiempo,
                   f'status={r.status_code}')

    # 4. Sello duplicado (usar sello_valvula SELLO_PRUEBA-V que ya se usó en pipa)
    form = construir_form_comun(f'2101-CITA-{960000 + int(SUFIJO)}', 'pipa_chica')
    form['id_lavadero'] = str(lavadero.id_lavadero)
    form['sello_valvula'] = f'{SELLO_PRUEBA}-V'  # ya usado en pipa jumbo
    r = c.post('/embarques/nuevo', data=form, follow_redirects=False)
    with c.session_transaction() as sess:
        flashed = sess.get('_flashes', [])
        msgs = [msg for cat, msg in flashed if cat == 'danger']
        has_sello = any('sello' in m.lower() and 'ya existe' in m.lower() for m in msgs)
    fails += check('Sello duplicado -> flash unicidad sello (sin 500)',
                   r.status_code != 500 and has_sello,
                   f'status={r.status_code}')

    # 5. Cero lotes (borrar listas)
    form = construir_form_comun(f'2101-CITA-{970000 + int(SUFIJO)}', 'caja_seca')
    form['lotes_ids[]'] = []
    form['lotes_cantidades[]'] = []
    r = c.post('/embarques/nuevo', data=form, follow_redirects=False)
    with c.session_transaction() as sess:
        flashed = sess.get('_flashes', [])
        msgs = [msg for cat, msg in flashed if cat == 'danger']
        has_lotes = any('agregar al menos un lote' in m for m in msgs)
    fails += check('Cero lotes -> flash requerir lotes (sin 500)',
                   r.status_code != 500 and has_lotes,
                   f'status={r.status_code}')

    # 6. Lote repetido en un mismo embarque
    form = construir_form_comun(f'2101-CITA-{980000 + int(SUFIJO)}', 'caja_seca')
    form['lotes_ids[]'] = [str(lote.id_lote), str(lote.id_lote)]
    form['lotes_cantidades[]'] = ['100', '150']
    r = c.post('/embarques/nuevo', data=form, follow_redirects=False)
    with c.session_transaction() as sess:
        flashed = sess.get('_flashes', [])
        msgs = [msg for cat, msg in flashed if cat == 'danger']
        has_rep = any('repetido' in m for m in msgs)
    fails += check('Lote duplicado en mismo embarque -> flash lote repetido (sin 500)',
                   r.status_code != 500 and has_rep,
                   f'status={r.status_code}')


# ===== PRUEBA: Dos lotes en mismo embarque (suma correcta) =====
print('\n=== PRUEBA EMBARQUE CON 2 LOTES ===')
with app.app_context():
    # Crear segundo lote de prueba
    from app import EstadoProducto
    ep = EstadoProducto.query.first()
    lote2 = Lote(
        codigo_lote=f'005-20260210-{SUFIJO}02',
        id_estado=ep.id_estado,
        fecha_lote=__import__('datetime').datetime(2026, 2, 10).date(),
        brix=64.0, relacion=5.2, ph=3.6, acidez=1.1, pulpa=11,
        observaciones='LOTE 2 PRUEBA'
    )
    db.session.add(lote2); db.session.flush()
    from app import Silo
    silo = Silo.query.first()
    db.session.add(InventarioSilo(id_silo=silo.id_silo, id_lote=lote2.id_lote, galones=30000))
    db.session.commit()
    lote2_id = lote2.id_lote

with app.test_client() as c:
    c.post('/login', data={'usuario': 'admin', 'password': 'admin123'})
    form = construir_form_comun(f'2101-CITA-{990000 + int(SUFIJO)}', 'trailer')
    form['lotes_ids[]'] = [str(lote.id_lote), str(lote2_id)]
    form['lotes_cantidades[]'] = ['100.5', '200.5']  # total = 301.0
    r = c.post('/embarques/nuevo', data=form, follow_redirects=False)
    with c.session_transaction() as sess:
        flashed = sess.get('_flashes', [])
        has_danger = any(cat == 'danger' for cat, msg in flashed)

with app.app_context():
    emb = Embarque.query.filter_by(num_cita=f'2101-CITA-{990000 + int(SUFIJO)}').first()
    if emb:
        n = len(emb.lotes)
        total = emb.cantidad_total
        ok_2l = (n == 2 and abs(float(total) - 301.0) < 0.001)
        fails += check(f'Embarque 2 lotes: {n} filas, suma={total} (esperado 301.0)',
                       ok_2l,
                       f'status_submit={r.status_code} danger={has_danger}')
    else:
        fails += check('Embarque 2 lotes: NO SE ENCONTRÓ', False)


print(f'\n=============================================')
print(f'Total FALLOS: {fails}')
sys.exit(0 if fails == 0 else 1)
