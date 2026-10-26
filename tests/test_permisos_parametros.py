"""
Pruebas de permisos por rol y del parámetro que habilita/deshabilita la
captura directa a silo (sin pasar por TQPF).
"""
from datetime import date
from decimal import Decimal

from app import (
    db,
    ParametroSistema,
    InventarioSilo,
    InventarioTQPF,
    Lote,
)


def _entrada_directa_datos(ids, codigo='005-20250101-000801', galones='500'):
    """Datos del formulario de entrada directa a silo."""
    return {
        'id_silo': ids['silo_a'],
        'tipo_producto': 'concentrado',
        'codigo_lote': codigo,
        'galones': galones,
        'brix': '11.5',
        'relacion': '15',
        'pulpa': '5',
        'id_estado': ids['estado'],
        'fecha_lote': date.today().isoformat(),
    }


def _set_parametro(clave, valor):
    """Actualiza un parámetro del sistema y confirma el cambio."""
    parametro = ParametroSistema.query.get(clave)
    if parametro is None:
        parametro = ParametroSistema(clave=clave, valor=valor, descripcion=clave)
        db.session.add(parametro)
    else:
        parametro.valor = valor
    db.session.commit()


# ----------------------------------------------------------------------
# Parámetro permitir_entrada_directa_silo
# ----------------------------------------------------------------------

def test_entrada_directa_permitida_por_defecto(app, ids, admin_client, post):
    """Con el parámetro en 1 la captura directa a silo funciona."""
    resp = post(admin_client, '/entrada', _entrada_directa_datos(ids))
    assert resp.status_code == 302
    assert InventarioSilo.query.filter_by(id_silo=ids['silo_a']).count() == 1


def test_entrada_directa_bloqueada_por_parametro(app, ids, admin_client, post):
    """Con el parámetro en 0 la captura directa se bloquea (sólo traspaso desde TQPF)."""
    _set_parametro('permitir_entrada_directa_silo', '0')

    resp = post(admin_client, '/entrada', _entrada_directa_datos(ids))
    assert resp.status_code == 302
    assert InventarioSilo.query.count() == 0
    assert Lote.query.count() == 0


# ----------------------------------------------------------------------
# Rol invitado: sólo lectura
# ----------------------------------------------------------------------

def test_invitado_no_puede_registrar_entrada_a_tqpf(app, ids, invitado_client, post):
    """El rol invitado no puede escribir en el inventario de TQPF."""
    resp = post(invitado_client, '/tqpf', {
        'accion': 'entrada',
        'id_tanque': ids['tqpf1'],
        'codigo_lote': '005-20250101-000901',
        'galones': '500',
        'fecha_lote': date.today().isoformat(),
    })
    assert resp.status_code == 302
    assert InventarioTQPF.query.count() == 0


def test_invitado_no_puede_traspasar_de_tqpf_a_silo(
        app, ids, invitado_client, admin_client, post, entrada_tqpf):
    """El rol invitado no puede traspasar lotes del tanque al silo."""
    entrada_tqpf(admin_client, ids['tqpf1'], '005-20250101-000902', 500)
    item = InventarioTQPF.query.first()

    resp = post(invitado_client, '/tqpf/traspaso', {
        'id_inventario_tqpf': item.id_inventario_tqpf,
        'id_silo': ids['silo_a'],
        'tipo_producto': 'concentrado',
        'galones': '500',
    })
    assert resp.status_code == 302
    assert InventarioTQPF.query.count() == 1
    assert InventarioSilo.query.count() == 0


def test_invitado_no_puede_crear_embarques(app, ids, invitado_client, post, crear_lote):
    """El rol invitado no puede dar de alta embarques."""
    lote = crear_lote('005-20250101-000903', 2000, ids['silo_a'])

    resp = post(invitado_client, '/embarques/nuevo', {
        'fecha_embarque': date.today().isoformat(),
        'estatus': 'cargado',
        'num_cita': '2101-CITA-000901',
        'num_orden': '2101-OT000901',
        'turno': '1',
        'tipo_unidad': 'tambores',
        'lotes_ids[]': [lote.id_lote],
        'lotes_cantidades[]': ['500'],
    })
    assert resp.status_code == 302
    assert Decimal(InventarioSilo.query.filter_by(id_lote=lote.id_lote).first().galones) == Decimal('2000.00')


# ----------------------------------------------------------------------
# Rol capturista: puede operar el flujo TQPF -> Silo
# ----------------------------------------------------------------------

def test_capturista_puede_traspasar_de_tqpf_a_silo(
        app, ids, capturista_client, admin_client, post, entrada_tqpf):
    """El capturista es el rol que opera el traspaso TQPF -> Silo."""
    entrada_tqpf(admin_client, ids['tqpf1'], '005-20250101-000904', 800)
    item = InventarioTQPF.query.first()

    resp = post(capturista_client, '/tqpf/traspaso', {
        'id_inventario_tqpf': item.id_inventario_tqpf,
        'id_silo': ids['silo_a'],
        'tipo_producto': 'concentrado',
        'galones': '800',
    })
    assert resp.status_code == 302
    assert InventarioTQPF.query.count() == 0
    inv = InventarioSilo.query.filter_by(id_silo=ids['silo_a']).first()
    assert inv is not None
    assert Decimal(inv.galones) == Decimal('800.00')


def test_solo_admin_puede_cancelar_embarques(app, ids, capturista_client, admin_client, post, crear_lote):
    """Cancelar un embarque está restringido al rol administrador."""
    lote = crear_lote('005-20250101-000905', 2000, ids['silo_a'])
    post(admin_client, '/embarques/nuevo', {
        'fecha_embarque': date.today().isoformat(),
        'estatus': 'cargado',
        'num_cita': '2101-CITA-000905',
        'num_orden': '2101-OT000905',
        'turno': '1',
        'tipo_unidad': 'tambores',
        'lotes_ids[]': [lote.id_lote],
        'lotes_cantidades[]': ['500'],
    })
    from app import Embarque
    emb = Embarque.query.filter_by(num_cita='2101-CITA-000905').first()
    assert emb is not None

    # El capturista no puede cancelar: el estatus no cambia.
    post(capturista_client, f'/embarques/{emb.id_embarque}/cancelar', {})
    assert Embarque.query.get(emb.id_embarque).estatus != 'cancelado'
    assert Decimal(InventarioSilo.query.filter_by(id_lote=lote.id_lote).first().galones) == Decimal('1500.00')
