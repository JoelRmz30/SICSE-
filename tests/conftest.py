"""
Configuración común de las pruebas (pytest) del flujo TQPF -> Silo y del
lote de mezcla de INVOCA.

Las pruebas corren sobre SQLite en memoria para NO tocar la base MySQL real.
La URI se fija con la variable de entorno DATABASE_URL ANTES de importar
`app`, porque app.py construye el engine de SQLAlchemy al momento del import.
"""
import os
import sys
from datetime import date
from decimal import Decimal

# Raíz del proyecto (carpeta padre de tests/) en el sys.path.
RAIZ_PROYECTO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RAIZ_PROYECTO not in sys.path:
    sys.path.insert(0, RAIZ_PROYECTO)

# Base de datos de pruebas: SQLite en memoria (no requiere servidor).
os.environ['DATABASE_URL'] = 'sqlite://'

import pytest
from flask import g
from werkzeug.security import generate_password_hash

from app import (
    app as flask_app,
    db,
    Usuario,
    Silo,
    EstadoProducto,
    Cliente,
    Lote,
    InventarioSilo,
    Movimiento,
    TanqueTQPF,
    InventarioTQPF,
    LoteComponente,
    ParametroSistema,
)

# Token CSRF fijo usado en todas las peticiones de prueba (la sesión se
# pre-carga con el mismo valor en _login).
CSRF_TOKEN = 'token-csrf-de-prueba'


@flask_app.after_request
def _limpiar_usuario_cacheado(response):
    """
    Evita que Flask-Login reutilice el usuario cacheado entre peticiones.

    En las pruebas el fixture `app` mantiene abierto un contexto de aplicación,
    por lo que todas las peticiones de un test client comparten el mismo `g`.
    Flask-Login guarda el usuario cargado en `g._login_user`; sin esta limpieza,
    si un test usa dos clientes con roles distintos (p. ej. admin y capturista),
    el segundo reutilizaría la identidad del primero (fuga de sesión).

    En producción cada petición tiene su propio contexto de aplicación, así que
    este comportamiento sólo afecta al entorno de pruebas.
    """
    g.pop('_login_user', None)
    return response



def _seed():
    """
    Crea el juego de datos mínimo y determinista para las pruebas.

    Devuelve un diccionario con los identificadores creados para que los tests
    no dependan de valores mágicos.
    """
    db.create_all()

    # --- Usuarios por rol ---
    admin = Usuario(usuario='admin', nombre='Administrador',
                    password=generate_password_hash('admin'),
                    rol='administrador', activo=True, debe_cambiar_password=False)
    capturista = Usuario(usuario='capturista', nombre='Capturista',
                         password=generate_password_hash('capturista'),
                         rol='capturista', activo=True, debe_cambiar_password=False)
    invitado = Usuario(usuario='invitado', nombre='Invitado',
                       password=generate_password_hash('invitado'),
                       rol='invitado', activo=True, debe_cambiar_password=False)
    db.session.add_all([admin, capturista, invitado])

    # --- Catálogos base ---
    estado = EstadoProducto(nombre_estado='Disponible')
    cliente = Cliente(nombre_cliente='Cliente Prueba')
    db.session.add_all([estado, cliente])

    # --- Silos: A grande (normal), B chico (para probar capacidad) ---
    silo_a = Silo(nombre_silo='SILO-A', capacidad_gal=Decimal('100000'),
                  tipo_producto=None, tipo_permitido=None, estado='activo')
    silo_b = Silo(nombre_silo='SILO-B', capacidad_gal=Decimal('1000'),
                  tipo_producto=None, tipo_permitido=None, estado='activo')
    # Silo destinado a jugo (para probar incompatibilidad de producto).
    silo_jugo = Silo(nombre_silo='SILO-JUGO', capacidad_gal=Decimal('100000'),
                     tipo_producto=None, tipo_permitido='jugo', estado='activo')
    db.session.add_all([silo_a, silo_b, silo_jugo])

    # --- Tanques de proceso (TQPF) ---
    tqpf1 = TanqueTQPF(nombre_tanque='TQPF-1', capacidad_gal=Decimal('5000'),
                       estado='activo')
    tqpf2 = TanqueTQPF(nombre_tanque='TQPF-2', capacidad_gal=Decimal('5000'),
                       estado='activo')
    db.session.add_all([tqpf1, tqpf2])

    # --- Parámetros del sistema ---
    db.session.add_all([
        ParametroSistema(clave='permitir_entrada_directa_silo', valor='1',
                         descripcion='Permite captura directa a silo (sin TQPF).'),
        ParametroSistema(clave='tqpf_ocupacion_alerta_pct', valor='90',
                         descripcion='% de ocupación de TQPF para alertar.'),
    ])

    db.session.commit()

    return {
        'admin': admin.id_usuario,
        'capturista': capturista.id_usuario,
        'invitado': invitado.id_usuario,
        'estado': estado.id_estado,
        'cliente': cliente.id_cliente,
        'silo_a': silo_a.id_silo,
        'silo_b': silo_b.id_silo,
        'silo_jugo': silo_jugo.id_silo,
        'tqpf1': tqpf1.id_tanque,
        'tqpf2': tqpf2.id_tanque,
    }


@pytest.fixture()
def app():
    """App Flask con base SQLite en memoria, recreada para cada prueba."""
    flask_app.config.update(TESTING=True)
    with flask_app.app_context():
        db.drop_all()
        ids = _seed()
        flask_app.config['IDS_PRUEBA'] = ids
        yield flask_app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def ids(app):
    """Identificadores de los datos sembrados (usuarios, silos, tanques...)."""
    return app.config['IDS_PRUEBA']


def _login(client, id_usuario):
    """Inicia sesión por sesión (Flask-Login) y fija el token CSRF."""
    with client.session_transaction() as sess:
        sess['_csrf_token'] = CSRF_TOKEN
        sess['_user_id'] = str(id_usuario)
        sess['_fresh'] = True


@pytest.fixture()
def admin_client(app):
    """Cliente autenticado como administrador."""
    cliente = app.test_client()
    _login(cliente, app.config['IDS_PRUEBA']['admin'])
    return cliente


@pytest.fixture()
def capturista_client(app):
    """Cliente autenticado como capturista."""
    cliente = app.test_client()
    _login(cliente, app.config['IDS_PRUEBA']['capturista'])
    return cliente


@pytest.fixture()
def invitado_client(app):
    """Cliente autenticado como invitado (solo lectura)."""
    cliente = app.test_client()
    _login(cliente, app.config['IDS_PRUEBA']['invitado'])
    return cliente


@pytest.fixture()
def post():
    """
    Realiza un POST agregando el token CSRF automáticamente.

    Uso: post(client, '/tqpf', {'accion': 'entrada', ...})
    """
    def _post(client, url, data=None, **kwargs):
        payload = dict(data or {})
        payload.setdefault('csrf_token', CSRF_TOKEN)
        return client.post(url, data=payload, **kwargs)
    return _post


@pytest.fixture()
def crear_lote():
    """
    Factory para crear un lote con inventario en un silo.

    Uso: lote = crear_lote('005-20250101-000001', 1000, ids['silo_a'])
    """
    def _crear(codigo, galones, id_silo, brix='11.50', posicion=1, **extra):
        lote = Lote(codigo_lote=codigo, fecha_lote=date.today(),
                    brix=Decimal(str(brix)), relacion=Decimal('15.00'),
                    pulpa=Decimal('5.00'), **extra)
        db.session.add(lote)
        db.session.flush()
        db.session.add(InventarioSilo(
            id_silo=id_silo, id_lote=lote.id_lote,
            posicion=posicion, galones=Decimal(str(galones))))
        db.session.commit()
        return lote
    return _crear


@pytest.fixture()
def entrada_tqpf(post):
    """
    Registra una entrada de lote a un tanque TQPF vía la ruta POST /tqpf.

    Uso: entrada_tqpf(admin_client, ids['tqpf1'], '005-20250101-000001', 1000)
    """
    def _entrada(client, id_tanque, codigo, galones, **extra):
        datos = {
            'accion': 'entrada',
            'id_tanque': id_tanque,
            'codigo_lote': codigo,
            'galones': str(galones),
            'fecha_lote': date.today().isoformat(),
            'brix': '11.50',
            'relacion': '15.00',
            'pulpa': '5.00',
        }
        datos.update(extra)
        return post(client, '/tqpf', datos)
    return _entrada
