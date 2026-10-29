"""
Pruebas de conciliación de material de empaque.

Valida que la conciliación acepte tanto la plantilla del sistema
(`codigo` + `fisico_dynamics`) como el formato real del usuario
(`Nombre del producto` + `Almacén` + `UM` + `Inventario Fisico Actual`).
"""
from io import BytesIO
from decimal import Decimal

import pandas as pd

from app import db, EmpaqueArticulo


def _excel_en_memoria(df):
    """Construye un archivo Excel en memoria para subirlo con el cliente Flask."""
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Plantilla')
    buf.seek(0)
    return buf


def test_conciliacion_acepta_formato_real_por_nombre(app, admin_client, post):
    """Acepta el layout real y actualiza fisico_dynamics buscando por nombre."""
    db.session.add_all([
        EmpaqueArticulo(
            codigo='EMP001',
            nombre='Tambor de Acero Cerrado 200lt (azul) con tapones rieke',
            um='Pz',
            almacen='CP005',
            activo=True,
        ),
        EmpaqueArticulo(
            codigo='EMP002',
            nombre='Bolsa de Polietileno 98 x 200 calibre 300 para tambor cilínd',
            um='Pz',
            almacen='CP005',
            activo=True,
        ),
    ])
    db.session.commit()

    df = pd.DataFrame([
        {
            'Nombre del producto': 'Tambor de Acero Cerrado 200lt (azul) con tapones rieke',
            'Almacén': 'CP005',
            'Inventario Fisico Actual': '137',
            'UM': 'Pz',
            'Stock': '370',
            'Comentarios': '',
        },
        {
            'Nombre del producto': 'Bolsa de Polietileno 98 x 200 calibre 300 para tambor cilínd',
            'Almacén': 'CP005',
            'Inventario Fisico Actual': '15,504',
            'UM': 'Pz',
            'Stock': '4,300',
            'Comentarios': '',
        },
    ])

    resp = post(
        admin_client,
        '/embarques/empaque/conciliacion',
        {'archivo': (_excel_en_memoria(df), 'conciliacion_real.xlsx')},
        content_type='multipart/form-data',
    )
    assert resp.status_code == 302

    art1 = db.session.get(EmpaqueArticulo, 'EMP001')
    art2 = db.session.get(EmpaqueArticulo, 'EMP002')
    assert art1.fisico_dynamics == Decimal('137')
    assert art2.fisico_dynamics == Decimal('15504')


def test_conciliacion_sigue_aceptando_plantilla_por_codigo(app, admin_client, post):
    """Mantiene compatibilidad con la plantilla original del sistema."""
    db.session.add(EmpaqueArticulo(
        codigo='EMP100',
        nombre='Etiqueta Adherible Color Rojo Medida 6 x 4',
        um='Pz',
        almacen='CP005',
        activo=True,
    ))
    db.session.commit()

    df = pd.DataFrame([
        {'codigo': 'EMP100', 'fisico_dynamics': '-70'},
    ])

    resp = post(
        admin_client,
        '/embarques/empaque/conciliacion',
        {'archivo': (_excel_en_memoria(df), 'conciliacion_codigo.xlsx')},
        content_type='multipart/form-data',
    )
    assert resp.status_code == 302

    art = db.session.get(EmpaqueArticulo, 'EMP100')
    assert art.fisico_dynamics == Decimal('-70')
