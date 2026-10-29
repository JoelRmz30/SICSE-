"""
Pruebas del flujo TQPF -> Silo:
  - Entrada de un lote a un tanque de proceso (TQPF).
  - Traspaso total y parcial de un lote de TQPF hacia un silo.
  - Rechazos por capacidad, incompatibilidad de producto y galones insuficientes.
"""
from decimal import Decimal

from app import (
    db,
    Lote,
    InventarioSilo,
    InventarioTQPF,
    Movimiento,
)

COD_LOTE_A = '005-20250101-000001'
COD_LOTE_B = '005-20250101-000002'


# ----------------------------------------------------------------------
# Entrada a TQPF
# ----------------------------------------------------------------------

def test_entrada_tqpf_crea_lote_inventario_y_movimiento(app, ids, admin_client, entrada_tqpf):
    """La entrada a un tanque crea el lote, el inventario en posición 1 y el movimiento."""
    resp = entrada_tqpf(admin_client, ids['tqpf1'], COD_LOTE_A, 1000)
    assert resp.status_code == 302

    lote = Lote.query.filter_by(codigo_lote=COD_LOTE_A).first()
    assert lote is not None

    inventario = InventarioTQPF.query.filter_by(id_tanque=ids['tqpf1']).all()
    assert len(inventario) == 1
    assert inventario[0].posicion == 1
    assert Decimal(inventario[0].galones) == Decimal('1000.00')

    mov = Movimiento.query.filter_by(tipo_movimiento='entrada_tqpf').all()
    assert len(mov) == 1
    assert mov[0].id_tanque == ids['tqpf1']
    assert mov[0].id_lote == lote.id_lote


def test_entrada_tqpf_ultimo_ingreso_queda_en_posicion_1(app, ids, admin_client, entrada_tqpf):
    """LIFO: el último lote ingresado al tanque ocupa la posición 1."""
    entrada_tqpf(admin_client, ids['tqpf1'], COD_LOTE_A, 500)
    entrada_tqpf(admin_client, ids['tqpf1'], COD_LOTE_B, 300)

    filas = InventarioTQPF.query.filter_by(id_tanque=ids['tqpf1']).all()
    por_lote = {f.lote.codigo_lote: f.posicion for f in filas}
    assert por_lote[COD_LOTE_B] == 1
    assert por_lote[COD_LOTE_A] == 2


def test_entrada_tqpf_rechaza_formato_de_lote_invalido(app, ids, admin_client, entrada_tqpf):
    """Un código de lote que no cumple 005-AAAAMMDD-NNNNNN no se registra."""
    entrada_tqpf(admin_client, ids['tqpf1'], 'LOTE-MALO', 100)
    assert InventarioTQPF.query.count() == 0
    assert Lote.query.count() == 0


def test_entrada_tqpf_rechaza_capacidad_excedida(app, ids, admin_client, entrada_tqpf):
    """No se puede superar la capacidad del tanque (TQPF-1 = 5000 gal)."""
    entrada_tqpf(admin_client, ids['tqpf1'], COD_LOTE_A, 6000)
    assert InventarioTQPF.query.count() == 0
    assert Movimiento.query.filter_by(tipo_movimiento='entrada_tqpf').count() == 0


def test_entrada_tqpf_reutiliza_lote_existente(app, ids, admin_client, entrada_tqpf):
    """El mismo lote puede estar en dos tanques distintos sin duplicarse en el catálogo."""
    entrada_tqpf(admin_client, ids['tqpf1'], COD_LOTE_A, 100)
    entrada_tqpf(admin_client, ids['tqpf2'], COD_LOTE_A, 100)

    assert Lote.query.filter_by(codigo_lote=COD_LOTE_A).count() == 1
    assert InventarioTQPF.query.count() == 2


def test_entrada_tqpf_rechaza_lote_repetido_en_el_mismo_tanque(app, ids, admin_client, entrada_tqpf):
    """Un mismo lote no se registra dos veces en el mismo tanque."""
    entrada_tqpf(admin_client, ids['tqpf1'], COD_LOTE_A, 100)
    entrada_tqpf(admin_client, ids['tqpf1'], COD_LOTE_A, 100)
    assert InventarioTQPF.query.count() == 1


# ----------------------------------------------------------------------
# Traspaso TQPF -> Silo
# ----------------------------------------------------------------------

def test_traspaso_total_mueve_el_lote_y_registra_movimientos(
        app, ids, admin_client, post, entrada_tqpf):
    """
    El traspaso total vacía el tanque y deja el lote en el silo en posición 1.

    Con la purga de 2 tambores (104 gal) el tanque debe tener 1104 gal para
    poder mandar 1000 gal al silo: el tanque baja 1000 (silo) + 104 (purga).
    """
    entrada_tqpf(admin_client, ids['tqpf1'], COD_LOTE_A, 1104)
    item = InventarioTQPF.query.first()

    resp = post(admin_client, '/tqpf/traspaso', {
        'id_inventario_tqpf': item.id_inventario_tqpf,
        'id_silo': ids['silo_a'],
        'tipo_producto': 'concentrado',
        'galones': '1000',
        'observaciones': 'traspaso de prueba',
    })
    assert resp.status_code == 302

    # El tanque queda vacío (la fila se elimina): 1104 - 1000 - 104 = 0.
    assert InventarioTQPF.query.filter_by(id_tanque=ids['tqpf1']).count() == 0

    # El silo recibe el lote en la posición 1 (último ingreso).
    inv_silo = InventarioSilo.query.filter_by(id_silo=ids['silo_a']).all()
    assert len(inv_silo) == 1
    assert inv_silo[0].posicion == 1
    assert Decimal(inv_silo[0].galones) == Decimal('1000.00')

    # Movimientos: traspaso (con id_tanque), entrada al silo y purga.
    mv_traspaso = Movimiento.query.filter_by(tipo_movimiento='traspaso_tqpf_silo').first()
    assert mv_traspaso is not None
    assert mv_traspaso.id_tanque == ids['tqpf1']
    assert mv_traspaso.id_silo == ids['silo_a']
    assert Movimiento.query.filter_by(tipo_movimiento='entrada',
                                      id_silo=ids['silo_a']).count() == 1
    mv_purga = Movimiento.query.filter_by(tipo_movimiento='purga').first()
    assert mv_purga is not None
    assert mv_purga.id_tanque == ids['tqpf1']
    assert Decimal(mv_purga.galones) == Decimal('104.00')


def test_traspaso_descuenta_purga_adicional_del_tanque(
        app, ids, admin_client, post, entrada_tqpf):
    """
    La purga se descuenta ADEMÁS de los galones que llegan al silo.

    Entrada 1000, traspaso 400 → al silo llegan 400 y del tanque salen 504
    (400 + 104 de purga), dejando 496 en el tanque.
    """
    entrada_tqpf(admin_client, ids['tqpf1'], COD_LOTE_A, 1000)
    item = InventarioTQPF.query.first()

    post(admin_client, '/tqpf/traspaso', {
        'id_inventario_tqpf': item.id_inventario_tqpf,
        'id_silo': ids['silo_a'],
        'tipo_producto': 'concentrado',
        'galones': '400',
    })

    restante = InventarioTQPF.query.filter_by(id_tanque=ids['tqpf1']).first()
    assert Decimal(restante.galones) == Decimal('496.00')

    inv_silo = InventarioSilo.query.filter_by(id_silo=ids['silo_a']).first()
    assert Decimal(inv_silo.galones) == Decimal('400.00')


def test_traspaso_rechaza_si_no_alcanza_para_la_purga(
        app, ids, admin_client, post, entrada_tqpf):
    """Si el tanque no cubre los galones al silo MÁS la purga, no se traspasa."""
    entrada_tqpf(admin_client, ids['tqpf1'], COD_LOTE_A, 1000)
    item = InventarioTQPF.query.first()

    post(admin_client, '/tqpf/traspaso', {
        'id_inventario_tqpf': item.id_inventario_tqpf,
        'id_silo': ids['silo_a'],
        'tipo_producto': 'concentrado',
        'galones': '950',  # 950 + 104 = 1054 > 1000
    })

    assert Decimal(InventarioTQPF.query.first().galones) == Decimal('1000.00')
    assert InventarioSilo.query.count() == 0
    assert Movimiento.query.filter_by(tipo_movimiento='purga').count() == 0


def test_purga_usa_parametros_configurables(app, ids, admin_client, post, entrada_tqpf):
    """La purga respeta los parámetros del sistema (tambores y galones por tambor)."""
    from app import ParametroSistema

    ParametroSistema.query.get('galones_tambor').valor = '50'
    ParametroSistema.query.get('tambores_purga_traspaso').valor = '1'
    db.session.commit()

    entrada_tqpf(admin_client, ids['tqpf1'], COD_LOTE_A, 1000)
    item = InventarioTQPF.query.first()

    post(admin_client, '/tqpf/traspaso', {
        'id_inventario_tqpf': item.id_inventario_tqpf,
        'id_silo': ids['silo_a'],
        'tipo_producto': 'concentrado',
        'galones': '900',
    })

    # Purga = 1 tambor x 50 gal = 50 gal; el tanque baja 900 + 50 = 950.
    restante = InventarioTQPF.query.filter_by(id_tanque=ids['tqpf1']).first()
    assert Decimal(restante.galones) == Decimal('50.00')
    mv_purga = Movimiento.query.filter_by(tipo_movimiento='purga').first()
    assert Decimal(mv_purga.galones) == Decimal('50.00')


def test_pagina_purgas_lista_los_movimientos(app, ids, admin_client, post, entrada_tqpf):
    """El apartado de purgas muestra las purgas registradas."""
    entrada_tqpf(admin_client, ids['tqpf1'], COD_LOTE_A, 1000)
    item = InventarioTQPF.query.first()
    post(admin_client, '/tqpf/traspaso', {
        'id_inventario_tqpf': item.id_inventario_tqpf,
        'id_silo': ids['silo_a'],
        'tipo_producto': 'concentrado',
        'galones': '400',
    })

    resp = admin_client.get('/tqpf/purgas')
    assert resp.status_code == 200
    assert COD_LOTE_A in resp.get_data(as_text=True)


def test_traspaso_parcial_descuenta_solo_lo_indicado(app, ids, admin_client, post, entrada_tqpf):
    """Un traspaso parcial descuenta del tanque (con purga) y conserva el remanente."""
    entrada_tqpf(admin_client, ids['tqpf1'], COD_LOTE_A, 1000)
    item = InventarioTQPF.query.first()

    post(admin_client, '/tqpf/traspaso', {
        'id_inventario_tqpf': item.id_inventario_tqpf,
        'id_silo': ids['silo_a'],
        'tipo_producto': 'concentrado',
        'galones': '400',
    })

    restante = InventarioTQPF.query.filter_by(id_tanque=ids['tqpf1']).first()
    assert Decimal(restante.galones) == Decimal('496.00')
    assert Decimal(restante.posicion) == 1

    inv_silo = InventarioSilo.query.filter_by(id_silo=ids['silo_a']).first()
    assert Decimal(inv_silo.galones) == Decimal('400.00')


def test_traspaso_rechaza_cuando_excede_la_capacidad_del_silo(
        app, ids, admin_client, post, entrada_tqpf):
    """No se traspasa si el silo destino no tiene capacidad (SILO-B = 1000 gal)."""
    entrada_tqpf(admin_client, ids['tqpf1'], COD_LOTE_A, 2000)
    item = InventarioTQPF.query.first()

    post(admin_client, '/tqpf/traspaso', {
        'id_inventario_tqpf': item.id_inventario_tqpf,
        'id_silo': ids['silo_b'],
        'tipo_producto': 'concentrado',
        'galones': '1100',
    })

    # El traspaso se revierte por completo.
    assert InventarioTQPF.query.filter_by(id_tanque=ids['tqpf1']).count() == 1
    assert InventarioSilo.query.filter_by(id_silo=ids['silo_b']).count() == 0
    assert Movimiento.query.filter_by(tipo_movimiento='traspaso_tqpf_silo').count() == 0


def test_traspaso_rechaza_producto_incompatible_con_el_silo(
        app, ids, admin_client, post, entrada_tqpf):
    """SILO-JUGO sólo admite 'jugo'; un 'concentrado' se rechaza."""
    entrada_tqpf(admin_client, ids['tqpf1'], COD_LOTE_A, 700)
    item = InventarioTQPF.query.first()

    post(admin_client, '/tqpf/traspaso', {
        'id_inventario_tqpf': item.id_inventario_tqpf,
        'id_silo': ids['silo_jugo'],
        'tipo_producto': 'concentrado',
        'galones': '500',
    })

    assert InventarioSilo.query.filter_by(id_silo=ids['silo_jugo']).count() == 0
    assert InventarioTQPF.query.filter_by(id_tanque=ids['tqpf1']).count() == 1


def test_traspaso_rechaza_galones_mayores_al_disponible(
        app, ids, admin_client, post, entrada_tqpf):
    """No se puede traspasar más de lo que hay del lote en el tanque."""
    entrada_tqpf(admin_client, ids['tqpf1'], COD_LOTE_A, 500)
    item = InventarioTQPF.query.first()

    post(admin_client, '/tqpf/traspaso', {
        'id_inventario_tqpf': item.id_inventario_tqpf,
        'id_silo': ids['silo_a'],
        'tipo_producto': 'concentrado',
        'galones': '800',
    })

    assert Decimal(InventarioTQPF.query.first().galones) == Decimal('500.00')
    assert InventarioSilo.query.count() == 0


def test_traspaso_conserva_orden_lifo_en_el_silo(app, ids, admin_client, post, entrada_tqpf):
    """Dos traspasos seguidos dejan el último lote en la posición 1 del silo."""
    # Cada lote se carga con sus galones al silo + la purga (104), para que el
    # traspaso lo pueda vaciar por completo y no quede remanente en el tanque.
    entrada_tqpf(admin_client, ids['tqpf1'], COD_LOTE_A, 804)   # 700 + 104
    entrada_tqpf(admin_client, ids['tqpf1'], COD_LOTE_B, 604)   # 500 + 104

    # El lote B está en posición 1 del tanque.
    item_b = (InventarioTQPF.query.filter_by(id_tanque=ids['tqpf1'])
              .filter(InventarioTQPF.posicion == 1).first())
    post(admin_client, '/tqpf/traspaso', {
        'id_inventario_tqpf': item_b.id_inventario_tqpf,
        'id_silo': ids['silo_a'],
        'tipo_producto': 'concentrado',
        'galones': '500',
    })

    item_a = InventarioTQPF.query.filter_by(id_tanque=ids['tqpf1']).first()
    post(admin_client, '/tqpf/traspaso', {
        'id_inventario_tqpf': item_a.id_inventario_tqpf,
        'id_silo': ids['silo_a'],
        'tipo_producto': 'concentrado',
        'galones': '700',
    })

    filas = InventarioSilo.query.filter_by(id_silo=ids['silo_a']).all()
    por_lote = {f.lote.codigo_lote: f.posicion for f in filas}
    assert por_lote[COD_LOTE_A] == 1  # el último traspasado (A) queda primero
    assert por_lote[COD_LOTE_B] == 2
