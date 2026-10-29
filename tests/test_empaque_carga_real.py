"""
Pruebas de carga masiva de material de empaque con el formato real del usuario.

Valida:
  - catálogo de artículos con encabezados "Número de artículo", "Nombre del producto",
    "Almacén", "Inventario Fis", "UM", "Stock", "Comentarios".
  - entradas históricas con encabezados "Número de artículo", "Nombre del producto",
    "UM", "Entradas", "Fecha Entrada", "Proveedor", "Rechazos", "Comentarios".
"""
from io import BytesIO
from decimal import Decimal

import pandas as pd

from app import db, EmpaqueArticulo, EmpaqueEntrada, EmpaqueProveedor


def _excel_en_memoria(df):
    """Construye un archivo Excel en memoria para subirlo desde las pruebas."""
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Plantilla')
    buf.seek(0)
    return buf


def test_carga_articulos_acepta_formato_real(app, admin_client, post):
    """Acepta el layout real de artículos y lo deja listo para aplicar."""
    df = pd.DataFrame([
        {
            'Número de artículo': 'IN00123912',
            'Nombre del producto': 'Tambor de Acero Cerrado 200lt (azul) con tapones rieke',
            'Almacén': 'CP005',
            'Inventario Fis': '812',
            'UM': 'Pz',
            'Stock': '1,044',
            'Comentarios': '',
        },
        {
            'Número de artículo': 'IN00700004',
            'Nombre del producto': 'Fleje de Acero Pavonado "Apex" 3/4" x 0.023"',
            'Almacén': 'CP005',
            'Inventario Fis': '963',
            'UM': 'Kg',
            'Stock': '',
            'Comentarios': '',
        },
    ])

    resp = post(
        admin_client,
        '/embarques/empaque/carga/articulos',
        {'archivo': (_excel_en_memoria(df), 'articulos_reales.xlsx')},
        content_type='multipart/form-data',
    )
    assert resp.status_code == 302

    with admin_client.session_transaction() as sess:
        carga = sess.get('empaque_carga_articulos')
        assert carga is not None
        assert len(carga['correctas']) == 2
        assert len(carga['rechazadas']) == 0

    resp = post(admin_client, '/embarques/empaque/carga/articulos/aplicar', {})
    assert resp.status_code == 302

    art1 = db.session.get(EmpaqueArticulo, 'IN00123912')
    art2 = db.session.get(EmpaqueArticulo, 'IN00700004')
    assert art1 is not None
    assert art1.nombre == 'Tambor de Acero Cerrado 200lt (azul) con tapones rieke'
    assert art1.almacen == 'CP005'
    assert art1.um == 'Pz'
    assert art1.fisico_dynamics == Decimal('812')
    assert art2 is not None
    assert art2.um == 'Kg'
    assert art2.fisico_dynamics == Decimal('963')


def test_carga_entradas_acepta_formato_real_y_fecha_en_espanol(app, admin_client, post):
    """Acepta el layout real de entradas y guarda la fecha correcta en español."""
    db.session.add(EmpaqueArticulo(
        codigo='IN00120071',
        nombre='Tambor de Acero Abierto 200 lt R1 (naranja)',
        um='Pz',
        almacen='CP005',
        activo=True,
    ))
    db.session.add(EmpaqueProveedor(nombre='Envases Tultitlan SA de CV', activo=True))
    db.session.commit()

    df = pd.DataFrame([
        {
            'Número de artículo': 'IN00120071',
            'Nombre del producto': 'Tambor de Acero Abierto 200 lt R1 (naranja)',
            'UM': 'Pz',
            'Entradas': '300',
            'Fecha Entrada': '21 de Febrero de 2026',
            'Proveedor': 'Envases Tultitlan SA de CV',
            'Rechazos': '0',
            'Comentarios': '',
        },
        {
            'Número de artículo': 'IN00120071',
            'Nombre del producto': 'Tambor de Acero Abierto 200 lt R1 (naranja)',
            'UM': 'Pz',
            'Entradas': '224',
            'Fecha Entrada': '04 DE MARZO DEL 2026',
            'Proveedor': 'Envases Tultitlan SA de CV',
            'Rechazos': '',
            'Comentarios': '',
        },
    ])

    resp = post(
        admin_client,
        '/embarques/empaque/carga/movimientos',
        {
            'tipo': 'entradas',
            'archivo': (_excel_en_memoria(df), 'entradas_reales.xlsx'),
        },
        content_type='multipart/form-data',
    )
    assert resp.status_code == 302

    with admin_client.session_transaction() as sess:
        carga = sess.get('empaque_carga_movs_entradas')
        assert carga is not None
        assert len(carga['correctas']) == 2
        assert len(carga['rechazadas']) == 0

    resp = post(admin_client, '/embarques/empaque/carga/movimientos/aplicar/entradas', {})
    assert resp.status_code == 302

    entradas = EmpaqueEntrada.query.order_by(EmpaqueEntrada.fecha.asc()).all()
    assert len(entradas) == 2
    assert entradas[0].codigo == 'IN00120071'
    assert entradas[0].cantidad == Decimal('300')
    assert entradas[0].fecha.isoformat() == '2026-02-21'
    assert entradas[1].cantidad == Decimal('224')
    assert entradas[1].fecha.isoformat() == '2026-03-04'
