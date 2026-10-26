"""
Pruebas del lote de mezcla (INVOCA) en embarques:
  - Tambores: se respeta el silo/lote, NO se crea lote de mezcla.
  - Pipa (jumbo/chica): se captura el lote de INVOCA y sus componentes.
  - Alertas cuando falta el lote de mezcla en pipa.
  - Cancelación con reversión de inventario y borrado de la mezcla.
"""
from datetime import date, datetime
from decimal import Decimal

from app import (
    db,
    Lote,
    LoteComponente,
    InventarioSilo,
    Embarque,
    EmbarqueTiempos,
    calcular_alertas,
)

MES_MEZCLA = '005-20250102-000999'


def datos_embarque(**extra):
    """Datos mínimos válidos del formulario de embarque, sobreescribibles."""
    datos = {
        'fecha_embarque': date.today().isoformat(),
        'estatus': 'cargado',
        'num_cita': '2101-CITA-000001',
        'num_orden': '2101-OT000001',
        'turno': '1',
        'tipo_unidad': 'pipa_chica',
    }
    datos.update(extra)
    return datos


def _crear_embarque_nuevo(post, client, datos):
    """Envía el formulario de alta de embarque y devuelve la respuesta."""
    return post(client, '/embarques/nuevo', datos)


# ----------------------------------------------------------------------
# Tambores: comportamiento actual (sin lote de mezcla)
# ----------------------------------------------------------------------

def test_embarque_tambores_no_crea_lote_de_mezcla(app, ids, admin_client, post, crear_lote):
    """Un embarque de tambores descuenta inventario pero no genera lote de mezcla."""
    lote = crear_lote('005-20250101-000100', 5000, ids['silo_a'])

    resp = _crear_embarque_nuevo(post, admin_client, datos_embarque(
        num_cita='2101-CITA-000101',
        num_orden='2101-OT000101',
        tipo_unidad='tambores',
        **{'lotes_ids[]': [lote.id_lote], 'lotes_cantidades[]': ['500']}))

    assert resp.status_code == 302
    emb = Embarque.query.filter_by(num_cita='2101-CITA-000101').first()
    assert emb is not None
    assert emb.tipo_unidad == 'tambores'

    # No se crea lote de mezcla ni componentes.
    assert LoteComponente.query.count() == 0
    assert Lote.query.filter_by(es_mezcla=True).count() == 0

    # El inventario del lote se descontó normalmente (respetando el silo).
    inv = InventarioSilo.query.filter_by(id_lote=lote.id_lote).first()
    assert Decimal(inv.galones) == Decimal('4500.00')


# ----------------------------------------------------------------------
# Pipa: lote de mezcla obligatorio capturado de INVOCA
# ----------------------------------------------------------------------

def test_embarque_pipa_crea_lote_de_mezcla_y_componentes(app, ids, admin_client, post, crear_lote):
    """La pipa crea el lote de mezcla (es_mezcla, INVOCA) con una fila por lote de origen."""
    lote_a = crear_lote('005-20250101-000201', 3000, ids['silo_a'], posicion=1)
    lote_b = crear_lote('005-20250101-000202', 3000, ids['silo_a'], posicion=2)

    resp = _crear_embarque_nuevo(post, admin_client, datos_embarque(
        num_cita='2101-CITA-000201',
        num_orden='2101-OT000201',
        tipo_unidad='pipa_chica',
        lote_mezcla=MES_MEZCLA,
        **{'lotes_ids[]': [lote_a.id_lote, lote_b.id_lote],
           'lotes_cantidades[]': ['1000', '500']}))

    assert resp.status_code == 302
    emb = Embarque.query.filter_by(num_cita='2101-CITA-000201').first()
    assert emb is not None

    mezcla = emb.lote_mezcla
    assert mezcla is not None
    assert mezcla.codigo_lote == MES_MEZCLA
    assert mezcla.es_mezcla is True
    assert mezcla.asignado_por == 'INVOCA'
    # °Brix ponderado por galones (ambos lotes tienen 11.50).
    assert Decimal(mezcla.brix) == Decimal('11.50')

    componentes = emb.componentes_mezcla
    assert len(componentes) == 2
    suma = sum((Decimal(c.galones) for c in componentes), Decimal('0'))
    assert suma == Decimal('1500.00')
    assert {c.id_lote_origen for c in componentes} == {lote_a.id_lote, lote_b.id_lote}


def test_embarque_pipa_sin_lote_de_mezcla_genera_alerta(app, ids, admin_client, post, crear_lote):
    """Sin lote de mezcla el embarque se guarda pero se levanta la alerta correspondiente."""
    lote = crear_lote('005-20250101-000301', 2000, ids['silo_a'])

    _crear_embarque_nuevo(post, admin_client, datos_embarque(
        num_cita='2101-CITA-000301',
        num_orden='2101-OT000301',
        tipo_unidad='pipa_jumbo',
        **{'lotes_ids[]': [lote.id_lote], 'lotes_cantidades[]': ['300']}))

    emb = Embarque.query.filter_by(num_cita='2101-CITA-000301').first()
    assert emb is not None
    assert emb.lote_mezcla is None

    # calcular_alertas() usa url_for, por lo que requiere contexto de petición.
    with app.test_request_context():
        claves = {a['clave_unica'] for a in calcular_alertas()}
    assert f'embarque:{emb.id_embarque}:pipa_sin_mezcla' in claves


def test_embarque_isotanque_no_genera_alerta_de_mezcla(app, ids, admin_client, post, crear_lote):
    """En isotanque el lote de mezcla es opcional: no se alerta si falta."""
    lote = crear_lote('005-20250101-000302', 2000, ids['silo_a'])

    _crear_embarque_nuevo(post, admin_client, datos_embarque(
        num_cita='2101-CITA-000302',
        num_orden='2101-OT000302',
        tipo_unidad='isotanque',
        **{'lotes_ids[]': [lote.id_lote], 'lotes_cantidades[]': ['300']}))

    emb = Embarque.query.filter_by(num_cita='2101-CITA-000302').first()
    assert emb is not None

    # calcular_alertas() usa url_for, por lo que requiere contexto de petición.
    with app.test_request_context():
        claves = {a['clave_unica'] for a in calcular_alertas()}
    assert f'embarque:{emb.id_embarque}:pipa_sin_mezcla' not in claves


def test_embarque_rechaza_orden_de_tiempos_incorrecto(app, ids, admin_client, post, crear_lote):
    """No debe guardarse si documentación queda después de la salida de planta."""
    lote = crear_lote('005-20250101-000303', 2000, ids['silo_a'])

    resp = _crear_embarque_nuevo(post, admin_client, datos_embarque(
        num_cita='2101-CITA-000303',
        num_orden='2101-OT000303',
        tipo_unidad='tambores',
        t_llegada='2026-10-16T09:07',
        t_entrada='2026-10-16T09:09',
        t_pesado_inicial='2026-10-16T09:13',
        t_pesaje_salida='2026-10-16T09:22',
        t_documentacion='2026-10-16T09:42',
        t_salida='2026-10-16T09:22',
        **{'lotes_ids[]': [lote.id_lote], 'lotes_cantidades[]': ['300']}))

    assert resp.status_code == 200
    assert Embarque.query.filter_by(num_cita='2101-CITA-000303').first() is None
    assert b'Orden de tiempos INCORRECTO' in resp.data


def test_alerta_embarque_con_orden_de_tiempos_incorrecto(app, ids, admin_client, post, crear_lote):
    """Los embarques viejos con tiempos mal capturados deben aparecer como alerta."""
    lote = crear_lote('005-20250101-000304', 2000, ids['silo_a'])

    resp = _crear_embarque_nuevo(post, admin_client, datos_embarque(
        num_cita='2101-CITA-000304',
        num_orden='2101-OT000304',
        tipo_unidad='tambores',
        t_llegada='2026-10-16T09:07',
        t_entrada='2026-10-16T09:09',
        t_pesado_inicial='2026-10-16T09:13',
        t_pesaje_salida='2026-10-16T09:22',
        t_documentacion='2026-10-16T09:23',
        t_salida='2026-10-16T09:42',
        **{'lotes_ids[]': [lote.id_lote], 'lotes_cantidades[]': ['300']}))
    assert resp.status_code == 302

    emb = Embarque.query.filter_by(num_cita='2101-CITA-000304').first()
    assert emb is not None

    # Simula un embarque legado/capturado antes de endurecer la regla.
    emb.tiempos.documentacion = datetime(2026, 10, 16, 9, 42)
    emb.tiempos.salida = datetime(2026, 10, 16, 9, 22)
    db.session.commit()

    ok, msg = EmbarqueTiempos.query.get(emb.id_embarque).tiempos_ordenados()
    assert ok is False
    assert msg.startswith('Orden de tiempos INCORRECTO:')

    with app.test_request_context():
        alertas = calcular_alertas()
    claves = {a['clave_unica'] for a in alertas}
    assert f'embarque:{emb.id_embarque}:orden_tiempos_incorrecto' in claves


def test_embarque_pipa_rechaza_lote_de_mezcla_con_formato_invalido(app, ids, admin_client, post, crear_lote):
    """Un código de mezcla que no cumple el formato rechaza el embarque completo."""
    lote = crear_lote('005-20250101-000401', 2000, ids['silo_a'])

    resp = _crear_embarque_nuevo(post, admin_client, datos_embarque(
        num_cita='2101-CITA-000401',
        num_orden='2101-OT000401',
        tipo_unidad='pipa_chica',
        lote_mezcla='MEZCLA-INVALIDA',
        **{'lotes_ids[]': [lote.id_lote], 'lotes_cantidades[]': ['500']}))

    assert resp.status_code == 200  # regresa al formulario con el error
    assert Embarque.query.filter_by(num_cita='2101-CITA-000401').first() is None
    # Nada se persiste: ni mezcla ni descuento de inventario.
    assert LoteComponente.query.count() == 0
    assert Lote.query.filter_by(es_mezcla=True).count() == 0
    assert Decimal(InventarioSilo.query.filter_by(id_lote=lote.id_lote).first().galones) == Decimal('2000.00')


def test_embarque_pipa_rechaza_mezcla_que_ya_es_lote_de_producto(app, ids, admin_client, post, crear_lote):
    """El código de mezcla asignado por INVOCA no puede reutilizar un lote con inventario."""
    origen = crear_lote('005-20250101-000501', 2000, ids['silo_a'])
    # Lote de producto ya existente con inventario en otro silo.
    crear_lote('005-20250102-000501', 100, ids['silo_b'])

    resp = _crear_embarque_nuevo(post, admin_client, datos_embarque(
        num_cita='2101-CITA-000501',
        num_orden='2101-OT000501',
        tipo_unidad='pipa_chica',
        lote_mezcla='005-20250102-000501',
        **{'lotes_ids[]': [origen.id_lote], 'lotes_cantidades[]': ['500']}))

    assert resp.status_code == 200
    assert Embarque.query.filter_by(num_cita='2101-CITA-000501').first() is None
    assert LoteComponente.query.count() == 0


def test_embarque_pipa_componentes_suman_lo_cargado(app, ids, admin_client, post, crear_lote):
    """La suma de galones de los componentes coincide con la cantidad cargada."""
    lote_a = crear_lote('005-20250101-000601', 3000, ids['silo_a'], posicion=1)
    lote_b = crear_lote('005-20250101-000602', 3000, ids['silo_a'], posicion=2)
    lote_c = crear_lote('005-20250101-000603', 3000, ids['silo_a'], posicion=3)

    _crear_embarque_nuevo(post, admin_client, datos_embarque(
        num_cita='2101-CITA-000601',
        num_orden='2101-OT000601',
        tipo_unidad='pipa_chica',
        lote_mezcla='005-20250102-000601',
        **{'lotes_ids[]': [lote_a.id_lote, lote_b.id_lote, lote_c.id_lote],
           'lotes_cantidades[]': ['250', '500', '750']}))

    emb = Embarque.query.filter_by(num_cita='2101-CITA-000601').first()
    total_componentes = sum((Decimal(c.galones) for c in emb.componentes_mezcla), Decimal('0'))
    assert total_componentes == emb.cantidad_total == Decimal('1500.00')


# ----------------------------------------------------------------------
# Cancelación con reversión
# ----------------------------------------------------------------------

def test_cancelar_embarque_revierte_inventario_y_elimina_mezcla(
        app, ids, admin_client, post, crear_lote):
    """Cancelar devuelve el inventario y borra el lote de mezcla y sus componentes."""
    lote = crear_lote('005-20250101-000701', 5000, ids['silo_a'])

    _crear_embarque_nuevo(post, admin_client, datos_embarque(
        num_cita='2101-CITA-000701',
        num_orden='2101-OT000701',
        tipo_unidad='pipa_chica',
        lote_mezcla='005-20250102-000701',
        **{'lotes_ids[]': [lote.id_lote], 'lotes_cantidades[]': ['1000']}))

    emb = Embarque.query.filter_by(num_cita='2101-CITA-000701').first()
    id_embarque = emb.id_embarque

    # Estado previo a la cancelación.
    assert LoteComponente.query.filter_by(id_embarque=id_embarque).count() == 1
    assert Decimal(InventarioSilo.query.filter_by(id_lote=lote.id_lote).first().galones) == Decimal('4000.00')

    resp = post(admin_client, f'/embarques/{id_embarque}/cancelar', {})
    assert resp.status_code == 302

    emb = Embarque.query.get(id_embarque)
    assert emb.estatus == 'cancelado'

    # Inventario restituido.
    assert Decimal(InventarioSilo.query.filter_by(id_lote=lote.id_lote).first().galones) == Decimal('5000.00')
    # Mezcla y componentes eliminados.
    assert LoteComponente.query.filter_by(id_embarque=id_embarque).count() == 0
    assert Lote.query.filter_by(codigo_lote='005-20250102-000701').first() is None
