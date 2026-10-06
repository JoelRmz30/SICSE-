import os
import re
import json
import math
import pandas as pd
from io import BytesIO
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_file
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
from datetime import datetime, timedelta
from decimal import Decimal
from sqlalchemy import and_, or_, func

# Cargar variables de entorno
load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev_key_for_session_management')

# Configuración de la base de datos MySQL (Compatible con XAMPP/Laragon)
user = os.getenv('DB_USER', 'root')
password = os.getenv('DB_PASSWORD', '')
host = os.getenv('DB_HOST', 'localhost')
db_name = os.getenv('DB_NAME', 'sistema_silos')

# Usar mysqlclient o mysql-connector-python
# Para XAMPP usualmente se usa 'mysql+pymysql' o 'mysql+mysqlconnector'
# Si falla mysql-connector-python, puedes cambiar a: f'mysql+pymysql://{user}:{password}@{host}/{db_name}'
app.config['SQLALCHEMY_DATABASE_URI'] = f'mysql+pymysql://{user}:{password}@{host}/{db_name}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Modelos
class Usuario(UserMixin, db.Model):
    __tablename__ = 'usuarios'
    id_usuario = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100))
    usuario = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    rol = db.Column(db.Enum('administrador', 'capturista', 'invitado'), nullable=False)
    activo = db.Column(db.Boolean, default=True)

    def get_id(self):
        return str(self.id_usuario)

class Silo(db.Model):
    __tablename__ = 'silos'
    id_silo = db.Column(db.Integer, primary_key=True)
    nombre_silo = db.Column(db.String(20))
    capacidad_gal = db.Column(db.Numeric(10, 2))
    capacidad_barriles = db.Column(db.Numeric(10, 2))
    tipo_producto = db.Column(db.String(30), nullable=True)
    tipo_permitido = db.Column(db.String(30), nullable=True)
    estado = db.Column(db.Enum('activo', 'inactivo'), default='activo')

class EstadoProducto(db.Model):
    __tablename__ = 'estados_producto'
    id_estado = db.Column(db.Integer, primary_key=True)
    nombre_estado = db.Column(db.String(50))

class Cliente(db.Model):
    """
    Modelo de clientes/destinos existente.
    Se extiende con `codigo` para códigos cortos (Ej: CP002, CP003, CP007).
    Reutilizado por el módulo de embarques.
    """
    __tablename__ = 'clientes'
    id_cliente = db.Column(db.Integer, primary_key=True)
    nombre_cliente = db.Column(db.String(100))
    codigo = db.Column(db.String(20), nullable=True, unique=True)

class Lote(db.Model):
    __tablename__ = 'lotes'
    id_lote = db.Column(db.Integer, primary_key=True)
    codigo_lote = db.Column(db.String(50), unique=True)
    fecha_lote = db.Column(db.Date)
    brix = db.Column(db.Numeric(5, 2))
    relacion = db.Column(db.Numeric(5, 2))
    pulpa = db.Column(db.Numeric(5, 2))
    id_estado = db.Column(db.Integer, db.ForeignKey('estados_producto.id_estado'))
    id_cliente = db.Column(db.Integer, db.ForeignKey('clientes.id_cliente'), nullable=True)
    cliente_manual = db.Column(db.String(100))
    
    estado = db.relationship('EstadoProducto')
    cliente = db.relationship('Cliente')
    inventariosilos = db.relationship('InventarioSilo', backref='lote_ref', lazy=True)

class InventarioSilo(db.Model):
    __tablename__ = 'inventario_silos'
    id_inventario = db.Column(db.Integer, primary_key=True)
    id_silo = db.Column(db.Integer, db.ForeignKey('silos.id_silo'))
    id_lote = db.Column(db.Integer, db.ForeignKey('lotes.id_lote'))
    posicion = db.Column(db.Integer)
    galones = db.Column(db.Numeric(10, 2))
    fecha_registro = db.Column(db.DateTime, default=datetime.utcnow)

    silo = db.relationship('Silo')
    lote = db.relationship('Lote')

class Movimiento(db.Model):
    """
    Modelo existente de movimientos de inventario (entrada, salida, ajuste, reproceso, cambio_estado).
    Reutilizado por embarque_lotes (vínculo opcional id_movimiento).
    """
    __tablename__ = 'movimientos'
    id_movimiento = db.Column(db.Integer, primary_key=True)
    tipo_movimiento = db.Column(db.Enum('entrada', 'salida', 'ajuste', 'reproceso', 'cambio_estado'))
    id_silo = db.Column(db.Integer, db.ForeignKey('silos.id_silo'))
    id_lote = db.Column(db.Integer, db.ForeignKey('lotes.id_lote'))
    galones = db.Column(db.Numeric(10, 2))
    fecha_movimiento = db.Column(db.DateTime, default=datetime.utcnow)
    id_usuario = db.Column(db.Integer, db.ForeignKey('usuarios.id_usuario'))
    observaciones = db.Column(db.Text)

    silo = db.relationship('Silo')
    lote = db.relationship('Lote')
    usuario = db.relationship('Usuario')


# =====================================================================
# ===== MÓDULO EMBARQUES - MODELOS ====================================
# =====================================================================
# Relación tipo_unidad -> grupo de detalle.
# Controla qué campos de detalle y qué tipos de sello aplican al embarque.
TIPO_UNIDAD_GRUPO = {
    'pipa_jumbo': 'pipa',
    'pipa_chica': 'pipa',
    'isotanque': 'pipa',
    'flexitanque': 'pipa',
    'caja_refrigerada': 'caja',
    'caja_seca': 'caja',
    'trailer': 'caja',
    'tambores': 'tambor',
}

# Estatus de embarque con su estilo visual de badge Bootstrap.
ESTILO_ESTATUS_EMBARQUE = {
    'programado': 'secondary',
    'en_planta': 'primary',
    'cargado': 'success',
    'cancelado': 'danger',
}


class ProductoEmbarque(db.Model):
    """
    Catálogo de productos que se embarcan (concentrado, pulpa, colateral).

    - item es único y es el código de producto (Ej: PT1701P004).
    - Nunca se elimina; se desactiva con `activo=False`.
    """
    __tablename__ = 'productos_embarque'
    id_producto = db.Column(db.Integer, primary_key=True)
    item = db.Column(db.String(50), nullable=False, unique=True)
    descripcion = db.Column(db.String(255), nullable=False)
    variedad = db.Column(db.String(100), nullable=True)
    tipo = db.Column(db.Enum('concentrado', 'pulpa', 'colateral'), nullable=False)
    unidad_medida = db.Column(db.Enum('KG', 'TAZ'), nullable=False)
    activo = db.Column(db.Boolean, default=True)
    creado_en = db.Column(db.DateTime, default=datetime.utcnow)
    actualizado_en = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Transportista(db.Model):
    """
    Catálogo de líneas transportistas. Nunca se borran, solo se desactivan.
    """
    __tablename__ = 'transportistas'
    id_transportista = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(200), nullable=False, unique=True)
    activo = db.Column(db.Boolean, default=True)
    creado_en = db.Column(db.DateTime, default=datetime.utcnow)
    actualizado_en = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Operador(db.Model):
    """
    Catálogo de operadores / choferes. Pertenencia a transportista es opcional.
    """
    __tablename__ = 'operadores'
    id_operador = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(200), nullable=False)
    id_transportista = db.Column(db.Integer, db.ForeignKey('transportistas.id_transportista'), nullable=True)
    activo = db.Column(db.Boolean, default=True)
    creado_en = db.Column(db.DateTime, default=datetime.utcnow)
    actualizado_en = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    transportista = db.relationship('Transportista')


class UnidadTransporte(db.Model):
    """
    Catálogo de tractores y remolques.
    placa se guarda en mayúsculas y es única.
    """
    __tablename__ = 'unidades_transporte'
    id_unidad = db.Column(db.Integer, primary_key=True)
    placa = db.Column(db.String(30), nullable=False, unique=True)
    tipo = db.Column(db.Enum('tractor', 'remolque'), nullable=False)
    activo = db.Column(db.Boolean, default=True)
    creado_en = db.Column(db.DateTime, default=datetime.utcnow)
    actualizado_en = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Lavadero(db.Model):
    """
    Catálogo de lavaderos autorizados (solo aplica para el grupo pipa).
    """
    __tablename__ = 'lavaderos'
    id_lavadero = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(200), nullable=False, unique=True)
    activo = db.Column(db.Boolean, default=True)
    creado_en = db.Column(db.DateTime, default=datetime.utcnow)
    actualizado_en = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Facilitador(db.Model):
    """
    Catálogo de facilitadores / agentes de transporte.
    """
    __tablename__ = 'facilitadores'
    id_facilitador = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(200), nullable=False)
    activo = db.Column(db.Boolean, default=True)
    creado_en = db.Column(db.DateTime, default=datetime.utcnow)
    actualizado_en = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Embarque(db.Model):
    """
    Tabla central del módulo de embarques.

    Reglas clave:
    - num_cita, ticket, packing son UNIQUE: serán llaves de conexión con Dynamics.
    - No existe columna cantidad; se calcula SUM(embarque_lotes.cantidad).
    - id_capturista y actualizado_por son auditoría; id_capturista se llena con
      current_user al crear, actualizado_por al editar.
    """
    __tablename__ = 'embarques'
    id_embarque = db.Column(db.Integer, primary_key=True)
    fecha_embarque = db.Column(db.Date, nullable=False)
    estatus = db.Column(db.Enum('programado', 'en_planta', 'cargado', 'cancelado'),
                        nullable=False, default='cargado')
    num_cita = db.Column(db.String(30), nullable=False, unique=True)
    num_orden = db.Column(db.String(30), nullable=False)
    ticket = db.Column(db.String(30), nullable=True, unique=True)
    packing = db.Column(db.String(30), nullable=True, unique=True)
    id_producto = db.Column(db.Integer, db.ForeignKey('productos_embarque.id_producto'), nullable=False)
    id_cliente = db.Column(db.Integer, db.ForeignKey('clientes.id_cliente'), nullable=False)
    tipo_unidad = db.Column(db.Enum('pipa_jumbo', 'pipa_chica', 'isotanque', 'flexitanque',
                                    'caja_refrigerada', 'caja_seca', 'trailer', 'tambores'),
                            nullable=False)
    id_transportista = db.Column(db.Integer, db.ForeignKey('transportistas.id_transportista'), nullable=True)
    id_operador = db.Column(db.Integer, db.ForeignKey('operadores.id_operador'), nullable=True)
    id_tractor = db.Column(db.Integer, db.ForeignKey('unidades_transporte.id_unidad'), nullable=True)
    id_remolque = db.Column(db.Integer, db.ForeignKey('unidades_transporte.id_unidad'), nullable=True)
    turno = db.Column(db.SmallInteger, nullable=False)
    temperatura_c = db.Column(db.Numeric(5, 1), nullable=True)
    id_capturista = db.Column(db.Integer, db.ForeignKey('usuarios.id_usuario'), nullable=False)
    id_facilitador = db.Column(db.Integer, db.ForeignKey('facilitadores.id_facilitador'), nullable=True)
    observaciones = db.Column(db.Text, nullable=True)
    creado_en = db.Column(db.DateTime, default=datetime.utcnow)
    actualizado_en = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    actualizado_por = db.Column(db.Integer, db.ForeignKey('usuarios.id_usuario'), nullable=True)

    # Relaciones
    producto = db.relationship('ProductoEmbarque')
    cliente = db.relationship('Cliente')
    transportista = db.relationship('Transportista', foreign_keys=[id_transportista])
    operador = db.relationship('Operador', foreign_keys=[id_operador])
    tractor = db.relationship('UnidadTransporte', foreign_keys=[id_tractor])
    remolque = db.relationship('UnidadTransporte', foreign_keys=[id_remolque])
    capturista = db.relationship('Usuario', foreign_keys=[id_capturista])
    facilitador = db.relationship('Facilitador', foreign_keys=[id_facilitador])
    actualizado_por_usuario = db.relationship('Usuario', foreign_keys=[actualizado_por])
    tiempos = db.relationship('EmbarqueTiempos', backref='embarque', uselist=False,
                              cascade='all, delete-orphan')
    detalle = db.relationship('EmbarqueDetalle', backref='embarque', uselist=False,
                              cascade='all, delete-orphan')
    sellos = db.relationship('EmbarqueSello', backref='embarque',
                             cascade='all, delete-orphan', lazy=True)
    lotes = db.relationship('EmbarqueLote', backref='embarque',
                            cascade='all, delete-orphan', lazy=True)

    @property
    def grupo_unidad(self):
        """Devuelve 'pipa', 'caja' o 'tambor' según el tipo_unidad."""
        return TIPO_UNIDAD_GRUPO.get(self.tipo_unidad, '')

    @property
    def cantidad_total(self):
        """Cantidad embarcada calculada: suma de embarque_lotes.cantidad (no se guarda)."""
        return sum((Decimal(str(el.cantidad)) if el.cantidad is not None else Decimal('0'))
                   for el in self.lotes)

    @property
    def badge_estatus(self):
        """Clase CSS Bootstrap para badge de estatus."""
        return ESTILO_ESTATUS_EMBARQUE.get(self.estatus, 'secondary')


class EmbarqueTiempos(db.Model):
    """
    Registro 1 a 1 de tiempos operativos del embarque.
    Orden obligatorio: llegada <= entrada <= pesado_inicial <= pesaje_salida
                       <= documentacion <= salida.
    Si faltan tiempos el estatus debe quedar 'en_planta'; con los 6 completos
    puede pasar a 'cargado'.
    """
    __tablename__ = 'embarque_tiempos'
    id_embarque = db.Column(db.Integer, db.ForeignKey('embarques.id_embarque'),
                            primary_key=True)
    llegada = db.Column(db.DateTime, nullable=True)
    entrada = db.Column(db.DateTime, nullable=True)
    pesado_inicial = db.Column(db.DateTime, nullable=True)
    pesaje_salida = db.Column(db.DateTime, nullable=True)
    documentacion = db.Column(db.DateTime, nullable=True)
    salida = db.Column(db.DateTime, nullable=True)

    def tiempos_ordenados(self):
        """
        Valida que los tiempos estén en orden cronológico.
        Devuelve (ok: bool, mensaje: str).
        """
        pares = [
            ('llegada', self.llegada, 'entrada', self.entrada),
            ('entrada', self.entrada, 'pesado_inicial', self.pesado_inicial),
            ('pesado_inicial', self.pesado_inicial, 'pesaje_salida', self.pesaje_salida),
            ('pesaje_salida', self.pesaje_salida, 'documentacion', self.documentacion),
            ('documentacion', self.documentacion, 'salida', self.salida),
        ]
        nombres = {
            'llegada': 'Llegada',
            'entrada': 'Entrada',
            'pesado_inicial': 'Pesado inicial',
            'pesaje_salida': 'Pesaje de salida',
            'documentacion': 'Documentación',
            'salida': 'Salida',
        }
        for a_n, a_v, b_n, b_v in pares:
            if a_v and b_v and a_v > b_v:
                return False, f'{nombres[a_n]} no puede ser posterior a {nombres[b_n]}.'
        return True, ''

    def completos(self):
        """True si los seis tiempos están registrados."""
        return all([self.llegada, self.entrada, self.pesado_inicial,
                    self.pesaje_salida, self.documentacion, self.salida])

    @property
    def tiempo_en_planta(self):
        """Diferencia salida - entrada (timedelta o None). Campo calculado: NO se guarda."""
        if self.entrada and self.salida:
            return self.salida - self.entrada
        return None

    @property
    def tiempo_documental(self):
        """Diferencia salida - documentacion (timedelta o None). Campo calculado."""
        if self.documentacion and self.salida:
            return self.salida - self.documentacion
        return None


class EmbarqueDetalle(db.Model):
    """
    Detalle opcional 1 a 1 con embarques. Los campos significan algo solo
    según el grupo del tipo_unidad:
      - grupo pipa     -> id_lavadero
      - grupo caja     -> (ninguno de estos; temperatura_c está en embarque)
      - grupo tambor   -> check_list, lote_tambor
    """
    __tablename__ = 'embarque_detalle'
    id_embarque = db.Column(db.Integer, db.ForeignKey('embarques.id_embarque'),
                            primary_key=True)
    id_lavadero = db.Column(db.Integer, db.ForeignKey('lavaderos.id_lavadero'), nullable=True)
    check_list = db.Column(db.Boolean, nullable=True)
    lote_tambor = db.Column(db.String(100), nullable=True)

    lavadero = db.relationship('Lavadero')


class EmbarqueSello(db.Model):
    """
    Sellos colocados a la unidad (1 a N).
    - numero es UNIQUE en toda la tabla; si se repite se debe mostrar mensaje
      claro al usuario y no dejar que explote el error SQL.
    - tipo depende del grupo de la unidad:
        pipa  -> lavado, valvula, escotilla
        caja  -> puerta_trasera
        tambor-> (ninguno)
    """
    __tablename__ = 'embarque_sellos'
    id_sello = db.Column(db.Integer, primary_key=True)
    id_embarque = db.Column(db.Integer, db.ForeignKey('embarques.id_embarque'), nullable=False)
    tipo = db.Column(db.Enum('lavado', 'valvula', 'escotilla', 'puerta_trasera'), nullable=False)
    numero = db.Column(db.String(100), nullable=False, unique=True)
    creado_en = db.Column(db.DateTime, default=datetime.utcnow)


class EmbarqueLote(db.Model):
    """
    Desglose por lote de la cantidad embarcada (llave compuesta).
    - cantidad > 0 (no se valida en modelo, pero sí en servidor).
    - La cantidad total del embarque es la suma de este campo (no se guarda).
    - id_movimiento es vínculo opcional con el flujo de salidas existente.
    """
    __tablename__ = 'embarque_lotes'
    id_embarque = db.Column(db.Integer, db.ForeignKey('embarques.id_embarque'), primary_key=True)
    id_lote = db.Column(db.Integer, db.ForeignKey('lotes.id_lote'), primary_key=True)
    cantidad = db.Column(db.Numeric(12, 2), nullable=False)
    id_movimiento = db.Column(db.Integer, db.ForeignKey('movimientos.id_movimiento'), nullable=True)

    lote = db.relationship('Lote')
    movimiento = db.relationship('Movimiento')


class ParametroSistema(db.Model):
    """
    Parámetros configurables del sistema. Permite ajustar validaciones
    (rangos de brix, temperatura, relación por producto, etc.) sin tocar código.
    Las validaciones de rango solo se aplican si el parámetro existe.
    """
    __tablename__ = 'parametros_sistema'
    clave = db.Column(db.String(100), primary_key=True)
    valor = db.Column(db.Text, nullable=False)
    descripcion = db.Column(db.String(255), nullable=False)
    creado_en = db.Column(db.DateTime, default=datetime.utcnow)
    actualizado_en = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# =====================================================================
# ===== FIN MODELOS EMBARQUES =========================================
# =====================================================================

@login_manager.user_loader
def load_user(user_id):
    return Usuario.query.get(int(user_id))

def _is_guest():
    if not current_user.is_authenticated:
        return False
    if (getattr(current_user, 'usuario', '') or '').strip().lower() == 'invitado':
        return True
    rol = (current_user.rol or '').strip().lower()
    if rol in ('administrador', 'capturista'):
        return False
    return True

def _deny_if_guest():
    if _is_guest():
        flash('Acceso denegado: el usuario invitado solo puede visualizar datos, no modificar.')
        return True
    return False

def _parse_json_dict(value):
    if not value:
        return {}
    try:
        data = json.loads(value)
        if isinstance(data, dict):
            return data
    except Exception:
        return {}
    return {}


@app.context_processor
def inject_helpers():
    """
    Expone helpers al motor de plantillas Jinja2 para todas las vistas.
    - _is_guest: permite ocultar botones de escritura al rol invitado.
    """
    return {
        '_is_guest': _is_guest,
    }

RUTAS_PERMITIDAS_INVITADO_GET = frozenset({
    # Rutas existentes
    'index', 'historial', 'ver_inventario_silo', 'exportar_historial',
    'login', 'logout', 'static',
    # Módulo embarques: solo lectura (listado, detalle, exportar, cuadre, API lotes)
    'listar_embarques', 'detalle_embarque', 'exportar_embarques',
    'cuadre_embarques', 'api_embarques_lotes',
})

RUTAS_NO_PERMITIDAS_INVITADO = frozenset({
    # Rutas existentes
    'registrar_entrada', 'registrar_salida', 'registrar_reproceso',
    'gestionar_usuarios', 'nuevo_usuario', 'reset_silos',
    'cambiar_estado_lote',
    # Módulo embarques: escritura está bloqueada además por _block_guest_writes
    'nuevo_embarque', 'editar_embarque', 'cancelar_embarque',
    'gestionar_catalogo',
})

@app.before_request
def _block_guest_writes():
    if not current_user.is_authenticated:
        return None
    if not _is_guest():
        return None
    metodo = request.method
    endpoint_full = request.endpoint or ''
    endpoint = endpoint_full.split('.')[-1]

    if metodo not in ('GET', 'HEAD', 'OPTIONS'):
        flash(f'Acceso denegado ({metodo}): usuario invitado no puede modificar datos.')
        return redirect(url_for('index'))

    if metodo == 'GET':
        if endpoint in RUTAS_NO_PERMITIDAS_INVITADO:
            flash('Acceso denegado: el usuario invitado solo puede visualizar datos.')
            return redirect(url_for('index'))
        if endpoint and endpoint not in RUTAS_PERMITIDAS_INVITADO_GET and endpoint != '' and not endpoint.startswith('debug_toolbar'):
            if endpoint in RUTAS_NO_PERMITIDAS_INVITADO or endpoint.startswith('gestionar') or endpoint.startswith('nuevo_') or endpoint.startswith('registrar_'):
                flash('Acceso denegado: el usuario invitado solo puede visualizar datos.')
                return redirect(url_for('index'))

# Rutas
@app.route('/')
@login_required
def index():
    silos = Silo.query.filter_by(estado='activo').all()
    silos_data = []
    total_galones = 0.0
    capacidad_total = 0.0
    silos_ocupados = 0
    
    total_jugo = 0
    total_concentrado = 0
    capacidad_jugo = 0
    capacidad_concentrado = 0
    
    # Estadísticas por cliente y estado
    clientes_stats = {}
    estados_stats = {}
    estados_silos_stats = {}
    clientes_silos_stats = {}

    for silo in silos:
        inventario = InventarioSilo.query.filter_by(id_silo=silo.id_silo).all()
        galones_actuales = sum(float(item.galones) for item in inventario)
        total_galones += galones_actuales
        capacidad_total += float(silo.capacidad_gal)
        
        if galones_actuales > 0:
            silos_ocupados += 1
        
        # Convertir silo.capacidad_gal a float para el cálculo
        capacidad_gal_float = float(silo.capacidad_gal)
        porcentaje_ocupacion = (galones_actuales / capacidad_gal_float * 100) if capacidad_gal_float > 0 else 0
        
        silos_data.append({
            'id_silo': silo.id_silo,
            'nombre': silo.nombre_silo,
            'tipo': silo.tipo_producto,
            'tipo_permitido': silo.tipo_permitido,
            'capacidad': float(silo.capacidad_gal),
            'inventario': galones_actuales,
            'ocupacion': round(porcentaje_ocupacion, 2)
        })
        
        # Acumular estadísticas por cliente y estado
        for item in inventario:
            # Por cliente
            cliente_nombre = None
            if item.lote.cliente:
                cliente_nombre = item.lote.cliente.nombre_cliente
            elif item.lote.cliente_manual:
                cliente_nombre = item.lote.cliente_manual
            else:
                cliente_nombre = "Sin Cliente"
            
            if cliente_nombre not in clientes_stats:
                clientes_stats[cliente_nombre] = 0.0
            clientes_stats[cliente_nombre] += float(item.galones)

            if cliente_nombre not in clientes_silos_stats:
                clientes_silos_stats[cliente_nombre] = {}
            silo_nombre = silo.nombre_silo
            if silo_nombre not in clientes_silos_stats[cliente_nombre]:
                clientes_silos_stats[cliente_nombre][silo_nombre] = 0.0
            clientes_silos_stats[cliente_nombre][silo_nombre] += float(item.galones)
            
            # Por estado
            estado_nombre = item.lote.estado.nombre_estado
            if estado_nombre not in estados_stats:
                estados_stats[estado_nombre] = 0.0
            estados_stats[estado_nombre] += float(item.galones)

            if estado_nombre not in estados_silos_stats:
                estados_silos_stats[estado_nombre] = {}
            silo_nombre = silo.nombre_silo
            if silo_nombre not in estados_silos_stats[estado_nombre]:
                estados_silos_stats[estado_nombre][silo_nombre] = 0.0
            estados_silos_stats[estado_nombre][silo_nombre] += float(item.galones)

    porcentaje_total = (total_galones / capacidad_total * 100) if capacidad_total > 0 else 0
    
    # Calcular porcentajes para clientes
    clientes_stats_list = []
    for cliente, galones in clientes_stats.items():
        porcentaje = (galones / total_galones * 100) if total_galones > 0 else 0
        silos_map = clientes_silos_stats.get(cliente, {})
        silos_list = [{'silo': k, 'galones': v} for k, v in silos_map.items()]
        silos_list.sort(key=lambda x: x['galones'], reverse=True)
        clientes_stats_list.append({
            'nombre': cliente,
            'galones': galones,
            'porcentaje': round(porcentaje, 2),
            'silos': silos_list
        })
    
    # Ordenar clientes por galones (mayor a menor)
    clientes_stats_list.sort(key=lambda x: x['galones'], reverse=True)
    
    estados_list = []
    for estado, galones in estados_stats.items():
        silos_map = estados_silos_stats.get(estado, {})
        silos_list = [{'silo': k, 'galones': v} for k, v in silos_map.items()]
        silos_list.sort(key=lambda x: x['galones'], reverse=True)
        estados_list.append({'estado': estado, 'galones': galones, 'silos': silos_list})
    estados_list.sort(key=lambda x: x['galones'], reverse=True)

    stats = {
        'total_galones': total_galones,
        'porcentaje_total': round(porcentaje_total, 2),
        'silos_ocupados': silos_ocupados,
        'silos_totales': len(silos),
        'clientes': clientes_stats_list,
        'estados': estados_stats,
        'estados_list': estados_list
    }

    return render_template('dashboard.html', silos=silos_data, stats=stats)

@app.route('/inventario/<int:id_silo>')
@login_required
def ver_inventario_silo(id_silo):
    silo = Silo.query.get_or_404(id_silo)
    inventario = InventarioSilo.query.filter_by(id_silo=id_silo).order_by(InventarioSilo.posicion).all()
    estados = EstadoProducto.query.all()
    clientes = Cliente.query.all()
    return render_template('silo_detalle.html', silo=silo, inventario=inventario, estados=estados, clientes=clientes)

@app.route('/inventario/cambiar-estado/<int:id_inventario>', methods=['POST'])
@login_required
def cambiar_estado_lote(id_inventario):
    if _deny_if_guest():
        return redirect(url_for('index'))
    try:
        item_inventario = InventarioSilo.query.get_or_404(id_inventario)
        nuevo_estado_id = request.form.get('nuevo_estado')
        id_cliente = request.form.get('id_cliente')
        cliente_manual = request.form.get('cliente_manual', '').strip()
        observaciones = request.form.get('observaciones', '')
        
        # Obtener el estado anterior y nuevo
        estado_anterior = item_inventario.lote.estado.nombre_estado
        nuevo_estado = EstadoProducto.query.get(nuevo_estado_id)
        cliente_anterior = None
        if item_inventario.lote.cliente:
            cliente_anterior = item_inventario.lote.cliente.nombre_cliente
        elif item_inventario.lote.cliente_manual:
            cliente_anterior = item_inventario.lote.cliente_manual
        
        # Actualizar el estado del lote
        item_inventario.lote.id_estado = nuevo_estado_id

        cliente_cambio = ''
        if id_cliente == '__none__':
            item_inventario.lote.id_cliente = None
            item_inventario.lote.cliente_manual = None
            if cliente_anterior:
                cliente_cambio = f"Cliente: {cliente_anterior} → Sin cliente. "
        elif id_cliente:
            item_inventario.lote.id_cliente = id_cliente
            item_inventario.lote.cliente_manual = None
            cliente_obj = Cliente.query.get(id_cliente)
            cliente_nombre = cliente_obj.nombre_cliente if cliente_obj else str(id_cliente)
            if cliente_anterior != cliente_nombre:
                cliente_cambio = f"Cliente: {cliente_anterior or 'Sin cliente'} → {cliente_nombre}. "
        elif cliente_manual:
            item_inventario.lote.id_cliente = None
            item_inventario.lote.cliente_manual = cliente_manual
            if cliente_anterior != cliente_manual:
                cliente_cambio = f"Cliente: {cliente_anterior or 'Sin cliente'} → {cliente_manual}. "
        
        # Registrar el movimiento
        movimiento = Movimiento(
            tipo_movimiento='cambio_estado',
            id_silo=item_inventario.id_silo,
            id_lote=item_inventario.id_lote,
            galones=float(item_inventario.galones),
            id_usuario=current_user.id_usuario,
            observaciones=f"{cliente_cambio}Cambio de estado: {estado_anterior} → {nuevo_estado.nombre_estado}. {observaciones}".strip()
        )
        db.session.add(movimiento)
        
        db.session.commit()
        flash(f'Estado del lote {item_inventario.lote.codigo_lote} actualizado correctamente!', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error al cambiar el estado: {str(e)}', 'danger')
    
    return redirect(url_for('ver_inventario_silo', id_silo=item_inventario.id_silo))

@app.route('/entrada', methods=['GET', 'POST'])
@login_required
def registrar_entrada():
    if _deny_if_guest():
        return redirect(url_for('index'))
    if request.method == 'GET':
        subq = db.session.query(InventarioSilo.id_silo).distinct()
        updated1 = db.session.query(Silo).filter(Silo.tipo_producto.isnot(None), ~Silo.id_silo.in_(subq)).update(
            {Silo.tipo_producto: None},
            synchronize_session=False
        )
        updated2 = db.session.query(Silo).filter(Silo.tipo_permitido.isnot(None), ~Silo.id_silo.in_(subq)).update(
            {Silo.tipo_producto: Silo.tipo_permitido},
            synchronize_session=False
        )
        if updated1 or updated2:
            db.session.commit()
    if request.method == 'POST':
        try:
            id_silo = request.form.get('id_silo')
            tipo_producto = request.form.get('tipo_producto')
            codigo_lote = request.form.get('codigo_lote')
            galones = float(request.form.get('galones'))
            brix = float(request.form.get('brix'))
            relacion = float(request.form.get('relacion'))
            pulpa = float(request.form.get('pulpa'))
            id_estado = request.form.get('id_estado')
            id_cliente = request.form.get('id_cliente')
            cliente_manual = request.form.get('cliente_manual')
            fecha_lote = request.form.get('fecha_lote')
            
            # Validar formato del lote
            lote_regex = r'^\d{3}-\d{8}-\d{6}$'
            if not re.match(lote_regex, codigo_lote):
                flash('Error: Formato de lote incorrecto. Usa: 005-20251210-044497', 'danger')
                return redirect(url_for('registrar_entrada'))

            silo = Silo.query.get(id_silo)
            inventario_actual = InventarioSilo.query.filter_by(id_silo=id_silo).all()
            galones_actuales = sum(float(item.galones) for item in inventario_actual)
            if galones_actuales <= 0 and silo.tipo_permitido:
                silo.tipo_producto = silo.tipo_permitido
            elif galones_actuales <= 0 and silo.tipo_producto is not None:
                silo.tipo_producto = None

            if silo.tipo_permitido and tipo_producto != silo.tipo_permitido:
                tipo_silo_esp = {
                    'jugo': 'Jugo',
                    'concentrado': 'Concentrado',
                    'aceite': 'Aceite',
                    'nfc': 'NFC'
                }.get(silo.tipo_permitido, silo.tipo_permitido)
                flash(f'Error: Este silo está destinado a {tipo_silo_esp}.', 'danger')
                return redirect(url_for('registrar_entrada'))

            # Verificar tipo del silo
            if silo.tipo_producto:
                if silo.tipo_producto != tipo_producto:
                    # Obtener nombres en español
                    tipo_silo_esp = {
                        'jugo': 'Jugo',
                        'concentrado': 'Concentrado',
                        'aceite': 'Aceite',
                        'nfc': 'NFC'
                    }.get(silo.tipo_producto, silo.tipo_producto)
                    tipo_nuevo_esp = {
                        'jugo': 'Jugo',
                        'concentrado': 'Concentrado',
                        'aceite': 'Aceite',
                        'nfc': 'NFC'
                    }.get(tipo_producto, tipo_producto)
                    flash(f'Error: Este silo ya tiene {tipo_silo_esp}. No puedes agregar {tipo_nuevo_esp}.', 'danger')
                    return redirect(url_for('registrar_entrada'))
            else:
                # Establecer el tipo del silo por primera vez
                silo.tipo_producto = silo.tipo_permitido or tipo_producto

            # Verificar capacidad del silo
            capacidad_gal = float(silo.capacidad_gal)
            if (galones_actuales + galones) > capacidad_gal:
                disponibles = capacidad_gal - galones_actuales
                flash(f'Error: Capacidad del silo excedida. Galones disponibles: {disponibles:.2f}', 'danger')
                return redirect(url_for('registrar_entrada'))

            # 1. Crear o buscar lote
            lote = Lote.query.filter_by(codigo_lote=codigo_lote).first()
            
            if lote:
                # Verificar si el lote ya está en el mismo silo
                existing_in_silo = InventarioSilo.query.filter_by(
                    id_silo=id_silo,
                    id_lote=lote.id_lote
                ).first()
                
                if existing_in_silo:
                    flash(f'Error: Este lote ({codigo_lote}) ya está registrado en este silo.', 'danger')
                    return redirect(url_for('registrar_entrada'))
            else:
                # Crear nuevo lote
                lote = Lote(
                    codigo_lote=codigo_lote,
                    fecha_lote=datetime.strptime(fecha_lote, '%Y-%m-%d'),
                    brix=brix,
                    relacion=relacion,
                    pulpa=pulpa,
                    id_estado=id_estado,
                    id_cliente=id_cliente if id_cliente else None,
                    cliente_manual=cliente_manual if cliente_manual else None
                )
                db.session.add(lote)
                db.session.flush() # Para obtener el id_lote

            # 2. Desplazar todas las posiciones existentes hacia abajo (nueva entrada es pos 1)
            items_existentes = InventarioSilo.query.filter_by(id_silo=id_silo).order_by(InventarioSilo.posicion).all()
            for item in items_existentes:
                item.posicion += 1

            # 3. Crear nuevo item en posición 1
            nuevo_item = InventarioSilo(
                id_silo=id_silo,
                id_lote=lote.id_lote,
                posicion=1,
                galones=galones
            )
            db.session.add(nuevo_item)

            # 4. Registrar movimiento
            movimiento = Movimiento(
                tipo_movimiento='entrada',
                id_silo=id_silo,
                id_lote=lote.id_lote,
                galones=galones,
                id_usuario=current_user.id_usuario,
                observaciones=request.form.get('observaciones')
            )
            db.session.add(movimiento)
            
            db.session.commit()
            flash('Entrada registrada correctamente.', 'success')
            return redirect(url_for('index'))
        except ValueError as e:
            db.session.rollback()
            flash('Error: Valor inválido. Por favor revisa los números (galones, brix, relación, pulpa).', 'danger')
        except Exception as e:
            db.session.rollback()
            # Mensaje de error amigable en español
            error_msg = 'Ocurrió un error al registrar la entrada. Por favor intenta nuevamente.'
            if 'capacidad' in str(e).lower():
                error_msg = 'Error: Problema con la capacidad del silo.'
            elif 'lote' in str(e).lower():
                error_msg = 'Error: Problema con el lote (ya existe o formato incorrecto).'
            elif 'usuario' in str(e).lower():
                error_msg = 'Error: Problema con el usuario.'
            flash(error_msg, 'danger')
            
    silos = Silo.query.filter_by(estado='activo').all()
    estados = EstadoProducto.query.all()
    clientes = Cliente.query.all()
    return render_template('entrada.html', silos=silos, estados=estados, clientes=clientes)

@app.route('/salida', methods=['GET', 'POST'])
@login_required
def registrar_salida():
    if _deny_if_guest():
        return redirect(url_for('index'))
    if request.method == 'POST':
        try:
            id_silo = request.form.get('id_silo')
            galones_raw = (request.form.get('galones') or '').strip()
            galones_a_sacar = Decimal(galones_raw or '0')
            destino = request.form.get('destino', '')
            placa = request.form.get('placa', '').strip()
            observaciones = request.form.get('observaciones', '')
            
            if galones_a_sacar <= 0:
                raise ValueError('La cantidad de galones debe ser mayor a 0.')

            if not re.match(r'^\d{1,9}$', placa or ''):
                raise ValueError('Número de placa inválido. Debe ser numérico y de máximo 9 dígitos.')

            partes_obs = []
            if placa:
                partes_obs.append(f"Placa: {placa}.")
            if destino:
                partes_obs.append(f"Destino: {destino}.")
            if observaciones:
                partes_obs.append(observaciones)
            observaciones = " ".join(partes_obs).strip()

            # Lógica LIFO: Obtener lotes del silo ordenados por posición descendente (último que entró primero que sale)
            items_inventario = InventarioSilo.query.filter_by(id_silo=id_silo).order_by(InventarioSilo.posicion.asc()).all()
            
            restante = galones_a_sacar
            for item in items_inventario:
                if restante <= 0:
                    break
                
                galones_en_lote = Decimal(item.galones)
                sacar_de_este = min(galones_en_lote, restante)
                
                # Registrar movimiento por cada lote afectado
                movimiento = Movimiento(
                    tipo_movimiento='salida',
                    id_silo=id_silo,
                    id_lote=item.id_lote,
                    galones=sacar_de_este,
                    id_usuario=current_user.id_usuario,
                    observaciones=f"{observaciones} (LIFO Lote {item.lote.codigo_lote} - Pos {item.posicion})".strip()
                )
                db.session.add(movimiento)

                if sacar_de_este >= galones_en_lote:
                    # Lote se vacía, eliminar de inventario
                    db.session.delete(item)
                else:
                    # Descontar del lote
                    item.galones = galones_en_lote - sacar_de_este
                
                restante -= sacar_de_este

            if restante > 0:
                raise Exception(f"No hay suficientes galones en el silo. Faltaron {restante} gal.")

            # Recalcular posiciones LIFO
            db.session.flush()
            restantes_en_silo = InventarioSilo.query.filter_by(id_silo=id_silo).order_by(InventarioSilo.posicion).all()
            for i, item in enumerate(restantes_en_silo):
                item.posicion = i + 1

            # Verificar si el silo está completamente vacío y resetear el tipo de producto
            if not restantes_en_silo:
                silo = Silo.query.get(id_silo)
                silo.tipo_producto = silo.tipo_permitido or None

            db.session.commit()
            flash('Salida registrada correctamente.', 'success')
            return redirect(url_for('index'))
        except ValueError as e:
            db.session.rollback()
            flash(f'Error: {str(e)}', 'danger')
        except Exception as e:
            db.session.rollback()
            if e.__class__.__name__ in ('InvalidOperation', 'DivisionUndefined', 'DivisionImpossible', 'DivisionByZero'):
                flash('Error: cantidad de galones inválida.', 'danger')
                return redirect(url_for('registrar_salida'))
            # Mensaje de error amigable en español
            error_msg = 'Ocurrió un error al registrar la salida. Por favor intenta nuevamente.'
            if 'suficientes' in str(e).lower():
                error_msg = str(e)
            elif 'silo' in str(e).lower():
                error_msg = 'Error: Problema con el silo seleccionado.'
            flash(error_msg, 'danger')

    # Obtener solo silos activos que tienen inventario
    silos_activos = Silo.query.filter_by(estado='activo').all()
    silos_con_inventario = []
    
    for silo in silos_activos:
        inventario = InventarioSilo.query.filter_by(id_silo=silo.id_silo).all()
        if sum(float(item.galones) for item in inventario) > 0:
            silos_con_inventario.append(silo)
    
    return render_template('salida.html', silos=silos_con_inventario)

@app.route('/historial')
@login_required
def historial():
    query = Movimiento.query
    
    # Filtros
    id_silo = request.args.get('id_silo')
    tipo = request.args.get('tipo')
    fecha_inicio = request.args.get('fecha_inicio')
    fecha_fin = request.args.get('fecha_fin')
    codigo_lote = request.args.get('codigo_lote')
    tipo_producto = request.args.get('tipo_producto')
    
    if id_silo:
        query = query.filter_by(id_silo=id_silo)
    if tipo:
        if tipo == 'reproceso':
            query = query.filter(or_(
                Movimiento.tipo_movimiento == 'reproceso',
                and_(
                    Movimiento.tipo_movimiento == '',
                    or_(Movimiento.observaciones.is_(None), ~Movimiento.observaciones.contains('Cambio de estado'))
                )
            ))
        elif tipo == 'cambio_estado':
            query = query.filter(or_(
                Movimiento.tipo_movimiento == 'cambio_estado',
                and_(
                    Movimiento.tipo_movimiento == '',
                    Movimiento.observaciones.contains('Cambio de estado')
                )
            ))
        else:
            query = query.filter_by(tipo_movimiento=tipo)
    if fecha_inicio:
        dt_inicio = datetime.strptime(fecha_inicio, '%Y-%m-%d')
        query = query.filter(Movimiento.fecha_movimiento >= dt_inicio)
    if fecha_fin:
        dt_fin = datetime.strptime(fecha_fin, '%Y-%m-%d') + timedelta(days=1)
        query = query.filter(Movimiento.fecha_movimiento < dt_fin)
    if codigo_lote:
        query = query.join(Lote).filter(Lote.codigo_lote.contains(codigo_lote))
    if tipo_producto:
        query = query.join(Silo).filter(Silo.tipo_producto.contains(tipo_producto))
        
    movimientos = query.order_by(Movimiento.fecha_movimiento.desc()).all()
    silos = Silo.query.all()
    tipos_producto = sorted({(s.tipo_producto or '').strip() for s in silos if (s.tipo_producto or '').strip()})
    
    return render_template('historial.html', movimientos=movimientos, silos=silos, tipos_producto=tipos_producto)

@app.route('/historial/exportar')
@login_required
def exportar_historial():
    query = Movimiento.query
    id_silo = request.args.get('id_silo')
    tipo = request.args.get('tipo')
    fecha_inicio = request.args.get('fecha_inicio')
    fecha_fin = request.args.get('fecha_fin')
    codigo_lote = request.args.get('codigo_lote')
    tipo_producto = request.args.get('tipo_producto')
    
    if id_silo:
        query = query.filter_by(id_silo=id_silo)
    if tipo:
        if tipo == 'reproceso':
            query = query.filter(or_(
                Movimiento.tipo_movimiento == 'reproceso',
                and_(
                    Movimiento.tipo_movimiento == '',
                    or_(Movimiento.observaciones.is_(None), ~Movimiento.observaciones.contains('Cambio de estado'))
                )
            ))
        elif tipo == 'cambio_estado':
            query = query.filter(or_(
                Movimiento.tipo_movimiento == 'cambio_estado',
                and_(
                    Movimiento.tipo_movimiento == '',
                    Movimiento.observaciones.contains('Cambio de estado')
                )
            ))
        else:
            query = query.filter_by(tipo_movimiento=tipo)
    if fecha_inicio:
        dt_inicio = datetime.strptime(fecha_inicio, '%Y-%m-%d')
        query = query.filter(Movimiento.fecha_movimiento >= dt_inicio)
    if fecha_fin:
        dt_fin = datetime.strptime(fecha_fin, '%Y-%m-%d') + timedelta(days=1)
        query = query.filter(Movimiento.fecha_movimiento < dt_fin)
    if codigo_lote:
        query = query.join(Lote).filter(Lote.codigo_lote.contains(codigo_lote))
    if tipo_producto:
        query = query.join(Silo).filter(Silo.tipo_producto.contains(tipo_producto))

    movimientos = query.order_by(Movimiento.fecha_movimiento.desc()).all()
    
    data = []
    for m in movimientos:
        tipo_norm = m.tipo_movimiento or ''
        if not tipo_norm:
            if (m.observaciones or '').find('Cambio de estado') != -1:
                tipo_norm = 'cambio_estado'
            else:
                tipo_norm = 'reproceso'
        data.append({
            'Fecha': m.fecha_movimiento.strftime('%Y-%m-%d %H:%M'),
            'Tipo': tipo_norm.replace('_', ' ').title(),
            'Silo': m.silo.nombre_silo if m.silo else '',
            'Lote': m.lote.codigo_lote if m.lote else '',
            'Galones': float(m.galones),
            'Usuario': m.usuario.usuario,
            'Observaciones': m.observaciones
        })
    
    df = pd.DataFrame(data)
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Movimientos')
    
    output.seek(0)
    
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=f'historial_movimientos_{datetime.now().strftime("%Y%m%d_%H%M")}.xlsx'
    )

@app.route('/admin/usuarios')
@login_required
def gestionar_usuarios():
    if current_user.rol != 'administrador':
        flash('Acceso denegado.')
        return redirect(url_for('index'))
    usuarios = Usuario.query.all()
    return render_template('admin/usuarios.html', usuarios=usuarios)

@app.route('/admin/usuarios/nuevo', methods=['GET', 'POST'])
@login_required
def nuevo_usuario():
    if current_user.rol != 'administrador':
        flash('Acceso denegado.')
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        nombre = request.form.get('nombre')
        usuario = request.form.get('usuario')
        password = request.form.get('password')
        rol = request.form.get('rol')
        
        if Usuario.query.filter_by(usuario=usuario).first():
            flash('El nombre de usuario ya existe.')
        else:
            nuevo = Usuario(
                nombre=nombre,
                usuario=usuario,
                password=generate_password_hash(password),
                rol=rol
            )
            db.session.add(nuevo)
            db.session.commit()
            flash('Usuario creado correctamente.')
            return redirect(url_for('gestionar_usuarios'))
            
    return render_template('admin/usuario_form.html', usuario=None)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        usuario = request.form.get('usuario')
        password = request.form.get('password')
        user = Usuario.query.filter_by(usuario=usuario).first()
        
        if user and check_password_hash(user.password, password):
            if user.activo:
                login_user(user)
                return redirect(url_for('index'))
            else:
                flash('Usuario inactivo. Contacte al administrador.')
        else:
            flash('Usuario o contraseña incorrectos.')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/reset-silos')
@login_required
def reset_silos():
    if _deny_if_guest():
        return redirect(url_for('index'))
    try:
        silos = Silo.query.all()
        for silo in silos:
            silo.tipo_producto = silo.tipo_permitido or None
        
        db.session.commit()
        flash(f'Se reseteó el tipo de producto para {len(silos)} silos correctamente!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error: {str(e)}', 'danger')
    
    return redirect(url_for('index'))

@app.route('/reproceso', methods=['GET', 'POST'])
@login_required
def registrar_reproceso():
    if _deny_if_guest():
        return redirect(url_for('index'))
    if request.method == 'POST':
        try:
            codigo_lote = request.form.get('codigo_lote')
            galones = float(request.form.get('galones'))
            nuevo_estado = request.form.get('nuevo_estado')
            observaciones = request.form.get('observaciones')
            fecha_embarque = request.form.get('fecha_embarque') or ''
            estatus = request.form.get('estatus') or ''
            fecha_hora_cita = request.form.get('fecha_hora_cita') or ''
            fecha_hora_registro_llegada = request.form.get('fecha_hora_registro_llegada') or ''
            fecha_hora_entrada_planta = request.form.get('fecha_hora_entrada_planta') or ''
            fecha_hora_salida_planta = request.form.get('fecha_hora_salida_planta') or ''
            numero_economico_placa = (request.form.get('numero_economico_placa') or '').strip()
            tipo_unidad = (request.form.get('tipo_unidad') or '').strip()
            linea_transportista = (request.form.get('linea_transportista') or '').strip()
            operador = (request.form.get('operador') or '').strip()
            sellos = (request.form.get('sellos') or '').strip()
            sello_valvula = (request.form.get('sello_valvula') or '').strip()
            turno = (request.form.get('turno') or '').strip()
            comentarios = (request.form.get('comentarios') or '').strip()
            
            # Buscar el lote
            lote = Lote.query.filter_by(codigo_lote=codigo_lote).first()
            if not lote:
                flash(f'Error: No se encontró el lote {codigo_lote}', 'danger')
                return redirect(url_for('registrar_reproceso'))
            
            # Verificar que exista inventario de ese lote
            inventario_items = InventarioSilo.query.filter_by(id_lote=lote.id_lote).all()
            total_inventario_lote = sum(float(item.galones) for item in inventario_items)
            
            if total_inventario_lote < galones:
                flash(f'Error: Solo hay {total_inventario_lote:.2f} galones disponibles en el lote', 'danger')
                return redirect(url_for('registrar_reproceso'))
            
            # Actualizar el estado del lote
            estado_anterior = lote.estado.nombre_estado if lote.estado else ''
            nuevo_estado_obj = EstadoProducto.query.get(nuevo_estado)
            nuevo_estado_nombre = nuevo_estado_obj.nombre_estado if nuevo_estado_obj else ''
            lote.id_estado = nuevo_estado
            
            # Registrar movimiento de reproceso
            payload = {
                'tipo': 'reproceso',
                'estado_anterior': estado_anterior,
                'estado_nuevo': nuevo_estado_nombre,
                'motivo': observaciones or '',
                'fecha_embarque': fecha_embarque,
                'estatus': estatus,
                'fecha_hora_cita': fecha_hora_cita,
                'fecha_hora_registro_llegada': fecha_hora_registro_llegada,
                'fecha_hora_entrada_planta': fecha_hora_entrada_planta,
                'fecha_hora_salida_planta': fecha_hora_salida_planta,
                'numero_economico_placa': numero_economico_placa,
                'tipo_unidad': tipo_unidad,
                'linea_transportista': linea_transportista,
                'operador': operador,
                'sellos': sellos,
                'sello_valvula': sello_valvula,
                'turno': turno,
                'comentarios': comentarios
            }
            movimiento = Movimiento(
                tipo_movimiento='reproceso',
                id_silo=inventario_items[0].id_silo if inventario_items else None,
                id_lote=lote.id_lote,
                galones=galones,
                id_usuario=current_user.id_usuario,
                observaciones=json.dumps(payload, ensure_ascii=False)
            )
            db.session.add(movimiento)
            
            db.session.commit()
            flash('Reproceso registrado correctamente!', 'success')
            return redirect(url_for('registrar_reproceso'))
        except Exception as e:
            db.session.rollback()
            # Mensaje de error amigable en español
            error_msg = 'Ocurrió un error al cambiar el estado del lote. Por favor intenta nuevamente.'
            if 'lote' in str(e).lower():
                error_msg = 'Error: No se encontró el lote especificado.'
            flash(error_msg, 'danger')
    
    # Obtener lotes que tienen inventario
    lotes_con_inventario = []
    inventario_items = InventarioSilo.query.all()
    seen_lotes = set()
    
    for item in inventario_items:
        if item.id_lote not in seen_lotes:
            seen_lotes.add(item.id_lote)
            # Calcular total de galones para este lote
            total_galones_lote = sum(float(i.galones) for i in InventarioSilo.query.filter_by(id_lote=item.id_lote).all())
            lotes_con_inventario.append({
                'lote': item.lote,
                'total_galones': total_galones_lote
            })
    
    estados = EstadoProducto.query.all()

    f_lote = (request.args.get('f_lote') or '').strip()
    f_fecha_inicio = request.args.get('f_fecha_inicio') or ''
    f_fecha_fin = request.args.get('f_fecha_fin') or ''
    f_placa = (request.args.get('f_placa') or '').strip().lower()

    q = Movimiento.query.filter(Movimiento.tipo_movimiento == 'reproceso')
    if f_lote:
        q = q.join(Lote).filter(Lote.codigo_lote.contains(f_lote))
    if f_fecha_inicio:
        dt_inicio = datetime.strptime(f_fecha_inicio, '%Y-%m-%d')
        q = q.filter(Movimiento.fecha_movimiento >= dt_inicio)
    if f_fecha_fin:
        dt_fin = datetime.strptime(f_fecha_fin, '%Y-%m-%d') + timedelta(days=1)
        q = q.filter(Movimiento.fecha_movimiento < dt_fin)
    movimientos_reproceso = q.order_by(Movimiento.fecha_movimiento.desc()).limit(200).all()

    reprocesos = []
    for m in movimientos_reproceso:
        data = _parse_json_dict(m.observaciones)
        placa_val = (data.get('numero_economico_placa') or '').strip().lower()
        if f_placa and f_placa not in placa_val:
            continue
        reprocesos.append({'mov': m, 'data': data})
    
    return render_template(
        'reproceso.html',
        lotes=lotes_con_inventario,
        estados=estados,
        reprocesos=reprocesos
    )

# =====================================================================
# ===== MÓDULO EMBARQUES - LÓGICA Y RUTAS ===========================
# =====================================================================
# Convenciones:
#   - Toda validación que se hace en el navegador se repite en el servidor.
#   - Los catálogos solo muestran registros activos=True.
#   - Los números/códigos se normalizan (strip + mayúsculas cuando corresponde.
#   - Los errores se devuelven con flash en lugar de dejar que el DB lanze excepción 500
#     con mensaje claro al usuario (unicidad de sello, cita repetida, desorden tiempos).
# =====================================================================

# Expresiones regulares de negocio (observadas del Excel de referencia).
REGEX_NUM_CITA = re.compile(r'^2101-CITA-\d{6}$')
REGEX_NUM_ORDEN = re.compile(r'^(2101-OT|2101-OV|1101-OV)\d{6}$')
REGEX_TICKET = re.compile(r'^ALA\d{7}$')
REGEX_PACKING = re.compile(r'^2101-\d{6}$')
REGEX_CODIGO_LOTE = re.compile(r'^\d{3}-\d{8}-\d{6}$')

# Nombres de catálogos permitidos en la ruta genérica de administración.
# El primer valor = nombre_tabla, el segundo = clase SQLAlchemy + metadatos.
CATALOGOS_EMBARQUES = {
    'productos_embarque': {
        'model': ProductoEmbarque,
        'nombre_visible': 'Productos de embarque',
        'campos': [
            ('item', 'Item (código único)', 'text', True),
            ('descripcion', 'Descripción', 'text', True),
            ('variedad', 'Variedad', 'text', False),
            ('tipo', 'Tipo',
             ('enum', ['concentrado','pulpa','colateral'],
                     ['Concentrado','Pulpa','Colateral']), True),
            ('unidad_medida', 'Unidad de medida',
             ('enum', ['KG','TAZ'], ['KG','TAZ']), True),
        ],
    },
    'transportistas': {
        'model': Transportista,
        'nombre_visible': 'Transportistas',
        'campos': [
            ('nombre', 'Nombre', 'text', True),
        ],
    },
    'operadores': {
        'model': Operador,
        'nombre_visible': 'Operadores',
        'campos': [
            ('nombre', 'Nombre completo', 'text', True),
            ('id_transportista', 'Transportista (opcional)', 'fk:transportistas', False),
        ],
    },
    'unidades_transporte': {
        'model': UnidadTransporte,
        'nombre_visible': 'Unidades de transporte',
        'campos': [
            ('placa', 'Placa o número económico', 'text', True),
            ('tipo', 'Tipo',
             ('enum', ['tractor','remolque'], ['Tractor','Remolque']), True),
        ],
    },
    'lavaderos': {
        'model': Lavadero,
        'nombre_visible': 'Lavaderos',
        'campos': [
            ('nombre', 'Nombre', 'text', True),
        ],
    },
    'facilitadores': {
        'model': Facilitador,
        'nombre_visible': 'Facilitadores',
        'campos': [
            ('nombre', 'Nombre', 'text', True),
        ],
    },
}


def _validar_y_normalizar_texto(valor, mayusculas=True):
    """
    Normaliza un valor de formulario: recorta espacios y opcionalmente pasa a mayúsculas.
    Devuelve None si la cadena queda vacía.

    Parámetros:
        valor: str o None.
        mayusculas: bool indica si se pasa a mayúsculas.

    Devuelve:
        str normalizado o None.
    """
    if valor is None:
        return None
    s = str(valor).strip()
    if not s:
        return None
    return s.upper() if mayusculas else s


def _parse_datetime_or_none(texto, fmt='%Y-%m-%dT%H:%M'):
    """
    Parsea una cadena a datetime con el formato dado o devuelve None si es vacía/inválida.

    Regla: los inputs HTML datetime-local renderizan "YYYY-MM-DDTHH:MM".
    """
    if not texto:
        return None
    try:
        return datetime.strptime(texto.strip(), fmt)
    except Exception:
        return None


def _parse_date_or_none(texto):
    """Parsea fecha YYYY-MM-DD o devuelve None si es vacía/inválida."""
    if not texto:
        return None
    try:
        return datetime.strptime(texto.strip(), '%Y-%m-%d').date()
    except Exception:
        return None


def _parse_decimal_or_none(texto):
    """Convierte texto a Decimal o devuelve None."""
    if texto is None or str(texto).strip() == '':
        return None
    try:
        return Decimal(str(texto).strip())
    except Exception:
        return None


def _parse_int_or_none(texto):
    """Convierte texto a int o devuelve None."""
    if texto is None or str(texto).strip() == '':
        return None
    try:
        return int(str(texto).strip())
    except Exception:
        return None


def _formatear_timedelta(td):
    """Formatea un timedelta a "5 h 12 min" o cadena vacía si es None."""
    if td is None:
        return ''
    total_segundos = int(td.total_seconds())
    if total_segundos < 0:
        total_segundos = 0
    horas, resto = divmod(total_segundos, 3600)
    minutos = resto // 60
    if horas and minutos:
        return f'{horas} h {minutos} min'
    if horas:
        return f'{horas} h'
    return f'{minutos} min'


def _separar_sellos(texto):
    """
    Separa una cadena de sellos en una lista.
    Se aceptan separadores: coma, barra /, guion -, espacio, salto de línea.
    Se eliminan duplicados y cadenas vacías.
    """
    if not texto:
        return []
    partes = re.split(r'[,/\-\s]+', texto.strip())
    limpias = [p for p in partes if p]
    return list(dict.fromkeys(limpias))


def _construir_query_embarques(filtros):
    """
    Construye el query de SQLAlchemy para el listado de embarques aplicando filtros.

    Parámetros filtros (dict):
        fecha_desde, fecha_hasta, id_producto, tipo_unidad, texto_libre.

    Devuelve:
        Query de Embarque con joins y filtros aplicados.
    """
    q = Embarque.query

    if filtros.get('fecha_desde'):
        q = q.filter(Embarque.fecha_embarque >= filtros['fecha_desde'])
    if filtros.get('fecha_hasta'):
        q = q.filter(Embarque.fecha_embarque <= filtros['fecha_hasta'])
    if filtros.get('id_producto'):
        q = q.filter(Embarque.id_producto == filtros['id_producto'])
    if filtros.get('tipo_unidad'):
        q = q.filter(Embarque.tipo_unidad == filtros['tipo_unidad'])

    texto = (filtros.get('texto_libre') or '').strip()
    if texto:
        # Texto libre busca en num_cita, ticket, packing y códigos de lote.
        q = q.outerjoin(EmbarqueLote).outerjoin(Lote)
        q = q.filter(or_(
            Embarque.num_cita.contains(texto),
            Embarque.ticket.contains(texto),
            Embarque.packing.contains(texto),
            Lote.codigo_lote.contains(texto),
        ))
    return q


# =====================================================================
# Rutas públicas de embarques (listado, detalle, nuevo, editar, cancelar, exportar)
# =====================================================================

@app.route('/embarques')
@login_required
def listar_embarques():
    """
    Listado de embarques con filtros, paginación de 25 y 3 tarjetas resumen.
    Filtros: fecha desde/hasta, producto, tipo_unidad, texto libre (cita/ticket/lote).
    """
    # --- Leer filtros de la URL ---
    fecha_desde = _parse_date_or_none(request.args.get('fecha_desde'))
    fecha_hasta = _parse_date_or_none(request.args.get('fecha_hasta'))
    id_producto = _parse_int_or_none(request.args.get('id_producto'))
    tipo_unidad = (request.args.get('tipo_unidad') or '').strip() or None
    texto_libre = (request.args.get('texto_libre') or '').strip() or None
    pagina = max(1, _parse_int_or_none(request.args.get('pagina')) or 1)
    por_pagina = 25

    filtros = {
        'fecha_desde': fecha_desde,
        'fecha_hasta': fecha_hasta,
        'id_producto': id_producto,
        'tipo_unidad': tipo_unidad,
        'texto_libre': texto_libre,
    }

    # --- Tarjetas resumen (aplican filtros de fecha) ---
    hoy = datetime.today().date()
    inicio_mes = hoy.replace(day=1)
    q_mes = Embarque.query.filter(
        Embarque.estatus != 'cancelado',
        Embarque.fecha_embarque >= inicio_mes,
    )
    total_mes = q_mes.count()
    embarques_mes = q_mes.options(db.joinedload(Embarque.lotes)).all()
    kg_embarcados = Decimal('0')
    for emb in embarques_mes:
        if emb.producto and emb.producto.unidad_medida == 'KG':
            kg_embarcados += emb.cantidad_total

    # Tiempo medio en planta (solo embarques con tiempos completos en el mes)
    tiempos_tds = []
    for emb in embarques_mes:
        if emb.tiempos and emb.tiempos.tiempo_en_planta:
            tiempos_tds.append(emb.tiempos.tiempo_en_planta.total_seconds())
    tiempo_medio_seg = (sum(tiempos_tds) / len(tiempos_tds)) if tiempos_tds else 0
    if tiempo_medio_seg > 0:
        h, r = divmod(int(tiempo_medio_seg), 3600)
        m = r // 60
        tiempo_medio_texto = f'{h} h {m} min'
    else:
        tiempo_medio_texto = '0 min'

    # --- Paginación del listado con filtros ---
    q = _construir_query_embarques(filtros)
    q = q.order_by(Embarque.fecha_embarque.desc(), Embarque.id_embarque.desc())
    paginacion = q.paginate(page=pagina, per_page=por_pagina, error_out=False)
    embarques = paginacion.items

    # Catálogos para filtros
    productos = ProductoEmbarque.query.filter_by(activo=True).order_by(ProductoEmbarque.descripcion).all()
    tipos_unidad = [k for k in TIPO_UNIDAD_GRUPO.keys()]
    tipos_unidad_labels = {
        'pipa_jumbo': 'Pipa jumbo',
        'pipa_chica': 'Pipa chica',
        'isotanque': 'Isotanque',
        'flexitanque': 'Flexitanque',
        'caja_refrigerada': 'Caja refrigerada',
        'caja_seca': 'Caja seca',
        'trailer': 'Tráiler',
        'tambores': 'Tambores',
    }

    return render_template(
        'embarques/listado.html',
        embarques=embarques,
        paginacion=paginacion,
        filtros=filtros,
        productos=productos,
        tipos_unidad=tipos_unidad,
        tipos_unidad_labels=tipos_unidad_labels,
        resumen={
            'total_mes': total_mes,
            'kg_embarcados': f'{float(kg_embarcados):,.2f}',
            'tiempo_medio': tiempo_medio_texto,
        },
        formatear_timedelta=_formatear_timedelta,
    )


def _cargar_catalogos_formulario():
    """
    Devuelve un diccionario con los catálogos activos usados por el formulario
    de captura/edición de embarques.
    """
    return {
        'productos': ProductoEmbarque.query.filter_by(activo=True).order_by(ProductoEmbarque.descripcion).all(),
        'clientes': Cliente.query.order_by(func.coalesce(Cliente.codigo, Cliente.nombre_cliente)).all(),
        'transportistas': Transportista.query.filter_by(activo=True).order_by(Transportista.nombre).all(),
        'operadores': Operador.query.filter_by(activo=True).order_by(Operador.nombre).all(),
        'tractores': UnidadTransporte.query.filter_by(activo=True, tipo='tractor').order_by(UnidadTransporte.placa).all(),
        'remolques': UnidadTransporte.query.filter_by(activo=True, tipo='remolque').order_by(UnidadTransporte.placa).all(),
        'lavaderos': Lavadero.query.filter_by(activo=True).order_by(Lavadero.nombre).all(),
        'facilitadores': Facilitador.query.filter_by(activo=True).order_by(Facilitador.nombre).all(),
    }


def _validar_embarque_form(datos, lotes_info, tiempos_obj, embarque_actual=None):
    """
    Realiza todas las validaciones del servidor del formulario de embarque.

    Parámetros:
        datos: dict con campos del embarque ya normalizados.
        lotes_info: lista de tuplas (id_lote, cantidad, lote_obj_existente).
        tiempos_obj: instancia de EmbarqueTiempos.
        embarque_actual: Embarque existente (para edición; excluye su ID en validaciones
                        de unicidad).

    Devuelve:
        (ok: bool, errores: list[str])
    """
    errores = []

    # --- Reglas regex (num_cita, num_orden, ticket, packing)
    if not datos['num_cita']:
        errores.append('Número de cita es obligatorio.')
    elif not REGEX_NUM_CITA.match(datos['num_cita']):
        errores.append('Número de cita no cumple el formato. Usa: 2101-CITA-000000.')
    else:
        # Unicidad (salvo el propio embarque en edición)
        q = Embarque.query.filter_by(num_cita=datos['num_cita'])
        if embarque_actual:
            q = q.filter(Embarque.id_embarque != embarque_actual.id_embarque)
        if q.first():
            errores.append('El número de cita ya está registrado en otro embarque.')

    if not datos['num_orden']:
        errores.append('Número de orden es obligatorio.')
    elif not REGEX_NUM_ORDEN.match(datos['num_orden']):
        errores.append('Número de orden no cumple el formato. Usa: 2101-OT000000, 2101-OV000000 o 1101-OV000000.')

    if datos['ticket']:
        if not REGEX_TICKET.match(datos['ticket']):
            errores.append('Ticket no cumple el formato. Usa: ALA0000000 (7 dígitos).')
        else:
            q = Embarque.query.filter_by(ticket=datos['ticket'])
            if embarque_actual:
                q = q.filter(Embarque.id_embarque != embarque_actual.id_embarque)
            if q.first():
                errores.append('El ticket ya está registrado en otro embarque.')

    if datos['packing']:
        if not REGEX_PACKING.match(datos['packing']):
            errores.append('Packing no cumple el formato. Usa: 2101-000000.')
        else:
            q = Embarque.query.filter_by(packing=datos['packing'])
            if embarque_actual:
                q = q.filter(Embarque.id_embarque != embarque_actual.id_embarque)
            if q.first():
                errores.append('El packing ya está registrado en otro embarque.')

    # Turno
    if datos['turno'] not in (1, 2, 3):
        errores.append('Turno debe ser 1, 2 o 3.')

    # Fecha de embarque: no futura y no anterior a fecha de cualquier lote
    hoy = datetime.today().date()
    if datos['fecha_embarque'] and datos['fecha_embarque'] > hoy:
        errores.append('La fecha de embarque no puede ser futura.')
    if datos['fecha_embarque'] and lotes_info:
        for _idl, _cant, lote_obj in lotes_info:
            if lote_obj and lote_obj.fecha_lote and lote_obj.fecha_lote > datos['fecha_embarque']:
                errores.append(
                    f'La fecha del lote {lote_obj.codigo_lote} ({lote_obj.fecha_lote.strftime("%d/%m/%Y")}) '
                    f'es posterior a la fecha de embarque.'
                )

    # Tiempos: orden cronológico
    if tiempos_obj:
        ok_t, msg_t = tiempos_obj.tiempos_ordenados()
        if not ok_t:
            errores.append(msg_t)

    # Lotes: deben existir y cantidad > 0
    if not lotes_info:
        errores.append('Debes agregar al menos un lote con su cantidad.')
    total_lotes = Decimal('0')
    ids_lotes_vistos = set()
    for id_lote, cantidad, lote_obj in lotes_info:
        if not lote_obj:
            errores.append(f'Lote {id_lote} no existe en el catálogo de lotes.')
            continue
        if lote_obj.id_lote in ids_lotes_vistos:
            errores.append(f'El lote {lote_obj.codigo_lote} está repetido en la lista.')
            continue
        ids_lotes_vistos.add(lote_obj.id_lote)
        if not REGEX_CODIGO_LOTE.match(lote_obj.codigo_lote):
            # Solo advertencia si no cumple el formato actual; el lote existe pero fue
            # creado con reglas antiguas. No bloqueamos.
            pass
        if not isinstance(cantidad, Decimal) or cantidad <= 0:
            errores.append(f'La cantidad del lote {lote_obj.codigo_lote} debe ser mayor a 0.')
        total_lotes += cantidad or Decimal('0')
    # (Regla inventario: la cantidad no debe superar el inventario disponible del lote.
    # Aquí confirmamos con el usuario antes de continuar. Si la suma no supera los galones
    # disponibles en inventario_silos convertidos a KG? Como no conocemos densidad
    # exacta (Fase 5), validamos que haya al menos inventario > 0.
    for id_lote, cantidad, lote_obj in lotes_info:
        if not lote_obj:
            continue
        total_inv = (
            db.session.query(db.func.coalesce(db.func.sum(InventarioSilo.galones), 0))
            .filter(InventarioSilo.id_lote == lote_obj.id_lote)
            .scalar()
        )
        if float(total_inv or 0) <= 0:
            errores.append(
                f'El lote {lote_obj.codigo_lote} no tiene inventario disponible en silos.'
            )

    return len(errores) == 0, errores


def _guardar_embarque_desde_form(embarque, request_form, es_nuevo, id_embarque_actual=None):
    """
    Construye/actualiza un Embarque + hijas desde request.form, valida y guarda.
    Devuelve (ok: bool, mensajes: list[str]). Si hay error hace rollback.

    Parámetros:
        embarque: instancia nueva o existente de Embarque.
        request_form: request.form del request actual.
        es_nuevo: True si es alta, False si edición.
        id_embarque_actual: id del embarque actual (para saltar unicidad propia).
    """
    try:
        # 1) Normalizar campos principales
        datos = {
            'fecha_embarque': _parse_date_or_none(request_form.get('fecha_embarque')),
            'estatus': (request_form.get('estatus') or 'cargado').strip() or 'cargado',
            'num_cita': _validar_y_normalizar_texto(request_form.get('num_cita')),
            'num_orden': _validar_y_normalizar_texto(request_form.get('num_orden')),
            'ticket': _validar_y_normalizar_texto(request_form.get('ticket')),
            'packing': _validar_y_normalizar_texto(request_form.get('packing')),
            'turno': _parse_int_or_none(request_form.get('turno')),
        }

        # 2) Asignar campos directos al embarque (FK y valores numéricos)
        if datos['fecha_embarque']:
            embarque.fecha_embarque = datos['fecha_embarque']
        embarque.num_cita = datos['num_cita']
        embarque.num_orden = datos['num_orden']
        embarque.ticket = datos['ticket']
        embarque.packing = datos['packing']
        embarque.estatus = datos['estatus'] if datos['estatus'] in (
            'programado', 'en_planta', 'cargado', 'cancelado') else 'cargado'
        embarque.id_producto = _parse_int_or_none(request_form.get('id_producto'))
        embarque.id_cliente = _parse_int_or_none(request_form.get('id_cliente'))
        tipo_unidad = (request_form.get('tipo_unidad') or '').strip()
        if tipo_unidad in TIPO_UNIDAD_GRUPO:
            embarque.tipo_unidad = tipo_unidad
        embarque.id_transportista = _parse_int_or_none(request_form.get('id_transportista'))
        embarque.id_operador = _parse_int_or_none(request_form.get('id_operador'))
        embarque.id_tractor = _parse_int_or_none(request_form.get('id_tractor'))
        embarque.id_remolque = _parse_int_or_none(request_form.get('id_remolque'))
        embarque.turno = datos['turno']
        if not 1 <= (embarque.turno or 0) <= 3:
            embarque.turno = datos['turno'] or 1
        temp_c = _parse_decimal_or_none(request_form.get('temperatura_c'))
        embarque.temperatura_c = temp_c
        embarque.id_facilitador = _parse_int_or_none(request_form.get('id_facilitador'))
        embarque.observaciones = _validar_y_normalizar_texto(
            request_form.get('observaciones'), mayusculas=False)

        # Auditoría
        if es_nuevo:
            embarque.id_capturista = current_user.id_usuario
        embarque.actualizado_por = current_user.id_usuario

        # 3) Tiempos
        tiempos = embarque.tiempos or EmbarqueTiempos()
        tiempos.llegada = _parse_datetime_or_none(request_form.get('t_llegada'))
        tiempos.entrada = _parse_datetime_or_none(request_form.get('t_entrada'))
        tiempos.pesado_inicial = _parse_datetime_or_none(request_form.get('t_pesado_inicial'))
        tiempos.pesaje_salida = _parse_datetime_or_none(request_form.get('t_pesaje_salida'))
        tiempos.documentacion = _parse_datetime_or_none(request_form.get('t_documentacion'))
        tiempos.salida = _parse_datetime_or_none(request_form.get('t_salida'))
        embarque.tiempos = tiempos

        # Determinar estatus en base a tiempos
        if embarque.estatus != 'cancelado':
            if tiempos.completos():
                embarque.estatus = 'cargado'
            else:
                embarque.estatus = 'en_planta'

        # 4) Detalle opcional según grupo_unidad
        grupo = TIPO_UNIDAD_GRUPO.get(embarque.tipo_unidad, '')
        detalle = embarque.detalle
        if grupo in ('pipa', 'tambor'):
            if not detalle:
                detalle = EmbarqueDetalle()
                embarque.detalle = detalle
        if grupo == 'pipa':
            detalle.id_lavadero = _parse_int_or_none(request_form.get('id_lavadero'))
            detalle.check_list = None
            detalle.lote_tambor = None
        elif grupo == 'tambor':
            detalle.id_lavadero = None
            detalle.check_list = request_form.get('check_list') == 'on' or request_form.get('check_list') in (1, '1', 'true', 'True')
            detalle.lote_tambor = _validar_y_normalizar_texto(request_form.get('lote_tambor'))
        elif grupo == 'caja':
            # Para caja no hay campos en detalle; temperatura va en embarque.
            if detalle:
                detalle.id_lavadero = None
                detalle.check_list = None
                detalle.lote_tambor = None
        else:
            if detalle:
                detalle.id_lavadero = None
                detalle.check_list = None
                detalle.lote_tambor = None

        # 5) Lotes (repetidor: leer listas paralelas lotes_ids[], lotes_cantidades[])
        ids_lotes = request_form.getlist('lotes_ids[]') or []
        cants_lotes = request_form.getlist('lotes_cantidades[]') or []
        lotes_info = []
        for i in range(max(len(ids_lotes), len(cants_lotes))):
            id_l = _parse_int_or_none(ids_lotes[i]) if i < len(ids_lotes) else None
            canti = _parse_decimal_or_none(cants_lotes[i]) if i < len(cants_lotes) else None
            if not id_l:
                continue
            lote_obj = Lote.query.get(id_l)
            lotes_info.append((id_l, canti, lote_obj))

        # 6) Validar todo antes de guardar
        ok, errores = _validar_embarque_form(datos, lotes_info, tiempos, embarque if not es_nuevo else None)
        if not ok:
            for msg in errores:
                flash(msg, 'danger')
            return False, errores

        # 7) Validación previa de unicidad global de sellos (para no dar error 500)
        #    Recolectar números de sellos por tipo.
        sellos_por_tipo = {}
        if grupo == 'pipa':
            sellos_por_tipo['lavado'] = _separar_sellos(request_form.get('sellos_lavado'))
            s_valvula = _validar_y_normalizar_texto(request_form.get('sello_valvula'))
            if s_valvula:
                sellos_por_tipo['valvula'] = [s_valvula]
            else:
                sellos_por_tipo['valvula'] = []
            sellos_por_tipo['escotilla'] = _separar_sellos(request_form.get('sellos_escotilla'))
        elif grupo == 'caja':
            sellos_por_tipo['puerta_trasera'] = _separar_sellos(request_form.get('sellos_puerta_trasera'))
        else:
            sellos_por_tipo = {}

        todos_numeros = []
        for _tipo, numeros in sellos_por_tipo.items():
            todos_numeros.extend(numeros)
        # Duplicados internos
        if len(todos_numeros) != len(set(todos_numeros)):
            flash('Hay números de sello duplicados dentro del mismo embarque.', 'danger')
            return False, []
        # Unicidad global
        if todos_numeros:
            q_existentes = EmbarqueSello.query.filter(EmbarqueSello.numero.in_(todos_numeros))
            if id_embarque_actual:
                q_existentes = q_existentes.filter(EmbarqueSello.id_embarque != id_embarque_actual)
            duplicado = q_existentes.first()
            if duplicado:
                flash(f'El número de sello {duplicado.numero} ya existe en otro embarque.', 'danger')
                return False, []

        # --- Todo OK, persistir
        if es_nuevo:
            db.session.add(embarque)
        db.session.flush()  # obtener id_embarque

        # 8) Reemplazar lista de lotes
        if id_embarque_actual:
            # Limpiar lotes previos
            EmbarqueLote.query.filter_by(id_embarque=id_embarque_actual).delete(synchronize_session=False)
        for id_lote, cantidad, lote_obj in lotes_info:
            if cantidad is None or cantidad <= 0:
                continue
            el = EmbarqueLote(id_embarque=embarque.id_embarque, id_lote=id_lote, cantidad=cantidad)
            db.session.add(el)

        # 9) Reemplazar sellos
        if id_embarque_actual:
            EmbarqueSello.query.filter_by(id_embarque=id_embarque_actual).delete(synchronize_session=False)
        for tipo_s, numeros in sellos_por_tipo.items():
            for num in numeros:
                db.session.add(EmbarqueSello(
                    id_embarque=embarque.id_embarque, tipo=tipo_s, numero=num))

        db.session.commit()
        return True, []
    except Exception as e:
        db.session.rollback()
        # Captura residual para no dar error 500 (mensaje genérico + info
        flash(f'Ocurrió un error al guardar el embarque: {str(e)}', 'danger')
        return False, [str(e)]


@app.route('/embarques/nuevo', methods=['GET', 'POST'])
@login_required
def nuevo_embarque():
    """Formulario de captura de un embarque nuevo."""
    if _deny_if_guest():
        return redirect(url_for('listar_embarques'))

    if request.method == 'POST':
        embarque = Embarque()
        ok, _ = _guardar_embarque_desde_form(embarque, request.form, es_nuevo=True)
        if ok:
            flash('Embarque registrado correctamente.', 'success')
            return redirect(url_for('detalle_embarque', id_embarque=embarque.id_embarque))
        # Si falló; cae de nuevo al formulario con flash.
        # (los datos enviados se repintan via form con valores previos.
        prev_data = request.form

    catalogos = _cargar_catalogos_formulario()
    grupo_opciones = {k: (
        {
            'pipa_jumbo': 'Pipa jumbo',
            'pipa_chica': 'Pipa chica',
            'isotanque': 'Isotanque',
            'flexitanque': 'Flexitanque',
            'caja_refrigerada': 'Caja refrigerada',
            'caja_seca': 'Caja seca',
            'trailer': 'Tráiler',
            'tambores': 'Tambores',
        }[k]) for k in TIPO_UNIDAD_GRUPO.keys()}
    return render_template(
        'embarques/formulario.html',
        modo='nuevo',
        embarque=None,
        catalogos=catalogos,
        TIPO_UNIDAD_GRUPO=TIPO_UNIDAD_GRUPO,
        grupo_opciones=grupo_opciones,
        REGEX_NUM_CITA=REGEX_NUM_CITA.pattern,
        REGEX_NUM_ORDEN=REGEX_NUM_ORDEN.pattern,
        REGEX_TICKET=REGEX_TICKET.pattern,
        REGEX_PACKING=REGEX_PACKING.pattern,
    )


@app.route('/embarques/<int:id_embarque>')
@login_required
def detalle_embarque(id_embarque):
    """Vista de detalle completo de un embarque: tiempos, sellos, lotes."""
    emb = Embarque.query.get_or_404(id_embarque)
    # Preparar sellos por tipo para mostrarlos agrupados.
    sellos_por_tipo = {}
    for s in emb.sellos:
        sellos_por_tipo.setdefault(s.tipo, []).append(s.numero)
    return render_template(
        'embarques/detalle.html',
        emb=emb,
        sellos_por_tipo=sellos_por_tipo,
        formatear_timedelta=_formatear_timedelta,
        TIPO_UNIDAD_GRUPO=TIPO_UNIDAD_GRUPO,
    )


@app.route('/embarques/<int:id_embarque>/editar', methods=['GET', 'POST'])
@login_required
def editar_embarque(id_embarque):
    """Edición de embarque existente."""
    if _deny_if_guest():
        return redirect(url_for('listar_embarques'))
    emb = Embarque.query.get_or_404(id_embarque)

    if request.method == 'POST':
        ok, _ = _guardar_embarque_desde_form(
            emb, request.form, es_nuevo=False, id_embarque_actual=id_embarque)
        if ok:
            flash('Embarque actualizado correctamente.', 'success')
            return redirect(url_for('detalle_embarque', id_embarque=id_embarque))

    catalogos = _cargar_catalogos_formulario()
    grupo_opciones = {k: (
        {
            'pipa_jumbo': 'Pipa jumbo',
            'pipa_chica': 'Pipa chica',
            'isotanque': 'Isotanque',
            'flexitanque': 'Flexitanque',
            'caja_refrigerada': 'Caja refrigerada',
            'caja_seca': 'Caja seca',
            'trailer': 'Tráiler',
            'tambores': 'Tambores',
        }[k]) for k in TIPO_UNIDAD_GRUPO.keys()}
    return render_template(
        'embarques/formulario.html',
        modo='editar',
        embarque=emb,
        catalogos=catalogos,
        TIPO_UNIDAD_GRUPO=TIPO_UNIDAD_GRUPO,
        grupo_opciones=grupo_opciones,
        REGEX_NUM_CITA=REGEX_NUM_CITA.pattern,
        REGEX_NUM_ORDEN=REGEX_NUM_ORDEN.pattern,
        REGEX_TICKET=REGEX_TICKET.pattern,
        REGEX_PACKING=REGEX_PACKING.pattern,
    )


@app.route('/embarques/<int:id_embarque>/cancelar', methods=['POST'])
@login_required
def cancelar_embarque(id_embarque):
    """Cancela un embarque (solo administrador). No se borra."""
    if current_user.rol != 'administrador':
        flash('Solo el administrador puede cancelar embarques.', 'danger')
        return redirect(url_for('detalle_embarque', id_embarque=id_embarque))
    # get_or_404 FUERA del try: así lanza 404 si no existe (coherente con detalle/editar)
    emb = Embarque.query.get_or_404(id_embarque)
    try:
        emb.estatus = 'cancelado'
        emb.actualizado_por = current_user.id_usuario
        db.session.commit()
        flash('El embarque se marcó como cancelado.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error al cancelar: {str(e)}', 'danger')
    return redirect(url_for('detalle_embarque', id_embarque=id_embarque))


@app.route('/embarques/exportar')
@login_required
def exportar_embarques():
    """
    Exporta a Excel el listado de embarques con los mismos filtros que el
    /embarques activos.

    Usa pandas + openpyxl.
    """
    # Re-aplicar filtros de la URL.
    filtros = {
        'fecha_desde': _parse_date_or_none(request.args.get('fecha_desde')),
        'fecha_hasta': _parse_date_or_none(request.args.get('fecha_hasta')),
        'id_producto': _parse_int_or_none(request.args.get('id_producto')),
        'tipo_unidad': (request.args.get('tipo_unidad') or '').strip() or None,
        'texto_libre': (request.args.get('texto_libre') or '').strip() or None,
    }
    q = _construir_query_embarques(filtros).options(
        db.joinedload(Embarque.lotes).joinedload(EmbarqueLote.lote),
        db.joinedload(Embarque.producto),
        db.joinedload(Embarque.cliente),
        db.joinedload(Embarque.tractor),
        db.joinedload(Embarque.remolque),
        db.joinedload(Embarque.operador),
        db.joinedload(Embarque.transportista),
        db.joinedload(Embarque.tiempos),
    )
    embarques = q.order_by(Embarque.fecha_embarque.desc()).all()

    filas = []
    tu_labels = {
        'pipa_jumbo': 'Pipa jumbo',
        'pipa_chica': 'Pipa chica',
        'isotanque': 'Isotanque',
        'flexitanque': 'Flexitanque',
        'caja_refrigerada': 'Caja refrigerada',
        'caja_seca': 'Caja seca',
        'trailer': 'Tráiler',
        'tambores': 'Tambores',
    }
    for emb in embarques:
        prod_desc = ''
        unidad_medida = ''
        if emb.producto:
            prod_desc = f'{emb.producto.descripcion} ({emb.producto.item or ""})'.strip()
            unidad_medida = emb.producto.unidad_medida or ''
        cliente_txt = ''
        if emb.cliente:
            if emb.cliente.codigo:
                cliente_txt = f'{emb.cliente.codigo} - {emb.cliente.nombre_cliente}'
            else:
                cliente_txt = emb.cliente.nombre_cliente
        lotes_codigos = '; '.join(
            f'{el.lote.codigo_lote if el.lote else ""}' for el in emb.lotes)
        filas.append({
            'Fecha': emb.fecha_embarque.strftime('%d/%m/%Y') if emb.fecha_embarque else '',
            'Cita': emb.num_cita or '',
            'Orden': emb.num_orden or '',
            'Ticket': emb.ticket or '',
            'Packing': emb.packing or '',
            'Producto': prod_desc,
            'Cliente': cliente_txt,
            'Tipo unidad': tu_labels.get(emb.tipo_unidad, emb.tipo_unidad),
            'Cantidad total': float(emb.cantidad_total),
            'Unidad': unidad_medida,
            'Lotes': lotes_codigos,
            'Estatus': emb.estatus,
            'Turno': emb.turno,
            'Tractor': emb.tractor.placa if emb.tractor else '',
            'Remolque': emb.remolque.placa if emb.remolque else '',
            'Operador': emb.operador.nombre if emb.operador else '',
            'Transportista': emb.transportista.nombre if emb.transportista else '',
            'T (C)': float(emb.temperatura_c) if emb.temperatura_c else '',
            'Tiempo en planta': _formatear_timedelta(
                emb.tiempos.tiempo_en_planta if emb.tiempos else None),
            'Tiempo documental': _formatear_timedelta(
                emb.tiempos.tiempo_documental if emb.tiempos else None),
            'Observaciones': emb.observaciones or '',
        })

    df = pd.DataFrame(filas)
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Embarques')
    output.seek(0)
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=f'embarques_{datetime.now().strftime("%Y%m%d_%H%M")}.xlsx',
    )


@app.route('/embarques/cuadre')
@login_required
def cuadre_embarques():
    """
    Pantalla de cuadre de galonaje (Fase 5). Por ahora es placeholder."""
    return render_template('embarques/cuadre.html')


# =====================================================================
# API
# =====================================================================

@app.route('/api/embarques/lotes')
@login_required
def api_embarques_lotes():
    """
    Endpoint JSON para el selector dinámico de lotes en el formulario.
    Devuelve lotes que tienen inventario disponible > 0.
    """
    # Subquery de lotes con inventario
    subq = (
        db.session.query(InventarioSilo.id_lote)
        .filter(InventarioSilo.galones > 0)
        .distinct()
    )
    lotes = (
        Lote.query
        .filter(Lote.id_lote.in_(subq))
        .order_by(Lote.codigo_lote.desc())
        .limit(500)
        .all()
    )
    data = []
    for l in lotes:
        total_gal = (
            db.session.query(db.func.coalesce(db.func.sum(InventarioSilo.galones), 0))
            .filter(InventarioSilo.id_lote == l.id_lote)
            .scalar()
        )
        cliente_nom = ''
        if l.cliente:
            cliente_nom = l.cliente.codigo or l.cliente.nombre_cliente
        elif l.cliente_manual:
            cliente_nom = l.cliente_manual
        data.append({
            'id_lote': l.id_lote,
            'codigo_lote': l.codigo_lote,
            'fecha_lote': l.fecha_lote.strftime('%d/%m/%Y') if l.fecha_lote else '',
            'brix': float(l.brix) if l.brix else None,
            'relacion': float(l.relacion) if l.relacion else None,
            'pulpa': float(l.pulpa) if l.pulpa else None,
            'cliente': cliente_nom,
            'galones_disponibles': float(total_gal or 0),
        })
    return jsonify({'lotes': data})


# =====================================================================
# Administración: catálogos genéricos
# =====================================================================

@app.route('/admin/catalogos/<nombre>', methods=['GET', 'POST'])
@login_required
def gestionar_catalogo(nombre):
    """
    Alta, edición y activar/desactivar de cualquiera de los catálogos del módulo
    de embarques. Solo administrador.

    nombre debe coincidir con las claves de CATALOGOS_EMBARQUES.
    """
    if current_user.rol != 'administrador':
        flash('Acceso denegado.', 'danger')
        return redirect(url_for('index'))
    if nombre not in CATALOGOS_EMBARQUES:
        flash('Catálogo no válido.', 'danger')
        return redirect(url_for('listar_embarques'))

    meta = CATALOGOS_EMBARQUES[nombre]
    Model = meta['model']
    nombre_visible = meta['nombre_visible']

    # POST: guardar nuevo o editar
    if request.method == 'POST':
        accion = request.form.get('accion', '').strip()
        id_edit = _parse_int_or_none(request.form.get('id_item'))
        try:
            if accion == 'guardar':
                # Construimos dict de valores de los campos declarados
                if id_edit:
                    obj = Model.query.get_or_404(id_edit)
                else:
                    obj = Model()
                    db.session.add(obj)
                # Normalizar y asignar campos
                for fname, _label, ftype, freq in meta['campos']:
                    raw = request.form.get(fname)
                    if ftype == 'text':
                        # Mantener mayúsculas por defecto salvo descripción que se conserva como lo escribió
                        valor = _validar_y_normalizar_texto(raw, mayusculas=(fname != 'descripcion' and fname != 'variedad'))
                        if freq and not valor:
                            flash(f'{_label} es obligatorio.', 'danger')
                            db.session.rollback()
                            return redirect(url_for('gestionar_catalogo', nombre=nombre))
                        setattr(obj, fname, valor)
                    elif isinstance(ftype, (tuple, list)) and len(ftype) == 3 and ftype[0] == 'enum':
                        # Tipo enum: ( 'enum', [valores], [labels] )
                        valor = _validar_y_normalizar_texto(raw)
                        if freq and not valor:
                            flash(f'{_label} es obligatorio.', 'danger')
                            db.session.rollback()
                            return redirect(url_for('gestionar_catalogo', nombre=nombre))
                        setattr(obj, fname, valor)
                    elif isinstance(ftype, str) and ftype.startswith('fk:'):
                        setattr(obj, fname, _parse_int_or_none(raw))
                # Campos especiales de normalización (placa siempre mayúsculas; nombres también)
                if hasattr(obj, 'placa') and obj.placa:
                    obj.placa = obj.placa.upper()
                if hasattr(obj, 'nombre') and obj.nombre:
                    obj.nombre = obj.nombre.upper()
                if hasattr(obj, 'item') and obj.item:
                    obj.item = obj.item.upper()
                if hasattr(obj, 'actualizado_por'):
                    obj.actualizado_por = current_user.id_usuario
                db.session.commit()
                flash(f'{nombre_visible} guardado correctamente.', 'success')
            elif accion == 'toggle_activo':
                obj = Model.query.get_or_404(id_edit)
                obj.activo = not bool(obj.activo)
                if hasattr(obj, 'actualizado_por'):
                    obj.actualizado_por = current_user.id_usuario
                db.session.commit()
                flash('Estado actualizado.', 'success')
        except Exception as e:
            db.session.rollback()
            msg = str(e)
            if 'Duplicate entry' in msg or 'unique' in msg.lower():
                msg = 'El registro ya existe con el mismo valor único.'
            flash(f'Error al guardar: {msg}', 'danger')
        return redirect(url_for('gestionar_catalogo', nombre=nombre))

    # GET: listar y catálogos relacionados para FKs
    # Ordenar por nombre / descripción si existen; de lo contrario por id.
    if hasattr(Model, 'nombre'):
        items = Model.query.order_by(Model.nombre).all()
    elif hasattr(Model, 'descripcion'):
        items = Model.query.order_by(Model.descripcion).all()
    elif hasattr(Model, 'placa'):
        items = Model.query.order_by(Model.placa).all()
    elif hasattr(Model, 'item'):
        items = Model.query.order_by(Model.item).all()
    else:
        items = Model.query.order_by(Model.id).all()
    fk_opciones = {}
    if nombre == 'operadores':
        fk_opciones['id_transportista'] = Transportista.query.filter_by(activo=True).order_by(Transportista.nombre).all()
    # Determinar el nombre del campo clave primaria para el template.
    pk_cols = list(Model.__mapper__.primary_key)
    pk_name = pk_cols[0].name if pk_cols else 'id'

    # Preparar los datos para renderizar la tabla: cada item se transforma en un
    # dict con los valores ya formateados (enum label, FK resuelto) para no poner
    # lógica compleja en Jinja2.
    items_display = []
    for it in items:
        pk_val = getattr(it, pk_name, None)
        cellas = {}
        for fname, _fl, ftype, _fr in meta['campos']:
            raw = getattr(it, fname, None)
            # Caso 1: enum (tupla de 3 elementos con primer valor 'enum')
            if (
                isinstance(ftype, (tuple, list))
                and len(ftype) == 3
                and ftype[0] == 'enum'
            ):
                _vals, _lbls = ftype[1], ftype[2]
                if raw and raw in _vals:
                    try:
                        cellas[fname] = _lbls[_vals.index(raw)]
                    except Exception:
                        cellas[fname] = raw or '-'
                else:
                    cellas[fname] = raw or '-'
            # Caso 2: FK (solo id_transportista por ahora)
            elif isinstance(ftype, str) and ftype.startswith('fk:') and fname == 'id_transportista' and raw:
                nombre_fk = ''
                for fk_row in (fk_opciones.get('id_transportista') or []):
                    if getattr(fk_row, 'id_transportista', None) == raw:
                        nombre_fk = getattr(fk_row, 'nombre', '') or ''
                        break
                cellas[fname] = nombre_fk or raw
            else:
                cellas[fname] = raw if (raw is not None and raw != '') else '-'
        items_display.append({
            'pk': pk_val,
            'activo': bool(getattr(it, 'activo', True)),
            'cellas': cellas,
            # Valores raw para el botón editar (data attributes)
            'raw': {
                fname: (getattr(it, fname, '') or '') if getattr(it, fname, None) is not None else ''
                for fname, _fl, _ft, _fr in meta['campos']
            },
        })

    return render_template(
        'admin/catalogos.html',
        nombre=nombre,
        meta=meta,
        items_display=items_display,
        fk_opciones=fk_opciones,
        catalogos_hijos=list(CATALOGOS_EMBARQUES.keys()),
        pk_name=pk_name,
    )


# =====================================================================
# FIN MÓDULO EMBARQUES
# =====================================================================

if __name__ == '__main__':
    app.run(debug=True, port=int(os.getenv('PORT', 5000)))
