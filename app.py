import os
import re
import json
import math
import secrets
try:
    import pandas as pd
except Exception:
    pd = None
from io import BytesIO
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_file, session, abort
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
from datetime import datetime, timedelta, date
from decimal import Decimal
from sqlalchemy import and_, or_, func

# Cargar variables de entorno
load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY') or secrets.token_urlsafe(48)

# Seguridad de cookies de sesión
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_HTTPONLY'] = True
# SESSION_COOKIE_SECURE debe activarse solo cuando se publique por HTTPS.
app.config['SESSION_COOKIE_SECURE'] = os.getenv('SESSION_COOKIE_SECURE', '0').strip() in ('1', 'true', 'True')
app.config['REMEMBER_COOKIE_SAMESITE'] = 'Lax'
app.config['REMEMBER_COOKIE_HTTPONLY'] = True

# Configuración de la base de datos MySQL (Compatible con XAMPP/Laragon)
user = os.getenv('DB_USER', 'root')
password = os.getenv('DB_PASSWORD', '')
host = os.getenv('DB_HOST', 'localhost')
db_name = os.getenv('DB_NAME', 'sistema_silos')

database_url = os.getenv('DATABASE_URL')
app.config['SQLALCHEMY_DATABASE_URI'] = database_url or f'mysql+pymysql://{user}:{password}@{host}/{db_name}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False


def csrf_token():
    """Devuelve el token CSRF de la sesión, generándolo si no existe."""
    token = session.get('_csrf_token')
    if not token:
        token = secrets.token_urlsafe(32)
        session['_csrf_token'] = token
    return token


@app.context_processor
def _inject_csrf_token():
    """Inyecta `csrf_token()` en todos los templates Jinja2."""
    return {'csrf_token': csrf_token}


@app.before_request
def _csrf_protect():
    """Bloquea solicitudes con método de escritura si no traen token CSRF válido."""
    if request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
        token_form = request.form.get('csrf_token')
        token_hdr = request.headers.get('X-CSRFToken') or request.headers.get('X-CSRF-Token')
        token = token_form or token_hdr
        token_sesion = session.get('_csrf_token')
        if not token or not token_sesion or token != token_sesion:
            abort(400)

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
    debe_cambiar_password = db.Column(db.Boolean, default=False, nullable=False)
    area = db.Column(db.Enum('operacion', 'calidad', 'embarques', 'almacen', 'ti'),
                     nullable=True, default=None)

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
    # Marca de lotes de mezcla generados en embarques de pipa.
    es_mezcla = db.Column(db.Boolean, nullable=False, default=False)
    asignado_por = db.Column(db.String(50), nullable=True)

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
    lote = db.relationship('Lote', overlaps='inventariosilos,lote_ref')

    # Un lote no se repite en un silo y la posición LIFO es única por silo.
    __table_args__ = (
        db.UniqueConstraint('id_silo', 'posicion', name='uq_inventario_silo_posicion'),
        db.UniqueConstraint('id_silo', 'id_lote', name='uq_inventario_silo_lote'),
    )

class Movimiento(db.Model):
    """
    Modelo existente de movimientos de inventario.
    Tipos: entrada, salida, ajuste, reproceso, cambio_estado,
           entrada_tqpf (lote que entra a un tanque de proceso),
           traspaso_tqpf_silo (lote que pasa de TQPF a un silo) y
           purga (tambores de producto que se pierden en la línea al traspasar
           de TQPF a silo y que se descuentan del tanque).
    Reutilizado por embarque_lotes (vínculo opcional id_movimiento).
    """
    __tablename__ = 'movimientos'
    id_movimiento = db.Column(db.Integer, primary_key=True)
    tipo_movimiento = db.Column(db.Enum('entrada', 'salida', 'ajuste', 'reproceso',
                                        'cambio_estado', 'entrada_tqpf', 'traspaso_tqpf_silo',
                                        'purga'))
    id_silo = db.Column(db.Integer, db.ForeignKey('silos.id_silo'))
    id_lote = db.Column(db.Integer, db.ForeignKey('lotes.id_lote'))
    id_tanque = db.Column(db.Integer, db.ForeignKey('tanques_tqpf.id_tanque'), nullable=True)
    galones = db.Column(db.Numeric(10, 2))
    fecha_movimiento = db.Column(db.DateTime, default=datetime.utcnow)
    id_usuario = db.Column(db.Integer, db.ForeignKey('usuarios.id_usuario'))
    observaciones = db.Column(db.Text)

    silo = db.relationship('Silo')
    lote = db.relationship('Lote')
    tanque = db.relationship('TanqueTQPF')
    usuario = db.relationship('Usuario')


# =====================================================================
# ===== MÓDULO TQPF (TANQUES DE PROCESO) - MODELOS ====================
# =====================================================================
class TanqueTQPF(db.Model):
    """
    Tanque de proceso (TQPF).

    Son los tanques donde el producto permanece mientras está en proceso,
    antes de pasar a los silos. Su inventario es independiente del de silos.
    """
    __tablename__ = 'tanques_tqpf'
    id_tanque = db.Column(db.Integer, primary_key=True)
    nombre_tanque = db.Column(db.String(30), unique=True)
    capacidad_gal = db.Column(db.Numeric(10, 2))
    tipo_producto = db.Column(db.String(30), nullable=True)
    estado = db.Column(db.Enum('activo', 'inactivo'), default='activo')


class InventarioTQPF(db.Model):
    """
    Inventario de un tanque de proceso.

    Cada fila representa el contenido de un lote dentro de un tanque TQPF.
    La `posicion` se usa para el consumo LIFO (la posición 1 es el último
    ingreso y por tanto el primero en salir).
    """
    __tablename__ = 'inventario_tqpf'
    id_inventario_tqpf = db.Column(db.Integer, primary_key=True)
    id_tanque = db.Column(db.Integer, db.ForeignKey('tanques_tqpf.id_tanque'))
    id_lote = db.Column(db.Integer, db.ForeignKey('lotes.id_lote'))
    posicion = db.Column(db.Integer)
    galones = db.Column(db.Numeric(10, 2))
    fecha_registro = db.Column(db.DateTime, default=datetime.utcnow)

    tanque = db.relationship('TanqueTQPF')
    lote = db.relationship('Lote')


class LoteComponente(db.Model):
    """
    Lotes de origen que componen un lote de mezcla.

    En un embarque de pipa el producto es una mezcla: el capturista elige los
    lotes de origen y sus galones, e INVOCA asigna el código del lote de mezcla.
    Cada fila guarda un lote de origen con los galones tomados de él.
    """
    __tablename__ = 'lote_componentes'
    id_componente = db.Column(db.Integer, primary_key=True)
    id_lote_mezcla = db.Column(db.Integer, db.ForeignKey('lotes.id_lote'), nullable=False)
    id_lote_origen = db.Column(db.Integer, db.ForeignKey('lotes.id_lote'), nullable=False)
    id_embarque = db.Column(db.Integer, db.ForeignKey('embarques.id_embarque'), nullable=True)
    galones = db.Column(db.Numeric(10, 2), nullable=False)
    creado_en = db.Column(db.DateTime, default=datetime.utcnow)

    lote_mezcla = db.relationship('Lote', foreign_keys=[id_lote_mezcla])
    lote_origen = db.relationship('Lote', foreign_keys=[id_lote_origen])

    __table_args__ = (
        db.UniqueConstraint('id_lote_mezcla', 'id_lote_origen', 'id_embarque',
                            name='uq_lote_componente'),
    )


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

# Tipos de unidad que pertenecen al grupo "pipa" (detalle y sellos de pipa).
TIPOS_UNIDAD_PIPA = ('pipa_jumbo', 'pipa_chica', 'isotanque', 'flexitanque')

# Tipos de unidad que embarcan MEZCLA OBLIGATORIA: el producto se junta de
# varios lotes de origen y el código del lote lo asigna INVOCA.
# Sólo la pipa jumbo y la pipa chica la exigen; en isotanque y flexitanque el
# campo "lote de mezcla" es opcional (igual que caja, tráiler o tambores).
TIPOS_UNIDAD_MEZCLA = ('pipa_jumbo', 'pipa_chica')

# Área/sistema que asigna el código del lote de mezcla.
ASIGNADO_POR_MEZCLA = 'INVOCA'


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
    id_producto = db.Column(db.Integer, db.ForeignKey('productos_embarque.id_producto'), nullable=True)
    id_cliente = db.Column(db.Integer, db.ForeignKey('clientes.id_cliente'), nullable=True)
    producto_texto = db.Column(db.String(200), nullable=True)
    cliente_texto = db.Column(db.String(200), nullable=True)
    tipo_unidad = db.Column(db.Enum('pipa_jumbo', 'pipa_chica', 'isotanque', 'flexitanque',
                                    'caja_refrigerada', 'caja_seca', 'trailer', 'tambores'),
                            nullable=False)
    id_transportista = db.Column(db.Integer, db.ForeignKey('transportistas.id_transportista'), nullable=True)
    id_operador = db.Column(db.Integer, db.ForeignKey('operadores.id_operador'), nullable=True)
    id_tractor = db.Column(db.Integer, db.ForeignKey('unidades_transporte.id_unidad'), nullable=True)
    id_remolque = db.Column(db.Integer, db.ForeignKey('unidades_transporte.id_unidad'), nullable=True)
    id_silo = db.Column(db.Integer, db.ForeignKey('silos.id_silo'), nullable=True)
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
    silo = db.relationship('Silo')
    capturista = db.relationship('Usuario', foreign_keys=[id_capturista])
    facilitador = db.relationship('Facilitador', foreign_keys=[id_facilitador])
    actualizado_por_usuario = db.relationship('Usuario', foreign_keys=[actualizado_por])
    tiempos = db.relationship('EmbarqueTiempos', backref='embarque', uselist=False,
                              cascade='all, delete-orphan')
    detalle = db.relationship('EmbarqueDetalle', backref='embarque', uselist=False,
                              cascade='all, delete-orphan')
    pesos = db.relationship('EmbarquePeso', backref='embarque', uselist=False,
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

    @property
    def es_pipa(self):
        """True si el embarque es de pipa (jumbo/chica/isotanque/flexitanque).

        En pipa el producto puede ser una mezcla y se captura el lote asignado
        por INVOCA, con sus lotes de origen en lote_componentes.
        """
        return self.tipo_unidad in TIPOS_UNIDAD_PIPA

    @property
    def requiere_mezcla(self):
        """True si el embarque EXIGE lote de mezcla de INVOCA (pipa jumbo/chica).

        En isotanque y flexitanque el lote de mezcla es opcional, por lo que no
        se genera la alerta de "pipa sin lote de mezcla".
        """
        return self.tipo_unidad in TIPOS_UNIDAD_MEZCLA

    @property
    def componentes_mezcla(self):
        """Filas de lote_componentes del embarque (los lotes de origen)."""
        if self.id_embarque is None:
            return []
        return LoteComponente.query.filter_by(id_embarque=self.id_embarque).all()

    @property
    def lote_mezcla(self):
        """Devuelve el Lote de mezcla del embarque (o None si no aplica).

        El lote de mezcla no vive en embarque_lotes (esos son los lotes de
        origen); se localiza a través de lote_componentes.
        """
        componente = self.componentes_mezcla
        return componente[0].lote_mezcla if componente else None


class EmbarqueTiempos(db.Model):
    """
    Registro 1 a 1 de tiempos operativos del embarque.
    Orden obligatorio y estricto:
      llegada <= entrada <= pesado_inicial <= pesaje_salida <= documentacion <= salida
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
            'llegada': 'Fecha y hora Registro llegada planta',
            'entrada': 'Fecha y hora de entrada a planta',
            'pesado_inicial': 'Pesado Inicial de la Unidad',
            'pesaje_salida': 'Pesaje de Salida',
            'documentacion': 'Fecha y hora de documentación',
            'salida': 'Fecha y hora de salida de Planta',
        }
        for a_n, a_v, b_n, b_v in pares:
            if a_v and b_v and a_v > b_v:
                return False, (
                    'Orden de tiempos INCORRECTO: '
                    f'{nombres[a_n]} no puede ser posterior a {nombres[b_n]}.'
                )
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


class EmbarquePeso(db.Model):
    """
    Registro 1 a 1 de pesos del embarque (para el cuadre de galonaje).
    - peso_bruto_kg: peso total de la unidad cargada.
    - tara_kg: peso de la unidad vacía.
    - peso_neto_kg: se calcula como bruto - tara (se guarda para validar).
    La captura es manual desde el formulario de embarque.
    """
    __tablename__ = 'embarque_pesos'
    id_embarque = db.Column(db.Integer, db.ForeignKey('embarques.id_embarque'),
                            primary_key=True)
    peso_bruto_kg = db.Column(db.Numeric(12, 2), nullable=True)
    tara_kg = db.Column(db.Numeric(12, 2), nullable=True)
    peso_neto_kg = db.Column(db.Numeric(12, 2), nullable=True)
    actualizado_por = db.Column(db.Integer, db.ForeignKey('usuarios.id_usuario'), nullable=True)
    actualizado_en = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def recalcular_neto(self):
        """Calcula peso_neto = bruto - tara si ambos están presentes."""
        if self.peso_bruto_kg is not None and self.tara_kg is not None:
            self.peso_neto_kg = Decimal(str(self.peso_bruto_kg)) - Decimal(str(self.tara_kg))


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


class DensidadBrix(db.Model):
    """
    Tabla de densidad por Brix y producto (la entrega Calidad).
    - Si Calidad da una tabla de puntos, se interpola linealmente.
    - Forma: densidad_brix(producto, brix, densidad_kg_l).
    """
    __tablename__ = 'densidad_brix'
    id_densidad = db.Column(db.Integer, primary_key=True)
    id_producto = db.Column(db.Integer, db.ForeignKey('productos_embarque.id_producto'), nullable=False)
    brix = db.Column(db.Numeric(6, 2), nullable=False)
    densidad_kg_l = db.Column(db.Numeric(8, 5), nullable=False)

    producto = db.relationship('ProductoEmbarque')


# =====================================================================
# ===== SISTEMA DE ALERTAS Y NOTIFICACIONES ==========================
# =====================================================================

class Alerta(db.Model):
    """
    Alertas persistentes del sistema (Fase B).
    - clave_unica evita duplicados (ej: silo:7:ocupacion_alta).
    - estado: 'activa' | 'atendida' | 'cerrada'.
    - Las alertas se generan desde calcular_alertas() y se persisten aquí
      para poder registrar quién las atendió y cuándo.
    """
    __tablename__ = 'alertas'
    id = db.Column(db.Integer, primary_key=True)
    tipo = db.Column(db.String(80), nullable=False)
    severidad = db.Column(db.Enum('info', 'warning', 'danger'), nullable=False)
    clave_unica = db.Column(db.String(200), unique=True, nullable=False)
    mensaje = db.Column(db.Text, nullable=False)
    url = db.Column(db.String(500), nullable=True)
    estado = db.Column(db.Enum('activa', 'atendida', 'cerrada'), nullable=False, default='activa')
    creada_en = db.Column(db.DateTime, default=datetime.utcnow)
    actualizada_en = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    atendida_por = db.Column(db.Integer, db.ForeignKey('usuarios.id_usuario'), nullable=True)
    atendida_en = db.Column(db.DateTime, nullable=True)

    notificaciones = db.relationship('Notificacion', backref='alerta',
                                     cascade='all, delete-orphan', lazy=True)


class Notificacion(db.Model):
    """
    Notificación dirigida a un usuario concreto.
    - Se crea cuando una alerta se genera y coincide con el área del usuario
      (según alerta_destinatarios).
    - leida indica si el usuario ya la vio.
    """
    __tablename__ = 'notificaciones'
    id = db.Column(db.Integer, primary_key=True)
    id_usuario = db.Column(db.Integer, db.ForeignKey('usuarios.id_usuario'), nullable=False, index=True)
    id_alerta = db.Column(db.Integer, db.ForeignKey('alertas.id'), nullable=False)
    titulo = db.Column(db.String(200), nullable=False)
    mensaje = db.Column(db.Text, nullable=False)
    url = db.Column(db.String(500), nullable=True)
    leida = db.Column(db.Boolean, default=False, nullable=False)
    creada_en = db.Column(db.DateTime, default=datetime.utcnow)

    usuario = db.relationship('Usuario', foreign_keys=[id_usuario])


class AlertaDestinatario(db.Model):
    """
    Define qué áreas reciben notificaciones por cada tipo de alerta.
    Ej: tipo_alerta='silo_ocupacion_alta', area='operacion'.
    Si no hay registros para un tipo, se notifica a todos los usuarios activos.
    """
    __tablename__ = 'alerta_destinatarios'
    id = db.Column(db.Integer, primary_key=True)
    tipo_alerta = db.Column(db.String(80), nullable=False, index=True)
    area = db.Column(db.Enum('operacion', 'calidad', 'embarques', 'almacen', 'ti'), nullable=False)


# =====================================================================
# ===== FIN MODELOS EMBARQUES =========================================
# =====================================================================


# =====================================================================
# ===== MÓDULO EMPAQUE - CATÁLOGOS ADMINISTRABLES =====================
# =====================================================================
# Todas las listas cerradas (categorías, áreas, proveedores) son tablas
# administrables por el administrador para que el usuario las llene.
# Nunca se borran físicamente; se desactivan con activo=False.
# =====================================================================


class EmpaqueCategoria(db.Model):
    """
    Catálogo de categorías de artículos de empaque (Ej: Contenedor, Tarima,
    Bolsa, Etiqueta, Cierre, Esencia, Otros, etc.).

    - El usuario administrador crea/edita/desactiva desde la pantalla.
    - nombre UNIQUE (no se permite duplicar la misma categoría).
    - Nunca se elimina; se desactiva.
    """
    __tablename__ = 'empaque_categorias'
    id_categoria = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False, unique=True)
    activo = db.Column(db.Boolean, default=True)
    creado_en = db.Column(db.DateTime, default=datetime.utcnow)
    actualizado_en = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class EmpaqueArea(db.Model):
    """
    Catálogo de áreas solicitantes de material de empaque.

    Ejemplos: Pulpa, Producción, Calidad, Llenado, Centrifugado,
              Evaporador, Embarques, Otra.

    - El nombre "Pulpa" tiene significado semántico en reglas de negocio:
      una salida con área Pulpa exige un lote de pulpa asociado.
    - nombre UNIQUE.
    """
    __tablename__ = 'empaque_areas'
    id_area = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False, unique=True)
    activo = db.Column(db.Boolean, default=True)
    creado_en = db.Column(db.DateTime, default=datetime.utcnow)
    actualizado_en = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class EmpaqueProveedor(db.Model):
    """
    Catálogo de proveedores de material de empaque. Usado en Entradas.

    - nombre UNIQUE.
    - Nunca se elimina; se desactiva.
    """
    __tablename__ = 'empaque_proveedores'
    id_proveedor = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(200), nullable=False, unique=True)
    activo = db.Column(db.Boolean, default=True)
    creado_en = db.Column(db.DateTime, default=datetime.utcnow)
    actualizado_en = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# =====================================================================
# ===== MÓDULO EMPAQUE - ARTÍCULO =====================================
# =====================================================================
# Regla fundamental: nombre y unidad de medida VIVEN SÓLO AQUÍ.
# Los movimientos (entrada/salida/ajuste) sólo guardan la FK al artículo;
# NUNCA duplican nombre ni unidad.
# =====================================================================


class EmpaqueArticulo(db.Model):
    """
    Catálogo maestro de artículos de empaque.

    - codigo es la PK natural del negocio (Ej: IN00120071). Único.
    - um (unidad de medida) es ENUM cerrada: 'Pz' o 'Kg'. No es adminable
      porque afecta reglas de validación de cantidad (entera vs. decimal).
    - stock_minimo y fisico_dynamics son opcionales (NULLABLE).
    - No se elimina físicamente si tiene movimientos asociados (se inactiva).
    """
    __tablename__ = 'empaque_articulos'
    codigo = db.Column(db.String(20), primary_key=True)
    nombre = db.Column(db.String(255), nullable=False, unique=True)
    id_categoria = db.Column(db.Integer, db.ForeignKey('empaque_categorias.id_categoria'), nullable=True)
    um = db.Column(db.Enum('Pz', 'Kg'), nullable=False)
    almacen = db.Column(db.String(20), nullable=False, default='CP005')
    stock_minimo = db.Column(db.Numeric(14, 3), nullable=True)
    fisico_dynamics = db.Column(db.Numeric(14, 3), nullable=True)
    activo = db.Column(db.Boolean, default=True)
    creado_en = db.Column(db.DateTime, default=datetime.utcnow)
    actualizado_en = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    categoria = db.relationship('EmpaqueCategoria')

    # ------------------------------------------------------------------
    # Campos calculados: stock, diferencia y estado.
    # Regla de arquitectura: NUNCA se guardan; siempre se derivan al vuelo
    # sumando entradas - salidas + ajustes.
    # ------------------------------------------------------------------

    @property
    def stock_actual(self):
        """
        Calcula el stock actual del artículo como:
        SUM(entradas.cantidad - entradas.rechazos) - SUM(salidas.cantidad) + SUM(ajustes.cantidad)

        Devuelve un Decimal. 0 si no hay movimientos.
        """
        entradas = (
            db.session.query(db.func.coalesce(
                db.func.sum(EmpaqueEntrada.cantidad - db.func.coalesce(EmpaqueEntrada.rechazos, 0)),
                0
            ))
            .filter(EmpaqueEntrada.codigo == self.codigo)
            .scalar()
        )
        salidas = (
            db.session.query(db.func.coalesce(
                db.func.sum(EmpaqueSalida.cantidad),
                0
            ))
            .filter(EmpaqueSalida.codigo == self.codigo)
            .scalar()
        )
        ajustes = (
            db.session.query(db.func.coalesce(
                db.func.sum(EmpaqueAjuste.cantidad),
                0
            ))
            .filter(EmpaqueAjuste.codigo == self.codigo)
            .scalar()
        )
        return (Decimal(str(entradas or 0))
                - Decimal(str(salidas or 0))
                + Decimal(str(ajustes or 0)))

    @property
    def diferencia(self):
        """
        Diferencia entre stock actual (control interno) y físico de Dynamics.
        Devuelve None si fisico_dynamics es NULL (no hay dato oficial).
        """
        if self.fisico_dynamics is None:
            return None
        return self.stock_actual - Decimal(str(self.fisico_dynamics))

    @property
    def estado_articulo(self):
        """
        Calcula el estado del artículo en el ORDEN ESTRICTO del requerimiento.
        El orden importa: una vez que cae en un estado no se evalúan los demás.

        Prioridad de mayor a menor:
        1) fisico < 0                -> 'negativo_dynamics'   (rojo)
        2) stock <= 0                -> 'sin_stock'           (rojo)
        3) stock < stock_minimo      -> 'bajo_minimo'         (ámbar)
        4) fisico IS NULL            -> 'sin_dynamics'        (informativo)
        5) stock == fisico           -> 'cuadra'              (verde)
        6) else                      -> 'con_diferencia'      (ámbar)

        Si la condición 3 y 6 son verdaderas al mismo tiempo, se devuelve
        'bajo_minimo' por ser la regla de mayor prioridad.

        Devuelve: (clave, etiqueta_visible, clase_color)
        """
        stock = self.stock_actual
        fisico = self.fisico_dynamics
        minimo = self.stock_minimo

        # 1. Negativo en Dynamics (rojo)
        if fisico is not None and Decimal(str(fisico)) < 0:
            return ('negativo_dynamics', 'Negativo en Dynamics', 'danger')

        # 2. Sin stock (rojo)
        if stock <= 0:
            return ('sin_stock', 'Sin stock', 'danger')

        # 3. Bajo mínimo (ámbar)
        if minimo is not None and stock < Decimal(str(minimo)):
            return ('bajo_minimo', 'Bajo mínimo', 'warning')

        # 4. Sin dato de Dynamics (informativo)
        if fisico is None:
            return ('sin_dynamics', 'Sin dato Dynamics', 'info')

        # 5. Cuadra (verde)
        if stock == Decimal(str(fisico)):
            return ('cuadra', 'Cuadra', 'success')

        # 6. Con diferencia (ámbar)
        return ('con_diferencia', 'Con diferencia', 'warning')


# =====================================================================
# ===== MÓDULO EMPAQUE - MOVIMIENTOS ==================================
# =====================================================================
# Invariantes clave:
# - Un movimiento (entrada/salida/ajuste) NUNCA se edita ni se borra.
# - Si hay un error, se registra un Ajuste con motivo.
# - El usuario y la fecha de creación son auditoría inmutable.
# =====================================================================


class EmpaqueEntrada(db.Model):
    """
    Entrada de material de empaque al almacén.

    - cantidad > 0 (validado en servidor).
    - rechazos: piezas devueltas al proveedor (default 0). Los rechazos se
      descuentan del cálculo de stock (entrada neta = cantidad - rechazos).
    - FK a EmpaqueProveedor (obligatorio).
    - creado_por -> Usuario.id_usuario (auditoría).
    """
    __tablename__ = 'empaque_entradas'
    id_entrada = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(20), db.ForeignKey('empaque_articulos.codigo'), nullable=False)
    cantidad = db.Column(db.Numeric(14, 3), nullable=False)
    fecha = db.Column(db.Date, nullable=False)
    id_proveedor = db.Column(db.Integer, db.ForeignKey('empaque_proveedores.id_proveedor'), nullable=False)
    rechazos = db.Column(db.Numeric(14, 3), nullable=False, default=0)
    comentario = db.Column(db.Text, nullable=True)
    creado_por = db.Column(db.Integer, db.ForeignKey('usuarios.id_usuario'), nullable=False)
    creado_en = db.Column(db.DateTime, default=datetime.utcnow)

    articulo = db.relationship('EmpaqueArticulo')
    proveedor = db.relationship('EmpaqueProveedor')
    usuario = db.relationship('Usuario', foreign_keys=[creado_por])


class EmpaqueSalida(db.Model):
    """
    Salida de material de empaque desde el almacén.

    Reglas:
    - cantidad > 0.
    - No puede dejar el stock en negativo (validado en transacción).
    - FK a EmpaqueArea (obligatorio).
    - lote_id es OPCIONAL EXCEPTO cuando el área es Pulpa. La comparación
      se hace por nombre del área (columna EmpaqueArea.nombre == 'Pulpa')
      porque es un catálogo editable por el usuario (no hay id fijo).
    - lote_id apunta a lotes.id_lote existente de SICSE (no duplica datos).
    """
    __tablename__ = 'empaque_salidas'
    id_salida = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(20), db.ForeignKey('empaque_articulos.codigo'), nullable=False)
    cantidad = db.Column(db.Numeric(14, 3), nullable=False)
    fecha = db.Column(db.Date, nullable=False)
    id_area = db.Column(db.Integer, db.ForeignKey('empaque_areas.id_area'), nullable=False)
    id_lote = db.Column(db.Integer, db.ForeignKey('lotes.id_lote'), nullable=True)
    comentario = db.Column(db.Text, nullable=True)
    creado_por = db.Column(db.Integer, db.ForeignKey('usuarios.id_usuario'), nullable=False)
    creado_en = db.Column(db.DateTime, default=datetime.utcnow)

    articulo = db.relationship('EmpaqueArticulo')
    area = db.relationship('EmpaqueArea')
    lote = db.relationship('Lote')
    usuario = db.relationship('Usuario', foreign_keys=[creado_por])


class EmpaqueAjuste(db.Model):
    """
    Ajuste de inventario de empaque. Única forma de corregir.

    - cantidad puede ser positiva (agrega stock) o negativa (resta stock).
    - motivo es OBLIGATORIO (por qué se ajusta).
    - usuario y fecha de auditoría inmutables.
    - solo lo registra el rol 'administrador'.
    """
    __tablename__ = 'empaque_ajustes'
    id_ajuste = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(20), db.ForeignKey('empaque_articulos.codigo'), nullable=False)
    cantidad = db.Column(db.Numeric(14, 3), nullable=False)
    fecha = db.Column(db.Date, nullable=False)
    motivo = db.Column(db.String(255), nullable=False)
    creado_por = db.Column(db.Integer, db.ForeignKey('usuarios.id_usuario'), nullable=False)
    creado_en = db.Column(db.DateTime, default=datetime.utcnow)

    articulo = db.relationship('EmpaqueArticulo')
    usuario = db.relationship('Usuario', foreign_keys=[creado_por])


# =====================================================================
# ===== MÓDULO EMPAQUE - KIT POR LOTE =================================
# =====================================================================


class EmpaqueKit(db.Model):
    """
    Kit estándar sugerido de consumo por lote de pulpa (o por área).

    - id_area: generalmente el área Pulpa, pero se deja abierto a otras
      áreas si el negocio lo requiere.
    - cantidad_sugerida > 0.
    - El administrador configura las filas desde la pantalla Catálogo.
    - Un registro por (id_area, codigo); UNIQUE.
    """
    __tablename__ = 'empaque_kits'
    id_kit = db.Column(db.Integer, primary_key=True)
    id_area = db.Column(db.Integer, db.ForeignKey('empaque_areas.id_area'), nullable=False)
    codigo = db.Column(db.String(20), db.ForeignKey('empaque_articulos.codigo'), nullable=False)
    cantidad_sugerida = db.Column(db.Numeric(14, 3), nullable=False)
    creado_en = db.Column(db.DateTime, default=datetime.utcnow)
    actualizado_en = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('id_area', 'codigo', name='uq_empaque_kit_area_codigo'),
    )

    area = db.relationship('EmpaqueArea')
    articulo = db.relationship('EmpaqueArticulo')


# =====================================================================
# ===== FIN MODELOS EMPAQUE ===========================================
# =====================================================================


@login_manager.user_loader
def load_user(user_id):
    try:
        return db.session.get(Usuario, int(user_id))
    except (TypeError, ValueError):
        return None

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
    - _is_guest: oculta botones de escritura al rol invitado.
    - empaque_format_num: formatea cantidades por UM (Pz/Kg) en templates.
    - empaque_estado_desde_valores: determina badge de estado con valores batch.
    - notificaciones_no_leidas: contador para la campana del navbar.
    """
    no_leidas = 0
    if current_user.is_authenticated:
        no_leidas = Notificacion.query.filter_by(
            id_usuario=current_user.id_usuario, leida=False
        ).count()
    return {
        '_is_guest': _is_guest,
        'empaque_format_num': _empaque_format_numero,
        'empaque_estado_desde_valores': _empaque_estado_desde_valores,
        'date': date,
        'today': date.today,
        'notificaciones_no_leidas': no_leidas,
    }

RUTAS_PERMITIDAS_INVITADO_GET = frozenset({
    # Rutas existentes
    'index', 'historial', 'ver_inventario_silo', 'exportar_historial',
    'login', 'logout', 'static',
    # Módulo embarques: solo lectura (listado, detalle, exportar, cuadre, API lotes)
    'listar_embarques', 'detalle_embarque', 'exportar_embarques',
    'cuadre_embarques', 'api_embarques_lotes',
    # Módulo empaque: solo lectura (rol Consulta -> invitado)
    'empaque_resumen', 'empaque_inventario',
    'empaque_api_articulo_detalle',
    # Notificaciones (propias del usuario)
    'notificaciones', 'api_notificaciones',
    # Exportar cuadre de galonaje
    'exportar_cuadre',
})

# POST permitidos para invitados (solo afectan sus propias notificaciones)
RUTAS_POST_PERMITIDAS_INVITADO = frozenset({
    'notificacion_leer', 'notificacion_leer_todas',
})

RUTAS_NO_PERMITIDAS_INVITADO = frozenset({
    # Rutas existentes
    'registrar_entrada', 'registrar_salida', 'registrar_reproceso',
    'gestionar_usuarios', 'nuevo_usuario', 'reset_silos',
    'cambiar_estado_lote',
    # Módulo embarques: escritura está bloqueada además por _block_guest_writes
    'nuevo_embarque', 'editar_embarque', 'cancelar_embarque',
    'gestionar_catalogo',
    # Módulo empaque: captura y administración
    'empaque_movimiento', 'empaque_registrar_kit',
    'empaque_registrar_ajuste',
    'empaque_catalogo', 'empaque_catalogo_guardar_articulo',
    'empaque_catalogo_toggle_articulo',
    'empaque_catalogo_guardar_categoria',
    'empaque_catalogo_guardar_area',
    'empaque_catalogo_guardar_proveedor',
    'empaque_catalogo_guardar_kit',
    'empaque_catalogo_eliminar_kit',
    'empaque_carga_masiva_plantilla',
    'empaque_carga_masiva_articulos',
    'empaque_carga_masiva_movimientos',
    'empaque_conciliacion',
    'empaque_exportar_inventario',
    'empaque_exportar_movimientos',
})


# =====================================================================
# ===== HELPERS MÓDULO EMPAQUE ========================================
# =====================================================================
# Funciones reutilizables que encapsulan reglas de negocio.
# Separadas de las rutas para facilitar testing y mantenimiento.
# =====================================================================


def _empaque_deny_if_not_admin():
    """
    Devuelve True y lanza flash si el usuario NO es administrador.
    Usado en rutas del Catálogo, Ajustes, Conciliación y Cargas masivas.
    """
    if not current_user.is_authenticated:
        flash('Sesión expirada. Inicia sesión nuevamente.', 'warning')
        return True
    if (current_user.rol or '').strip().lower() != 'administrador':
        flash('Acceso denegado: solo el rol Administrador puede realizar esta acción.', 'danger')
        return True
    return False


def _empaque_deny_if_guest_or_consulta():
    """
    Devuelve True si el usuario no puede escribir (invitado / consulta).
    Usado para rutas de Entrada / Salida (capturista o admin sí pueden).
    """
    return _deny_if_guest()


def _validar_cantidad_por_um(raw, um, allow_negative=False):
    """
    Valida y parsea una cantidad para la UM indicada (Pz entera, Kg hasta 3 decimales).

    Parámetros:
        raw: str / Decimal / number (acepta entrada directa de formulario).
        um: 'Pz' o 'Kg'.
        allow_negative: si True, admite signo negativo (por ejemplo, ajustes).

    Devuelve:
        (ok: bool, cantidad_decimal_o_None, mensaje_error: str)
    """
    if raw is None:
        return False, None, 'Cantidad faltante.'
    s = str(raw).strip()
    if s == '':
        return False, None, 'Cantidad faltante.'
    cantidad = _parse_decimal_or_none(s)
    if cantidad is None:
        return False, None, 'Cantidad no es un número válido.'
    if not allow_negative and cantidad <= 0:
        return False, None, 'La cantidad debe ser mayor a cero.'
    if allow_negative and cantidad == 0:
        return False, None, 'La cantidad debe ser distinta de cero.'
    um_ = (um or '').strip()
    if um_ == 'Pz':
        if cantidad != cantidad.to_integral_value():
            return False, None, 'Para unidad Pz la cantidad debe ser entera (sin decimales).'
    elif um_ == 'Kg':
        signo, digitos, exp = cantidad.as_tuple()
        if exp is not None and exp < -3:
            return False, None, 'Para unidad Kg se admiten máximo 3 decimales.'
    else:
        return False, None, f'Unidad de medida desconocida: {um}.'
    return True, cantidad, ''


def _empaque_validar_cantidad_por_um(cantidad, um):
    """Wrapper legacy. Devuelve (ok, mensaje)."""
    ok, _val, msg = _validar_cantidad_por_um(cantidad, um, allow_negative=False)
    return ok, msg


def _empaque_calcular_stock_batch(codigos):
    """
    Calcula stock actual para UNA LISTA de códigos en 3 consultas SQL
    (una por tipo de movimiento) en lugar de 3 por cada artículo.
    Optimización crucial para listados con > 50 artículos.

    Parámetros:
        codigos: list[str] de códigos de artículo.

    Devuelve:
        dict {codigo: Decimal_stock_actual}
    """
    if not codigos:
        return {}

    entrada_neta = dict(
        db.session.query(
            EmpaqueEntrada.codigo,
            db.func.coalesce(
                db.func.sum(EmpaqueEntrada.cantidad - db.func.coalesce(EmpaqueEntrada.rechazos, 0)),
                0
            )
        )
        .filter(EmpaqueEntrada.codigo.in_(codigos))
        .group_by(EmpaqueEntrada.codigo)
        .all()
    )
    salidas_total = dict(
        db.session.query(
            EmpaqueSalida.codigo,
            db.func.coalesce(db.func.sum(EmpaqueSalida.cantidad), 0)
        )
        .filter(EmpaqueSalida.codigo.in_(codigos))
        .group_by(EmpaqueSalida.codigo)
        .all()
    )
    ajustes_total = dict(
        db.session.query(
            EmpaqueAjuste.codigo,
            db.func.coalesce(db.func.sum(EmpaqueAjuste.cantidad), 0)
        )
        .filter(EmpaqueAjuste.codigo.in_(codigos))
        .group_by(EmpaqueAjuste.codigo)
        .all()
    )

    resultado = {}
    for c in codigos:
        e = Decimal(str(entrada_neta.get(c, 0)))
        s = Decimal(str(salidas_total.get(c, 0)))
        a = Decimal(str(ajustes_total.get(c, 0)))
        resultado[c] = e - s + a
    return resultado


def _empaque_estado_desde_valores(stock_actual, fisico_dynamics, diferencia_o_stock_minimo=None, stock_minimo=None):
    """
    Calcula el estado de un artículo a partir de sus valores numéricos.
    MISMA REGLA que EmpaqueArticulo.estado_articulo pero permite ser usada
    con el stock calculado en batch (evita N+1 queries en listados).

    Compatibilidad:
      - Firma nueva: (stock_actual, fisico_dynamics, stock_minimo)
      - Firma legacy: (stock_actual, fisico_dynamics, diferencia, stock_minimo)
        donde `diferencia` ya no se usa para decidir el estado.

    Devuelve: (clave, etiqueta, clase_color)
    """
    stock = Decimal(str(stock_actual)) if stock_actual is not None else Decimal('0')
    if stock_minimo is None:
        stock_minimo = diferencia_o_stock_minimo
    minimo = Decimal(str(stock_minimo)) if stock_minimo is not None else None
    fisico = Decimal(str(fisico_dynamics)) if fisico_dynamics is not None else None

    # 1. Negativo en Dynamics (rojo)
    if fisico is not None and fisico < 0:
        return ('negativo_dynamics', 'Negativo en Dynamics', 'danger')

    # 2. Sin stock (rojo)
    if stock <= 0:
        return ('sin_stock', 'Sin stock', 'danger')

    # 3. Bajo mínimo (ámbar)
    if minimo is not None and stock < minimo:
        return ('bajo_minimo', 'Bajo mínimo', 'warning')

    # 4. Sin dato Dynamics (informativo)
    if fisico is None:
        return ('sin_dynamics', 'Sin dato Dynamics', 'info')

    # 5. Cuadra (verde)
    if stock == fisico:
        return ('cuadra', 'Cuadra', 'success')

    # 6. Con diferencia (ámbar)
    return ('con_diferencia', 'Con diferencia', 'warning')


# =====================================================================
# ===== SISTEMA DE ALERTAS (Fase A) ====================================
# =====================================================================

def _get_parametro_str(clave, default=None):
    """Lee un parámetro de parametros_sistema como texto. Devuelve default si no existe."""
    p = ParametroSistema.query.get(clave)
    return p.valor if p and p.valor not in (None, '') else default


def _get_parametro_float(clave, default=None):
    """Lee un parámetro numérico. Devuelve default si no existe o no es válido."""
    raw = _get_parametro_str(clave)
    if raw is None:
        return default
    try:
        return float(raw)
    except (ValueError, TypeError):
        return default


def calcular_alertas():
    """
    Calcula las alertas activas del sistema a partir de los datos existentes.
    Devuelve una lista de diccionarios: {tipo, severidad, mensaje, url}.

    severidad: 'info' | 'warning' | 'danger' (reutiliza colores de empaque).
    No requiere tabla nueva; todo se calcula al vuelo.
    """
    alertas = []
    ahora = datetime.now()
    hoy = ahora.date()

    # ------------------------------------------------------------------
    # 1. SILOS: ocupación mayor a X %
    # ------------------------------------------------------------------
    umbral_silo = _get_parametro_float('silo_ocupacion_alerta_pct', 90.0)
    silos_activos = Silo.query.filter_by(estado='activo').all()
    for silo in silos_activos:
        inventario = InventarioSilo.query.filter_by(id_silo=silo.id_silo).all()
        galones = sum(float(item.galones) for item in inventario)
        cap = float(silo.capacidad_gal) if silo.capacidad_gal else 0
        if cap > 0:
            pct = (galones / cap) * 100
            if pct >= umbral_silo:
                alertas.append({
                    'tipo': 'silo_ocupacion_alta',
                    'severidad': 'warning' if pct < 98 else 'danger',
                    'clave_unica': f'silo:{silo.id_silo}:ocupacion_alta',
                    'mensaje': f'Silo {silo.nombre_silo} al {pct:.1f}% de ocupación.',
                    'url': url_for('ver_inventario_silo', id_silo=silo.id_silo),
                })

    # ------------------------------------------------------------------
    # 2. LOTES: Brix, relación o pulpa fuera de rango
    # ------------------------------------------------------------------
    # Umbrales por tipo de producto (concentrado / pulpa / colateral).
    # Solo aplica si el parámetro existe.
    rangos_brix = {
        'concentrado': (_get_parametro_float('brix_min_concentrado'), _get_parametro_float('brix_max_concentrado')),
        'pulpa':       (_get_parametro_float('brix_min_pulpa'),       _get_parametro_float('brix_max_pulpa')),
        'colateral':   (_get_parametro_float('brix_min_colateral'),   _get_parametro_float('brix_max_colateral')),
    }
    rangos_relacion = {
        'concentrado': (_get_parametro_float('relacion_min_concentrado'), _get_parametro_float('relacion_max_concentrado')),
    }
    rangos_pulpa = {
        'concentrado': (_get_parametro_float('pulpa_min_concentrado'), _get_parametro_float('pulpa_max_concentrado')),
    }

    lotes = Lote.query.filter(Lote.brix.isnot(None) | Lote.relacion.isnot(None) | Lote.pulpa.isnot(None)).all()
    # Determinar tipo de producto por cliente o por nombre (heurística simple:
    # si el cliente/estado sugiere pulpa o concentrado). Si no se puede, se
    # evalúan los rangos de concentrado como default.
    for lote in lotes:
        # Usar 'concentrado' como tipo por defecto para validar rangos.
        # (En producción esto podría venir de un campo tipo_producto en Lote.)
        tipo_prod = 'concentrado'
        bmin, bmax = rangos_brix.get(tipo_prod, (None, None))
        rmin, rmax = rangos_relacion.get(tipo_prod, (None, None))
        pmin, pmax = rangos_pulpa.get(tipo_prod, (None, None))

        problemas = []
        if lote.brix is not None and (bmin is not None or bmax is not None):
            if bmin is not None and float(lote.brix) < bmin:
                problemas.append(f'Brix {float(lote.brix):.2f} < {bmin}')
            if bmax is not None and float(lote.brix) > bmax:
                problemas.append(f'Brix {float(lote.brix):.2f} > {bmax}')
        if lote.relacion is not None and (rmin is not None or rmax is not None):
            if rmin is not None and float(lote.relacion) < rmin:
                problemas.append(f'Relación {float(lote.relacion):.2f} < {rmin}')
            if rmax is not None and float(lote.relacion) > rmax:
                problemas.append(f'Relación {float(lote.relacion):.2f} > {rmax}')
        if lote.pulpa is not None and (pmin is not None or pmax is not None):
            if pmin is not None and float(lote.pulpa) < pmin:
                problemas.append(f'Pulpa {float(lote.pulpa):.2f} < {pmin}')
            if pmax is not None and float(lote.pulpa) > pmax:
                problemas.append(f'Pulpa {float(lote.pulpa):.2f} > {pmax}')

        if problemas:
            alertas.append({
                'tipo': 'lote_fuera_rango',
                'severidad': 'danger',
                'clave_unica': f'lote:{lote.id_lote}:fuera_rango',
                'mensaje': f'Lote {lote.codigo_lote}: {"; ".join(problemas)}.',
                'url': '#',
            })

    # ------------------------------------------------------------------
    # 3. EMBARQUES: checklist de pulpa / tambor / tiempo documental
    # ------------------------------------------------------------------
    embarques = Embarque.query.filter(Embarque.estatus != 'cancelado').all()
    for emb in embarques:
        detalle = emb.detalle
        tiempos = emb.tiempos
        tipo_unidad = emb.tipo_unidad or ''
        es_tambor = tipo_unidad == 'tambores'
        es_pulpa = emb.producto and emb.producto.tipo == 'pulpa'

        # Pulpa sin Check List (solo si el producto es pulpa y el detalle existe)
        if es_pulpa and detalle is not None and detalle.check_list is not True:
            alertas.append({
                'tipo': 'embarque_sin_checklist',
                'severidad': 'warning',
                'clave_unica': f'embarque:{emb.id_embarque}:sin_checklist',
                'mensaje': f'Embarque {emb.num_cita} (Pulpa) sin Check List registrado.',
                'url': url_for('editar_embarque', id_embarque=emb.id_embarque),
            })

        # Tambor sin lote de tambor
        if es_tambor and (detalle is None or not detalle.lote_tambor):
            alertas.append({
                'tipo': 'embarque_sin_lote_tambor',
                'severidad': 'warning',
                'clave_unica': f'embarque:{emb.id_embarque}:sin_lote_tambor',
                'mensaje': f'Embarque {emb.num_cita} (Tambores) sin lote de tambor registrado.',
                'url': url_for('editar_embarque', id_embarque=emb.id_embarque),
            })

        # Pipa (jumbo/chica) sin lote de mezcla asignado por INVOCA
        if emb.requiere_mezcla and emb.lote_mezcla is None:
            alertas.append({
                'tipo': 'embarque_pipa_sin_mezcla',
                'severidad': 'warning',
                'clave_unica': f'embarque:{emb.id_embarque}:pipa_sin_mezcla',
                'mensaje': f'Embarque {emb.num_cita} (pipa) sin lote de mezcla de INVOCA.',
                'url': url_for('editar_embarque', id_embarque=emb.id_embarque),
            })

        # Orden de tiempos incorrecto: el proceso debe seguir la secuencia
        # llegada -> entrada -> pesado inicial -> pesaje salida -> documentación -> salida.
        if tiempos is not None:
            orden_ok, orden_msg = tiempos.tiempos_ordenados()
            if not orden_ok:
                alertas.append({
                    'tipo': 'embarque_orden_tiempos_incorrecto',
                    'severidad': 'danger',
                    'clave_unica': f'embarque:{emb.id_embarque}:orden_tiempos_incorrecto',
                    'mensaje': f'Embarque {emb.num_cita}: {orden_msg}',
                    'url': url_for('editar_embarque', id_embarque=emb.id_embarque),
                })

        # Sin tiempo documental (documentación) cuando está en planta o cargado
        if emb.estatus in ('en_planta', 'cargado') and (tiempos is None or tiempos.documentacion is None):
            alertas.append({
                'tipo': 'embarque_sin_documentacion',
                'severidad': 'info',
                'clave_unica': f'embarque:{emb.id_embarque}:sin_documentacion',
                'mensaje': f'Embarque {emb.num_cita} sin fecha de documentación.',
                'url': url_for('editar_embarque', id_embarque=emb.id_embarque),
            })

    # ------------------------------------------------------------------
    # 4. EMBARQUES: en planta por más de X horas / programado vencido
    # ------------------------------------------------------------------
    max_horas_planta = _get_parametro_float('embarque_en_planta_max_horas', 24.0)
    for emb in embarques:
        if emb.estatus == 'en_planta':
            tiempos = emb.tiempos
            ref = None
            if tiempos:
                ref = tiempos.entrada or tiempos.llegada
            if ref is not None:
                horas = (ahora - ref).total_seconds() / 3600.0
                if horas > max_horas_planta:
                    alertas.append({
                        'tipo': 'embarque_tiempo_excedido',
                        'severidad': 'danger',
                        'clave_unica': f'embarque:{emb.id_embarque}:tiempo_excedido',
                        'mensaje': f'Embarque {emb.num_cita} en planta por {horas:.1f} h (máx {max_horas_planta:.0f} h).',
                        'url': url_for('editar_embarque', id_embarque=emb.id_embarque),
                    })
        elif emb.estatus == 'programado' and emb.fecha_embarque and emb.fecha_embarque < hoy:
            alertas.append({
                'tipo': 'embarque_programado_vencido',
                'severidad': 'warning',
                'clave_unica': f'embarque:{emb.id_embarque}:programado_vencido',
                'mensaje': f'Embarque {emb.num_cita} programado para {emb.fecha_embarque} y aún no llega.',
                'url': url_for('editar_embarque', id_embarque=emb.id_embarque),
            })

    # ------------------------------------------------------------------
    # 4b. TQPF: tanques de proceso con ocupación alta
    # ------------------------------------------------------------------
    umbral_tqpf = _get_parametro_float('tqpf_ocupacion_alerta_pct', 90.0)
    for tanque in TanqueTQPF.query.filter_by(estado='activo').all():
        cap_t = float(tanque.capacidad_gal) if tanque.capacidad_gal else 0
        if cap_t <= 0:
            continue
        items_t = InventarioTQPF.query.filter_by(id_tanque=tanque.id_tanque).all()
        gal_t = sum((float(i.galones or 0) for i in items_t), 0.0)
        pct_t = (gal_t / cap_t) * 100
        if pct_t >= umbral_tqpf:
            alertas.append({
                'tipo': 'tqpf_ocupacion_alta',
                'severidad': 'warning' if pct_t < 98 else 'danger',
                'clave_unica': f'tqpf:{tanque.id_tanque}:ocupacion_alta',
                'mensaje': f'Tanque {tanque.nombre_tanque} al {pct_t:.1f}% de ocupación.',
                'url': url_for('inventario_tqpf'),
            })

    # ------------------------------------------------------------------
    # 5. EMPAQUE: negativo, sin stock, bajo mínimo, diferencia con Dynamics
    # ------------------------------------------------------------------
    articulos = EmpaqueArticulo.query.filter_by(activo=True).all()
    for art in articulos:
        stock = art.stock_actual
        fisico = art.fisico_dynamics
        minimo = art.stock_minimo
        clave, etiqueta, color = _empaque_estado_desde_valores(stock, fisico, minimo)
        # Solo reportar estados problemáticos (no success ni info)
        if color in ('danger', 'warning'):
            severidad = color  # danger/warning ya coinciden
            alertas.append({
                'tipo': f'empaque_{clave}',
                'severidad': severidad,
                'clave_unica': f'empaque:{art.codigo}:{clave}',
                'mensaje': f'{art.nombre}: {etiqueta} (stock {_empaque_format_numero(stock, art.um)} {art.um}).',
                'url': url_for('empaque_inventario'),
            })

    return alertas


# ----------------------------------------------------------------------
# Sincronización de alertas y generación de notificaciones
# ----------------------------------------------------------------------

_TITULOS_POR_TIPO = {
    'silo_ocupacion_alta': 'Silo con ocupación alta',
    'lote_fuera_rango': 'Lote fuera de rango',
    'embarque_sin_checklist': 'Embarque de pulpa sin Check List',
    'embarque_sin_lote_tambor': 'Embarque de tambores sin lote',
    'embarque_sin_documentacion': 'Embarque sin documentación',
    'embarque_tiempo_excedido': 'Embarque excede tiempo en planta',
    'embarque_programado_vencido': 'Embarque programado vencido',
    'embarque_pipa_sin_mezcla': 'Embarque en pipa sin lote de mezcla',
    'tqpf_ocupacion_alta': 'Tanque TQPF con ocupación alta',
}


def _titulo_por_tipo(tipo):
    """Genera un título legible para la notificación según el tipo de alerta."""
    if tipo in _TITULOS_POR_TIPO:
        return _TITULOS_POR_TIPO[tipo]
    if tipo.startswith('empaque_'):
        return 'Empaque: stock fuera de parámetros'
    return 'Alerta del sistema'


def _generar_notificaciones(alerta):
    """
    Crea notificaciones para los usuarios del área correspondiente.
    - Si hay registros en alerta_destinatarios para el tipo, solo esas áreas.
    - Si no hay registros, todos los usuarios activos.
    - No crea notificaciones duplicadas (id_alerta + id_usuario).
    """
    destinatarios = AlertaDestinatario.query.filter_by(tipo_alerta=alerta.tipo).all()
    if destinatarios:
        areas = [d.area for d in destinatarios]
        usuarios = Usuario.query.filter(
            Usuario.activo == True,  # noqa: E712
            Usuario.area.in_(areas)
        ).all()
    else:
        usuarios = Usuario.query.filter_by(activo=True).all()

    for u in usuarios:
        existe = Notificacion.query.filter_by(
            id_alerta=alerta.id,
            id_usuario=u.id_usuario
        ).first()
        if existe is None:
            db.session.add(Notificacion(
                id_usuario=u.id_usuario,
                id_alerta=alerta.id,
                titulo=_titulo_por_tipo(alerta.tipo),
                mensaje=alerta.mensaje,
                url=alerta.url,
                leida=False,
            ))


def sincronizar_alertas():
    """
    Calcula alertas actuales, las persiste en la tabla `alertas` (upsert por
    clave_unica), genera notificaciones por área y cierra las que ya no
    aplican. Devuelve la lista de alertas activas (dicts) para el dashboard.

    Regla anti-spam: una alerta activa no vuelve a generar notificaciones.
    Solo se notifica cuando una alerta nueva aparece o una cerrada reaparece.
    """
    alertas_calculadas = calcular_alertas()
    claves_actuales = {a['clave_unica'] for a in alertas_calculadas}

    # 1. Cerrar alertas activas que ya no aplican
    if claves_actuales:
        Alerta.query.filter(
            Alerta.estado == 'activa',
            ~Alerta.clave_unica.in_(claves_actuales)
        ).update({Alerta.estado: 'cerrada', Alerta.actualizada_en: datetime.utcnow()},
                 synchronize_session=False)
    else:
        Alerta.query.filter_by(estado='activa').update(
            {Alerta.estado: 'cerrada', Alerta.actualizada_en: datetime.utcnow()},
            synchronize_session=False)

    # 2. Upsert de alertas calculadas
    for a in alertas_calculadas:
        alerta = Alerta.query.filter_by(clave_unica=a['clave_unica']).first()
        if alerta is None:
            alerta = Alerta(
                tipo=a['tipo'],
                severidad=a['severidad'],
                clave_unica=a['clave_unica'],
                mensaje=a['mensaje'],
                url=a['url'],
                estado='activa',
            )
            db.session.add(alerta)
            db.session.flush()
            _generar_notificaciones(alerta)
        else:
            alerta.tipo = a['tipo']
            alerta.severidad = a['severidad']
            alerta.mensaje = a['mensaje']
            alerta.url = a['url']
            if alerta.estado == 'cerrada':
                # Reapareció: reabrir y volver a notificar
                alerta.estado = 'activa'
                alerta.atendida_por = None
                alerta.atendida_en = None
                _generar_notificaciones(alerta)

    db.session.commit()

    activas = Alerta.query.filter_by(estado='activa').order_by(
        db.case(
            (Alerta.severidad == 'danger', 0),
            (Alerta.severidad == 'warning', 1),
            else_=2
        ),
        Alerta.creada_en.desc()
    ).all()

    return [{
        'id': a.id,
        'tipo': a.tipo,
        'severidad': a.severidad,
        'clave_unica': a.clave_unica,
        'mensaje': a.mensaje,
        'url': a.url,
    } for a in activas]


# ----------------------------------------------------------------------
# Cuadre de galonaje
# ----------------------------------------------------------------------

# Constante: galones por litro (1 galón US = 3.78541 L)
GALONES_POR_LITRO = Decimal('3.78541')


def _get_densidad(id_producto, brix):
    """
    Devuelve la densidad (kg/L) para un producto y Brix dados.
    - Busca en la tabla densidad_brix.
    - Si hay una fila con el Brix exacto, la devuelve.
    - Si no, interpola linealmente entre las dos filas más cercanas.
    - Si no hay datos para el producto, devuelve None.
    """
    if id_producto is None or brix is None:
        return None
    brix = float(brix)
    filas = DensidadBrix.query.filter_by(id_producto=id_producto) \
        .order_by(DensidadBrix.brix).all()
    if not filas:
        return None
    # Brix exacto
    for f in filas:
        if abs(float(f.brix) - brix) < 1e-6:
            return float(f.densidad_kg_l)
    # Fuera de rango: usar el extremo más cercano (sin extrapolar)
    if brix <= float(filas[0].brix):
        return float(filas[0].densidad_kg_l)
    if brix >= float(filas[-1].brix):
        return float(filas[-1].densidad_kg_l)
    # Interpolación lineal
    for i in range(len(filas) - 1):
        b0 = float(filas[i].brix)
        b1 = float(filas[i + 1].brix)
        if b0 < brix < b1:
            d0 = float(filas[i].densidad_kg_l)
            d1 = float(filas[i + 1].densidad_kg_l)
            return d0 + (d1 - d0) * (brix - b0) / (b1 - b0)
    return None


def _estado_cuadre(dif_pct, tolerancia_pct):
    """
    Devuelve el estado del cuadre según la diferencia porcentual.
    - 'cuadra': |dif| <= 0.1% (diferencia despreciable)
    - 'dentro_tolerancia': 0.1% < |dif| <= tolerancia
    - 'descuadre': |dif| > tolerancia
    - 'sin_datos': no hay suficientes datos para comparar
    """
    if dif_pct is None:
        return 'sin_datos'
    tol = float(tolerancia_pct) if tolerancia_pct is not None else 1.0
    adif = abs(dif_pct)
    if adif <= 0.1:
        return 'cuadra'
    if adif <= tol:
        return 'dentro_tolerancia'
    return 'descuadre'


def _calcular_cuadre_embarque(embarque, tolerancia_pct):
    """
    Calcula el cuadre de galonaje para un embarque.
    Compara tres cifras:
      1. Galones por peso: neto_kg ÷ (densidad_kg/L × 3.78541)
      2. Galones declarados por lote: SUM(embarque_lotes.cantidad)
      3. Galones de inventario: SUM(movimientos.galones) vía id_movimiento

    Devuelve un dict con todas las cifras, diferencias y estados.
    """
    # --- Brix promedio del embarque (promedio de los lotes) ---
    lotes = embarque.lotes or []
    brix_values = []
    for el in lotes:
        if el.lote and el.lote.brix is not None:
            brix_values.append(float(el.lote.brix))
    brix_promedio = (sum(brix_values) / len(brix_values)) if brix_values else None

    # --- 1. Galones por peso ---
    galones_peso = None
    peso_neto = None
    densidad = None
    if embarque.pesos and embarque.pesos.peso_neto_kg is not None:
        peso_neto = float(embarque.pesos.peso_neto_kg)
        id_producto = embarque.id_producto
        densidad = _get_densidad(id_producto, brix_promedio)
        if densidad and densidad > 0:
            # galones = kg ÷ (densidad kg/L × 3.78541 L/gal)
            galones_peso = peso_neto / (densidad * float(GALONES_POR_LITRO))

    # --- 2. Galones declarados por lote ---
    galones_lotes = 0.0
    for el in lotes:
        if el.cantidad is not None:
            galones_lotes += float(el.cantidad)

    # --- 3. Galones de inventario (movimientos vinculados) ---
    galones_inventario = None
    movimientos_encontrados = []
    for el in lotes:
        if el.id_movimiento is not None and el.movimiento:
            mov = el.movimiento
            # Los movimientos de salida restan; el signo depende de cómo
            # se registró. Aquí usamos el valor absoluto para la comparación.
            mov_val = float(mov.galones) if mov.galones is not None else 0.0
            movimientos_encontrados.append(mov_val)
    if movimientos_encontrados:
        galones_inventario = sum(movimientos_encontrados)

    # --- Diferencias ---
    def _dif(cifra_base, cifra_ref):
        if cifra_base is None or cifra_ref is None or cifra_ref == 0:
            return None
        return ((cifra_base - cifra_ref) / cifra_ref) * 100.0

    # Base de comparación: lotes (papel). Si no hay lotes, usar peso.
    base = galones_lotes if galones_lotes > 0 else galones_peso

    dif_peso_lotes = _dif(galones_peso, galones_lotes)
    dif_inv_lotes = _dif(galones_inventario, galones_lotes)
    dif_peso_inv = _dif(galones_peso, galones_inventario)

    # Estado general: peor caso entre peso y inventario contra lotes
    difs = [d for d in (dif_peso_lotes, dif_inv_lotes) if d is not None]
    peor_dif = max(difs, key=abs) if difs else None
    estado = _estado_cuadre(peor_dif, tolerancia_pct)

    return {
        'embarque': embarque,
        'brix_promedio': brix_promedio,
        'densidad': densidad,
        'peso_neto': peso_neto,
        'galones_peso': galones_peso,
        'galones_lotes': galones_lotes,
        'galones_inventario': galones_inventario,
        'dif_peso_lotes': dif_peso_lotes,
        'dif_inv_lotes': dif_inv_lotes,
        'dif_peso_inv': dif_peso_inv,
        'dif_lotes_abs': galones_lotes - galones_inventario if galones_inventario is not None else None,
        'dif_peso_lotes_abs': galones_peso - galones_lotes if galones_peso is not None else None,
        'estado': estado,
    }


def _empaque_format_numero(valor, um=None):
    """
    Formatea un número para UI según la unidad de medida.
    - Pz: sin decimales.
    - Kg: hasta 3 decimales (mostrando los no-cero).
    - Otros: 2 decimales por defecto.

    Devuelve str con separador de miles.
    """
    if valor is None:
        return ''
    try:
        d = Decimal(str(valor))
    except Exception:
        return str(valor)
    if um == 'Pz':
        return f'{int(d):,}'
    if um == 'Kg':
        s = f'{d:,.3f}'.rstrip('0').rstrip('.')
        return s if s else '0'
    return f'{d:,.2f}'


def _empaque_tiene_movimientos(codigo):
    """
    Devuelve True si el artículo tiene al menos un movimiento
    (entrada, salida o ajuste). Usado para prohibir ELIMINACIÓN física;
    solo se puede INACTIVAR.
    """
    if not codigo:
        return False
    if EmpaqueEntrada.query.filter_by(codigo=codigo).first():
        return True
    if EmpaqueSalida.query.filter_by(codigo=codigo).first():
        return True
    if EmpaqueAjuste.query.filter_by(codigo=codigo).first():
        return True
    return False


# =====================================================================
# ===== FIN HELPERS EMPAQUE ===========================================
# =====================================================================

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
        if endpoint not in RUTAS_POST_PERMITIDAS_INVITADO:
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

@app.before_request
def _forzar_cambio_password():
    if not current_user.is_authenticated:
        return None
    endpoint = (request.endpoint or '').split('.')[-1]
    # Permitir rutas de seguridad y logout mientras se cambia la contraseña
    if endpoint in ('cambiar_password', 'logout', 'login', 'static'):
        return None
    if getattr(current_user, 'debe_cambiar_password', False):
        flash('Por seguridad, debe cambiar su contraseña antes de continuar.', 'warning')
        return redirect(url_for('cambiar_password'))

# =====================================================================
# Helpers del flujo Silo
# Compartidos por la captura directa a silo y por el traspaso TQPF -> Silo.
# =====================================================================

# Nombres en español de los tipos de producto del silo.
TIPO_PRODUCTO_ESP = {
    'jugo': 'Jugo',
    'concentrado': 'Concentrado',
    'aceite': 'Aceite',
    'nfc': 'NFC',
}


def _permitir_entrada_directa():
    """
    Indica si el sistema permite capturar entradas directas a silo (sin pasar
    por TQPF). Se controla con el parámetro `permitir_entrada_directa_silo`.
    """
    valor = _get_parametro_str('permitir_entrada_directa_silo', '1')
    return str(valor).strip().lower() not in ('0', 'false', 'no')


def _preparar_entrada_silo(id_silo, tipo_producto, galones):
    """
    Valida que un silo pueda recibir `galones` del `tipo_producto` indicado y
    deja el silo listo para la entrada (tipo de producto y capacidad).

    Es la validación compartida entre la captura directa a silo y el traspaso
    desde TQPF, para que ambos caminos apliquen las MISMAS reglas.

    Devuelve (silo, galones_actuales, error):
      - error es None si todo está correcto; si no, contiene el mensaje
        amigable que debe mostrarse al usuario.
    """
    silo = Silo.query.get(id_silo)
    if not silo:
        return None, Decimal('0'), 'Error: El silo seleccionado no existe.'

    inventario_actual = InventarioSilo.query.filter_by(id_silo=silo.id_silo).all()
    galones_actuales = sum((Decimal(str(i.galones or 0)) for i in inventario_actual), Decimal('0'))

    # Si el silo está vacío, se refresca su tipo con el tipo permitido.
    if galones_actuales <= 0 and silo.tipo_permitido:
        silo.tipo_producto = silo.tipo_permitido
    elif galones_actuales <= 0 and silo.tipo_producto is not None:
        silo.tipo_producto = None

    if silo.tipo_permitido and tipo_producto != silo.tipo_permitido:
        return silo, galones_actuales, (
            f'Error: Este silo está destinado a '
            f'{TIPO_PRODUCTO_ESP.get(silo.tipo_permitido, silo.tipo_permitido)}.')

    if silo.tipo_producto:
        if silo.tipo_producto != tipo_producto:
            return silo, galones_actuales, (
                f'Error: Este silo ya tiene '
                f'{TIPO_PRODUCTO_ESP.get(silo.tipo_producto, silo.tipo_producto)}. '
                f'No puedes agregar {TIPO_PRODUCTO_ESP.get(tipo_producto, tipo_producto)}.')
    else:
        # Primera vez que se llena el silo: se fija su tipo de producto.
        silo.tipo_producto = silo.tipo_permitido or tipo_producto

    capacidad_gal = Decimal(str(silo.capacidad_gal or 0))
    if (galones_actuales + Decimal(str(galones))) > capacidad_gal:
        disponibles = capacidad_gal - galones_actuales
        return silo, galones_actuales, (
            f'Error: Capacidad del silo excedida. Galones disponibles: {float(disponibles):.2f}')

    return silo, galones_actuales, None

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
            lote = item.lote

            # Por cliente
            cliente_nombre = None
            if lote and lote.cliente:
                cliente_nombre = lote.cliente.nombre_cliente
            elif lote and lote.cliente_manual:
                cliente_nombre = lote.cliente_manual
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
            if lote and lote.estado:
                estado_nombre = lote.estado.nombre_estado
            else:
                estado_nombre = 'Sin estado'
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
        'capacidad_total': capacidad_total,
        'capacidad_disponible': max(capacidad_total - total_galones, 0),
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
        # Restricción configurable: si el parámetro está apagado, la captura
        # directa a silo se bloquea y sólo se permite el traspaso desde TQPF.
        if not _permitir_entrada_directa():
            flash('La entrada directa a silo está deshabilitada. '
                  'Usa el traspaso desde TQPF.', 'danger')
            return redirect(url_for('inventario_tqpf'))
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

            # Validaciones compartidas del silo (tipo permitido, compatibilidad
            # con el producto que ya contiene y capacidad disponible).
            silo, galones_actuales, err_silo = _preparar_entrada_silo(
                id_silo, tipo_producto, galones)
            if err_silo:
                flash(err_silo, 'danger')
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

@app.route('/admin/usuarios/<int:id_usuario>/editar', methods=['GET', 'POST'])
@login_required
def editar_usuario(id_usuario):
    if current_user.rol != 'administrador':
        flash('Acceso denegado.')
        return redirect(url_for('index'))
    usu = Usuario.query.get_or_404(id_usuario)
    if request.method == 'POST':
        nombre = request.form.get('nombre')
        usuario = request.form.get('usuario')
        password = request.form.get('password')
        rol = request.form.get('rol')
        # Validar unicidad del nombre de usuario (excluyendo el actual)
        otro = Usuario.query.filter_by(usuario=usuario).first()
        if otro and otro.id_usuario != id_usuario:
            flash('El nombre de usuario ya existe.')
        else:
            usu.nombre = nombre
            usu.usuario = usuario
            usu.rol = rol
            if password:
                usu.password = generate_password_hash(password)
            db.session.commit()
            flash('Usuario actualizado correctamente.')
            return redirect(url_for('gestionar_usuarios'))
    return render_template('admin/usuario_form.html', usuario=usu)

@app.route('/admin/usuarios/<int:id_usuario>/eliminar', methods=['POST'])
@login_required
def eliminar_usuario(id_usuario):
    if current_user.rol != 'administrador':
        flash('Acceso denegado.')
        return redirect(url_for('index'))
    if id_usuario == current_user.id_usuario:
        flash('No puedes eliminar tu propio usuario.', 'warning')
        return redirect(url_for('gestionar_usuarios'))
    usu = Usuario.query.get_or_404(id_usuario)
    try:
        db.session.delete(usu)
        db.session.commit()
        flash(f'Usuario "{usu.usuario}" eliminado correctamente.', 'success')
    except Exception:
        # Si hay registros dependientes, desactivar en lugar de eliminar
        db.session.rollback()
        usu.activo = False
        db.session.commit()
        flash(f'No se pudo eliminar por registros asociados. Se desactivó el usuario "{usu.usuario}".', 'warning')
    return redirect(url_for('gestionar_usuarios'))

@app.route('/admin/usuarios/<int:id_usuario>/toggle', methods=['POST'])
@login_required
def toggle_usuario(id_usuario):
    if current_user.rol != 'administrador':
        flash('Acceso denegado.')
        return redirect(url_for('index'))
    if id_usuario == current_user.id_usuario:
        flash('No puedes cambiar el estado de tu propio usuario.', 'warning')
        return redirect(url_for('gestionar_usuarios'))
    usu = Usuario.query.get_or_404(id_usuario)
    usu.activo = not usu.activo
    db.session.commit()
    flash(f'Usuario {"activado" if usu.activo else "desactivado"} correctamente.', 'success')
    return redirect(url_for('gestionar_usuarios'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        usuario = (request.form.get('usuario') or '').strip()
        password = request.form.get('password') or ''

        # Límite de intentos fallidos por IP + usuario (5 por ventana de 15 min)
        MAX_INTENTOS = 5
        VENTANA_MIN = 15
        ahora = datetime.now()
        key = f'_login_fails_{request.remote_addr}_{usuario}'
        fallos = session.get(key, {'count': 0, 'until': None})
        until = fallos.get('until')
        if until:
            until_dt = datetime.fromisoformat(until)
            if ahora < until_dt:
                restante = int((until_dt - ahora).total_seconds() // 60) + 1
                flash(f'Demasiados intentos fallidos. Intente nuevamente en {restante} minuto(s).')
                return render_template('login.html')
            else:
                fallos = {'count': 0, 'until': None}

        user = Usuario.query.filter_by(usuario=usuario).first()

        if user and check_password_hash(user.password, password):
            if user.activo:
                # Resetear contador de fallos al autenticar correctamente
                session.pop(key, None)
                login_user(user)
                if user.debe_cambiar_password:
                    flash('Por seguridad, debe cambiar su contraseña antes de continuar.', 'warning')
                    return redirect(url_for('cambiar_password'))
                return redirect(url_for('index'))
            else:
                flash('Usuario inactivo. Contacte al administrador.')
        else:
            fallos['count'] = fallos.get('count', 0) + 1
            if fallos['count'] >= MAX_INTENTOS:
                fallos['until'] = (ahora + timedelta(minutes=VENTANA_MIN)).isoformat()
                flash(f'Demasiados intentos fallidos. Intente nuevamente en {VENTANA_MIN} minutos.')
            else:
                flash('Usuario o contraseña incorrectos.')
            session[key] = fallos
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))


# =====================================================================
# ===== NOTIFICACIONES =================================================
# =====================================================================

@app.route('/notificaciones')
@login_required
def notificaciones():
    """Página de notificaciones del usuario."""
    sincronizar_alertas()
    todas = Notificacion.query.filter_by(id_usuario=current_user.id_usuario) \
        .order_by(Notificacion.creada_en.desc()).limit(200).all()
    return render_template('notificaciones.html', notificaciones=todas)


@app.route('/notificaciones/<int:id_notif>/leer', methods=['POST'])
@login_required
def notificacion_leer(id_notif):
    """Marca una notificación como leída (solo si pertenece al usuario)."""
    n = Notificacion.query.get_or_404(id_notif)
    if n.id_usuario != current_user.id_usuario:
        abort(403)
    n.leida = True
    db.session.commit()
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'ok': True, 'no_leidas': _contar_no_leidas()})
    return redirect(request.referrer or url_for('notificaciones'))


@app.route('/notificaciones/leer-todas', methods=['POST'])
@login_required
def notificacion_leer_todas():
    """Marca todas las notificaciones del usuario como leídas."""
    Notificacion.query.filter_by(
        id_usuario=current_user.id_usuario, leida=False
    ).update({Notificacion.leida: True}, synchronize_session=False)
    db.session.commit()
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'ok': True, 'no_leidas': 0})
    return redirect(url_for('notificaciones'))


@app.route('/api/notificaciones')
@login_required
def api_notificaciones():
    """
    Endpoint JSON para polling del navegador (cada 60 s).
    Devuelve: no_leidas (int) y lista de notificaciones recientes (5).
    """
    sincronizar_alertas()
    no_leidas = _contar_no_leidas()
    recientes = Notificacion.query.filter_by(id_usuario=current_user.id_usuario) \
        .order_by(Notificacion.creada_en.desc()).limit(10).all()
    return jsonify({
        'no_leidas': no_leidas,
        'notificaciones': [{
            'id': n.id,
            'titulo': n.titulo,
            'mensaje': n.mensaje,
            'url': n.url,
            'leida': n.leida,
            'creada_en': n.creada_en.strftime('%Y-%m-%d %H:%M') if n.creada_en else '',
        } for n in recientes],
    })


def _contar_no_leidas():
    if not current_user.is_authenticated:
        return 0
    return Notificacion.query.filter_by(
        id_usuario=current_user.id_usuario, leida=False
    ).count()


@app.route('/cambiar-password', methods=['GET', 'POST'])
@login_required
def cambiar_password():
    if request.method == 'POST':
        actual = request.form.get('password_actual') or ''
        nueva = request.form.get('password_nueva') or ''
        confirmar = request.form.get('password_confirmar') or ''

        if not check_password_hash(current_user.password, actual):
            flash('La contraseña actual es incorrecta.', 'danger')
        elif len(nueva) < 8:
            flash('La nueva contraseña debe tener al menos 8 caracteres.', 'danger')
        elif nueva != confirmar:
            flash('Las contraseñas nuevas no coinciden.', 'danger')
        elif nueva == actual:
            flash('La nueva contraseña no puede ser igual a la actual.', 'danger')
        else:
            current_user.password = generate_password_hash(nueva)
            current_user.debe_cambiar_password = False
            db.session.commit()
            flash('Contraseña actualizada correctamente.', 'success')
            return redirect(url_for('index'))

    return render_template('cambiar_password.html',
                           forzar_cambio=bool(getattr(current_user, 'debe_cambiar_password', False)))

@app.route('/reset-silos', methods=['POST'])
@login_required
def reset_silos():
    if (current_user.rol or '').strip().lower() != 'administrador':
        flash('Acceso denegado: solo el administrador puede resetear los silos.', 'danger')
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

@app.route('/admin/silos', methods=['GET', 'POST'])
@login_required
def configurar_silos():
    """Configuración de silos: alta, edición, activar/desactivar y eliminar."""
    if current_user.rol != 'administrador':
        flash('Acceso denegado.', 'danger')
        return redirect(url_for('index'))

    if request.method == 'POST':
        accion = request.form.get('accion', '').strip()
        id_edit = _parse_int_or_none(request.form.get('id_silo'))
        try:
            if accion == 'guardar':
                if id_edit:
                    silo = Silo.query.get_or_404(id_edit)
                else:
                    silo = Silo()
                    db.session.add(silo)
                silo.nombre_silo = (request.form.get('nombre_silo') or '').strip()
                silo.capacidad_gal = _parse_decimal_or_none(request.form.get('capacidad_gal'))
                silo.capacidad_barriles = _parse_decimal_or_none(request.form.get('capacidad_barriles'))
                silo.tipo_producto = (request.form.get('tipo_producto') or '').strip() or None
                silo.tipo_permitido = (request.form.get('tipo_permitido') or '').strip() or None
                if not silo.nombre_silo:
                    flash('El nombre del silo es obligatorio.', 'danger')
                    db.session.rollback()
                    return redirect(url_for('configurar_silos'))
                db.session.commit()
                flash(f'Silo "{silo.nombre_silo}" guardado correctamente.', 'success')
            elif accion == 'toggle':
                silo = Silo.query.get_or_404(id_edit)
                silo.estado = 'inactivo' if silo.estado == 'activo' else 'activo'
                db.session.commit()
                flash(f'Silo "{silo.nombre_silo}" {silo.estado}.', 'success')
            elif accion == 'eliminar':
                silo = Silo.query.get_or_404(id_edit)
                # Validar que no tenga inventario ni movimientos
                tiene_inv = InventarioSilo.query.filter_by(id_silo=id_edit).first()
                tiene_mov = Movimiento.query.filter_by(id_silo=id_edit).first()
                if tiene_inv or tiene_mov:
                    flash(f'No se puede eliminar el silo "{silo.nombre_silo}" porque tiene inventario o movimientos asociados. Desactívelo en su lugar.', 'danger')
                else:
                    db.session.delete(silo)
                    db.session.commit()
                    flash(f'Silo "{silo.nombre_silo}" eliminado correctamente.', 'success')
        except Exception as e:
            db.session.rollback()
            msg = str(e)
            if 'Duplicate entry' in msg:
                msg = 'Ya existe un silo con ese nombre.'
            flash(f'Error: {msg}', 'danger')
        return redirect(url_for('configurar_silos'))

    silos = Silo.query.order_by(Silo.nombre_silo).all()
    return render_template('admin/silos.html', silos=silos)

# =====================================================================
# Helpers del módulo TQPF
# =====================================================================
REGEX_CODIGO_LOTE = re.compile(r'^\d{3}-\d{8}-\d{6}$')

# Valores por omisión de la purga al traspasar de TQPF a silo. Son
# configurables desde parametros_sistema para poder ajustarlos sin tocar código.
TAMBORES_PURGA_DEFAULT = 2.0
GALONES_TAMBOR_DEFAULT = 52.0


def _calcular_purga_traspaso():
    """
    Calcula la purga que se descuenta del tanque TQPF al traspasar a un silo.

    La purga son los tambores de producto que se quedan en la tubería (el
    producto que llena la línea antes de que el flujo llegue al silo) y que el
    negocio considera merma. El acuerdo es que el tanque baje esos galones
    ADEMÁS de los galones que sí llegan al silo.

    Devuelve (tambores, galones_tambor, galones_purga). Los tres valores se
    leen de parametros_sistema:

      - `tambores_purga_traspaso`: cuántos tambores se descuentan (por omisión 2).
      - `galones_tambor`: galones que tiene cada tambor (por omisión 52).

    Si algún parámetro no existe o no es un número válido, se usan los valores
    por omisión definidos en el módulo.
    """
    tambores = _get_parametro_float('tambores_purga_traspaso', TAMBORES_PURGA_DEFAULT)
    galones_tambor = _get_parametro_float('galones_tambor', GALONES_TAMBOR_DEFAULT)
    if tambores is None:
        tambores = TAMBORES_PURGA_DEFAULT
    if galones_tambor is None:
        galones_tambor = GALONES_TAMBOR_DEFAULT
    purga = Decimal(str(tambores)) * Decimal(str(galones_tambor))
    return tambores, galones_tambor, purga


def _renumerar_posiciones_tqpf(id_tanque):
    """Renumera 1..n las posiciones LIFO del inventario de un tanque TQPF."""
    items = (InventarioTQPF.query.filter_by(id_tanque=id_tanque)
             .order_by(InventarioTQPF.posicion.asc(),
                       InventarioTQPF.id_inventario_tqpf.asc()).all())
    for i, it in enumerate(items, start=1):
        it.posicion = i


def _tqpf_registrar_entrada(form):
    """
    Registra la entrada de un lote a un tanque de proceso (TQPF).

    Flujo real: los lotes se asignan PRIMERO al tanque de pared fría. Si el
    lote no existe en el catálogo se crea; si ya existe se reutiliza.

    Valida: tanque activo, formato del código de lote, galones > 0, capacidad
    del tanque y que el lote no esté ya en ese mismo tanque.
    Registra un movimiento `entrada_tqpf`.

    Lanza ValueError con un mensaje amigable si algo no cumple.
    """
    id_tanque = _parse_int_or_none(form.get('id_tanque'))
    codigo_lote = (form.get('codigo_lote') or '').strip()
    galones = _parse_decimal_or_none(form.get('galones'))

    tanque = TanqueTQPF.query.get(id_tanque) if id_tanque else None
    if not tanque:
        raise ValueError('Selecciona un tanque válido.')
    if tanque.estado != 'activo':
        raise ValueError(f'El tanque {tanque.nombre_tanque} está inactivo.')
    if not REGEX_CODIGO_LOTE.match(codigo_lote):
        raise ValueError('Formato de lote incorrecto. Usa: 005-20251210-044497')
    if galones is None or galones <= 0:
        raise ValueError('Captura una cantidad de galones mayor a cero.')

    # Capacidad del tanque (sólo se valida si el tanque tiene capacidad capturada).
    cap = Decimal(str(tanque.capacidad_gal or 0))
    if cap > 0:
        actuales = sum((Decimal(str(i.galones or 0))
                        for i in InventarioTQPF.query.filter_by(id_tanque=tanque.id_tanque).all()),
                       Decimal('0'))
        if actuales + galones > cap:
            raise ValueError(f'Capacidad del tanque excedida. '
                             f'Disponibles: {float(cap - actuales):.2f} gal.')

    # Lote: se crea si no existe; si existe se reutiliza.
    lote = Lote.query.filter_by(codigo_lote=codigo_lote).first()
    if not lote:
        lote = Lote(
            codigo_lote=codigo_lote,
            fecha_lote=_parse_date_or_none(form.get('fecha_lote')),
            brix=_parse_decimal_or_none(form.get('brix')),
            relacion=_parse_decimal_or_none(form.get('relacion')),
            pulpa=_parse_decimal_or_none(form.get('pulpa')),
            id_estado=_parse_int_or_none(form.get('id_estado')),
            id_cliente=_parse_int_or_none(form.get('id_cliente')),
            cliente_manual=(form.get('cliente_manual') or '').strip() or None,
        )
        db.session.add(lote)
        db.session.flush()

    # No se permite el mismo lote dos veces en el mismo tanque.
    if InventarioTQPF.query.filter_by(id_tanque=tanque.id_tanque, id_lote=lote.id_lote).first():
        raise ValueError(f'El lote {codigo_lote} ya está registrado en {tanque.nombre_tanque}.')

    # El último ingreso queda en la posición 1 (consumo LIFO).
    for it in InventarioTQPF.query.filter_by(id_tanque=tanque.id_tanque).all():
        it.posicion = (it.posicion or 0) + 1

    db.session.add(InventarioTQPF(
        id_tanque=tanque.id_tanque,
        id_lote=lote.id_lote,
        posicion=1,
        galones=galones,
    ))
    db.session.add(Movimiento(
        tipo_movimiento='entrada_tqpf',
        id_tanque=tanque.id_tanque,
        id_lote=lote.id_lote,
        galones=galones,
        id_usuario=current_user.id_usuario,
        observaciones=f'Entrada a {tanque.nombre_tanque}',
    ))
    db.session.commit()


@app.route('/tqpf', methods=['GET', 'POST'])
@login_required
def inventario_tqpf():
    """
    Inventario de tanques de proceso (TQPF).

    Los lotes se asignan primero al tanque de pared fría y de ahí se traspasan
    al silo. Esta pantalla muestra el contenido de cada tanque (lote, Brix y
    galones), el total y el porcentaje de ocupación, y permite registrar la
    entrada de un lote y vaciar un lote del tanque.
    """
    if request.method == 'POST':
        accion = (request.form.get('accion') or '').strip()
        try:
            if accion == 'entrada':
                _tqpf_registrar_entrada(request.form)
                flash('Entrada registrada en el tanque correctamente.', 'success')
            elif accion == 'vaciar':
                item = InventarioTQPF.query.get_or_404(
                    _parse_int_or_none(request.form.get('id_inventario_tqpf')))
                id_tanque = item.id_tanque
                db.session.delete(item)
                db.session.flush()
                _renumerar_posiciones_tqpf(id_tanque)
                db.session.commit()
                flash('Se vació el lote del tanque.', 'success')
        except ValueError as e:
            db.session.rollback()
            flash(str(e), 'danger')
        except Exception as e:
            db.session.rollback()
            flash(f'Error: {e}', 'danger')
        return redirect(url_for('inventario_tqpf'))

    tanques = TanqueTQPF.query.order_by(TanqueTQPF.nombre_tanque).all()
    detalle = {}
    total_general = Decimal('0')
    for t in tanques:
        items = (InventarioTQPF.query.filter_by(id_tanque=t.id_tanque)
                 .order_by(InventarioTQPF.posicion.asc(),
                           InventarioTQPF.id_inventario_tqpf.asc()).all())
        galones = sum((Decimal(str(i.galones or 0)) for i in items), Decimal('0'))
        cap = Decimal(str(t.capacidad_gal or 0))
        pct = (galones / cap * 100) if cap > 0 else Decimal('0')
        detalle[t.id_tanque] = {'filas': items, 'galones': galones, 'pct': pct}
        total_general += galones

    estados = EstadoProducto.query.all()
    clientes = Cliente.query.all()
    silos = Silo.query.filter_by(estado='activo').all()
    # Datos de la purga para mostrarlos en el modal de traspaso.
    tambores_purga, galones_tambor, galones_purga = _calcular_purga_traspaso()
    return render_template('tqpf.html', tanques=tanques, detalle=detalle,
                           total_general=total_general, estados=estados,
                           clientes=clientes, silos=silos,
                           tambores_purga=tambores_purga,
                           galones_tambor=galones_tambor,
                           galones_purga=galones_purga)


@app.route('/tqpf/purgas')
@login_required
def purgas_tqpf():
    """
    Apartado de control de purgas.

    Muestra los movimientos de tipo `purga`: los tambores de producto que se
    pierden en la línea al traspasar de un tanque TQPF a un silo. Permite
    filtrar por tanque y por rango de fechas y muestra el total de galones y de
    tambores purgados, para llevar el control de la merma.
    """
    id_tanque = _parse_int_or_none(request.args.get('id_tanque'))
    fecha_inicio = request.args.get('fecha_inicio')
    fecha_fin = request.args.get('fecha_fin')

    query = Movimiento.query.filter_by(tipo_movimiento='purga')
    if id_tanque:
        query = query.filter_by(id_tanque=id_tanque)
    if fecha_inicio:
        try:
            query = query.filter(Movimiento.fecha_movimiento >=
                                 datetime.strptime(fecha_inicio, '%Y-%m-%d'))
        except ValueError:
            fecha_inicio = None
    if fecha_fin:
        try:
            dt_fin = datetime.strptime(fecha_fin, '%Y-%m-%d') + timedelta(days=1)
            query = query.filter(Movimiento.fecha_movimiento < dt_fin)
        except ValueError:
            fecha_fin = None

    purgas = query.order_by(Movimiento.fecha_movimiento.desc()).all()
    total_galones = sum((Decimal(str(m.galones or 0)) for m in purgas), Decimal('0'))

    _, galones_tambor, _ = _calcular_purga_traspaso()
    galones_tambor = Decimal(str(galones_tambor or 0))
    total_tambores = (total_galones / galones_tambor) if galones_tambor > 0 else Decimal('0')

    tanques = TanqueTQPF.query.order_by(TanqueTQPF.nombre_tanque).all()
    return render_template('tqpf_purgas.html', purgas=purgas, tanques=tanques,
                           total_galones=total_galones, total_tambores=total_tambores,
                           galones_tambor=galones_tambor)


@app.route('/tqpf/traspaso', methods=['POST'])
@login_required
def traspasar_tqpf_silo():
    """
    Traspasa un lote de un tanque de proceso (TQPF) hacia un silo.

    - Descuenta `galones` del inventario del tanque (puede ser parcial; si la
      fila llega a 0 se elimina y se renumeran las posiciones LIFO).
    - Aplica las MISMAS validaciones que la entrada al silo (tipo permitido,
      compatibilidad con el producto que ya contiene y capacidad disponible).
    - Coloca el lote en el silo con la posición 1 (último ingresado).
    - Registra dos movimientos: `traspaso_tqpf_silo` (con id_tanque) y la
      entrada correspondiente al silo.
    Todo sucede en UNA transacción; ante cualquier error se revierte.
    """
    if _deny_if_guest():
        return redirect(url_for('index'))
    try:
        id_inv_tqpf = _parse_int_or_none(request.form.get('id_inventario_tqpf'))
        id_silo = _parse_int_or_none(request.form.get('id_silo'))
        tipo_producto = (request.form.get('tipo_producto') or '').strip() or None
        galones = _parse_decimal_or_none(request.form.get('galones'))
        observaciones = (request.form.get('observaciones') or '').strip()

        item = InventarioTQPF.query.get(id_inv_tqpf) if id_inv_tqpf else None
        if not item:
            raise ValueError('El lote seleccionado ya no está en el tanque.')
        if galones is None or galones <= 0:
            raise ValueError('Captura una cantidad de galones mayor a cero.')

        disponible = Decimal(str(item.galones or 0))

        # Purga: tambores de producto que se quedan en la línea. El tanque baja
        # los galones que llegan al silo MÁS la purga, así que debe alcanzar
        # para ambos conceptos.
        tambores_purga, galones_tambor, galones_purga = _calcular_purga_traspaso()
        total_tanque = galones + galones_purga
        if total_tanque > disponible:
            raise ValueError(
                f'El tanque sólo tiene {float(disponible):.2f} gal de ese lote. '
                f'Traspasar {float(galones):.2f} gal requiere {float(total_tanque):.2f} gal '
                f'incluyendo la purga de {tambores_purga:g} tambores '
                f'({float(galones_purga):.2f} gal).')

        # Mismas validaciones que la entrada al silo.
        silo, _g_act, err_silo = _preparar_entrada_silo(id_silo, tipo_producto, galones)
        if err_silo:
            raise ValueError(err_silo.replace('Error: ', ''))

        tanque = item.tanque
        id_tanque = item.id_tanque
        id_lote = item.id_lote
        codigo_lote = item.lote.codigo_lote if item.lote else id_lote

        # 1) Descontar del tanque (galones al silo + purga) y eliminar la fila
        #    si queda en cero.
        if total_tanque >= disponible:
            db.session.delete(item)
        else:
            item.galones = disponible - total_tanque
        db.session.flush()
        _renumerar_posiciones_tqpf(id_tanque)

        # 2) Ingresar al silo en la posición 1 (LIFO).
        existente = InventarioSilo.query.filter_by(
            id_silo=silo.id_silo, id_lote=id_lote).first()
        if existente:
            # El lote ya estaba en el silo: se suma a su contenido.
            existente.galones = Decimal(str(existente.galones or 0)) + galones
        else:
            for it in InventarioSilo.query.filter_by(id_silo=silo.id_silo).all():
                it.posicion = (it.posicion or 0) + 1
            db.session.add(InventarioSilo(
                id_silo=silo.id_silo,
                id_lote=id_lote,
                posicion=1,
                galones=galones,
            ))
        db.session.flush()

        # 3) Movimientos: traspaso (tanque), entrada (silo) y purga (merma).
        obs = f'Traspaso {tanque.nombre_tanque} -> {silo.nombre_silo} (Lote {codigo_lote})'
        if observaciones:
            obs = f'{obs}. {observaciones}'
        db.session.add(Movimiento(
            tipo_movimiento='traspaso_tqpf_silo',
            id_tanque=id_tanque,
            id_silo=silo.id_silo,
            id_lote=id_lote,
            galones=galones,
            id_usuario=current_user.id_usuario,
            observaciones=obs,
        ))
        db.session.add(Movimiento(
            tipo_movimiento='entrada',
            id_silo=silo.id_silo,
            id_lote=id_lote,
            galones=galones,
            id_usuario=current_user.id_usuario,
            observaciones=obs,
        ))
        # Purga: tambores que se pierden en la línea y que también bajan del
        # tanque. Se guarda como movimiento propio para poder llevar su control.
        if galones_purga > 0:
            db.session.add(Movimiento(
                tipo_movimiento='purga',
                id_tanque=id_tanque,
                id_lote=id_lote,
                galones=galones_purga,
                id_usuario=current_user.id_usuario,
                observaciones=(
                    f'Purga de {tambores_purga:g} tambores '
                    f'({float(galones_tambor):.2f} gal/tambor) al traspasar '
                    f'{tanque.nombre_tanque} -> {silo.nombre_silo} (Lote {codigo_lote}).'
                ),
            ))
        db.session.commit()
        flash(f'Se traspasaron {float(galones):.2f} gal del lote {codigo_lote} '
              f'de {tanque.nombre_tanque} a {silo.nombre_silo}. '
              f'Se descontaron {float(galones_purga):.2f} gal de purga '
              f'({tambores_purga:g} tambores).', 'success')
    except ValueError as e:
        db.session.rollback()
        flash(f'Error: {e}', 'danger')
    except Exception as e:
        db.session.rollback()
        flash(f'Ocurrió un error al traspasar el lote: {e}', 'danger')
    else:
        # Evaluar alertas después de un traspaso exitoso.
        try:
            sincronizar_alertas()
        except Exception:
            db.session.rollback()
    return redirect(url_for('inventario_tqpf'))


@app.route('/admin/tqpf', methods=['GET', 'POST'])
@login_required
def configurar_tqpf():
    """Configuración de tanques de proceso (TQPF): alta, edición, activar/desactivar y eliminar."""
    if current_user.rol != 'administrador':
        flash('Acceso denegado.', 'danger')
        return redirect(url_for('index'))

    if request.method == 'POST':
        accion = (request.form.get('accion') or '').strip()
        id_edit = _parse_int_or_none(request.form.get('id_tanque'))
        try:
            if accion == 'guardar':
                if id_edit:
                    tanque = TanqueTQPF.query.get_or_404(id_edit)
                else:
                    tanque = TanqueTQPF()
                    db.session.add(tanque)
                tanque.nombre_tanque = (request.form.get('nombre_tanque') or '').strip()
                tanque.capacidad_gal = _parse_decimal_or_none(request.form.get('capacidad_gal'))
                tanque.tipo_producto = (request.form.get('tipo_producto') or '').strip() or None
                if not tanque.nombre_tanque:
                    flash('El nombre del tanque es obligatorio.', 'danger')
                    db.session.rollback()
                    return redirect(url_for('configurar_tqpf'))
                db.session.commit()
                flash(f'Tanque "{tanque.nombre_tanque}" guardado correctamente.', 'success')
            elif accion == 'toggle':
                tanque = TanqueTQPF.query.get_or_404(id_edit)
                tanque.estado = 'inactivo' if tanque.estado == 'activo' else 'activo'
                db.session.commit()
                flash(f'Tanque "{tanque.nombre_tanque}" {tanque.estado}.', 'success')
            elif accion == 'eliminar':
                tanque = TanqueTQPF.query.get_or_404(id_edit)
                # No se permite eliminar si todavía tiene inventario asociado.
                tiene_inv = InventarioTQPF.query.filter_by(id_tanque=id_edit).first()
                if tiene_inv:
                    flash(f'No se puede eliminar el tanque "{tanque.nombre_tanque}" porque tiene inventario asociado. Desactívelo en su lugar.', 'danger')
                else:
                    db.session.delete(tanque)
                    db.session.commit()
                    flash(f'Tanque "{tanque.nombre_tanque}" eliminado correctamente.', 'success')
        except Exception as e:
            db.session.rollback()
            msg = str(e)
            if 'Duplicate entry' in msg:
                msg = 'Ya existe un tanque con ese nombre.'
            flash(f'Error: {msg}', 'danger')
        return redirect(url_for('configurar_tqpf'))

    tanques = TanqueTQPF.query.order_by(TanqueTQPF.nombre_tanque).all()
    return render_template('admin/tqpf.html', tanques=tanques)

@app.route('/admin/reportes')
@login_required
def reportes():
    """Pantalla de reportes: inventario por silo y embarques por periodo."""
    # Reporte de inventario por silo
    silos = Silo.query.order_by(Silo.nombre_silo).all()
    inventario = []
    total_gal = Decimal('0')
    total_cap = Decimal('0')
    for s in silos:
        items = InventarioSilo.query.filter_by(id_silo=s.id_silo).all()
        galones = sum((Decimal(str(it.galones or 0)) for it in items), Decimal('0'))
        cap = Decimal(str(s.capacidad_gal or 0))
        pct = (galones / cap * 100) if cap > 0 else Decimal('0')
        inventario.append({
            'id_silo': s.id_silo,
            'nombre': s.nombre_silo,
            'capacidad_gal': cap,
            'galones': galones,
            'ocupacion_pct': pct,
            'tipo_producto': s.tipo_producto,
            'estado': s.estado,
        })
        total_gal += galones
        total_cap += cap

    # Reporte de embarques por periodo
    fecha_desde = _parse_date_or_none(request.args.get('fecha_desde'))
    fecha_hasta = _parse_date_or_none(request.args.get('fecha_hasta'))
    id_producto = _parse_int_or_none(request.args.get('id_producto'))
    id_cliente = _parse_int_or_none(request.args.get('id_cliente'))

    q = Embarque.query
    if fecha_desde:
        q = q.filter(Embarque.fecha_embarque >= fecha_desde)
    if fecha_hasta:
        q = q.filter(Embarque.fecha_embarque <= fecha_hasta)
    if id_producto:
        q = q.filter(Embarque.id_producto == id_producto)
    if id_cliente:
        q = q.filter(Embarque.id_cliente == id_cliente)
    embarques = q.order_by(Embarque.fecha_embarque.desc()).all()

    # Totales de embarques
    total_embarques_gal = Decimal('0')
    for e in embarques:
        total_embarques_gal += sum((Decimal(str(el.cantidad or 0)) for el in e.lotes), Decimal('0'))

    productos = ProductoEmbarque.query.order_by(ProductoEmbarque.descripcion).all()
    clientes = Cliente.query.order_by(Cliente.nombre_cliente).all()

    return render_template('admin/reportes.html',
                           inventario=inventario,
                           total_gal=total_gal,
                           total_cap=total_cap,
                           embarques=embarques,
                           total_embarques_gal=total_embarques_gal,
                           productos=productos,
                           clientes=clientes,
                           filtros={
                               'fecha_desde': request.args.get('fecha_desde', ''),
                               'fecha_hasta': request.args.get('fecha_hasta', ''),
                               'id_producto': id_producto,
                               'id_cliente': id_cliente,
                           })

@app.route('/admin/reportes/exportar')
@login_required
def exportar_reportes():
    """Exporta el reporte seleccionado a Excel."""
    tipo = request.args.get('tipo', 'inventario')
    if tipo == 'inventario':
        silos = Silo.query.order_by(Silo.nombre_silo).all()
        filas = []
        for s in silos:
            items = InventarioSilo.query.filter_by(id_silo=s.id_silo).all()
            galones = sum((Decimal(str(it.galones or 0)) for it in items), Decimal('0'))
            cap = Decimal(str(s.capacidad_gal or 0))
            pct = float(galones / cap * 100) if cap > 0 else 0
            filas.append({
                'Silo': s.nombre_silo,
                'Capacidad (gal)': float(cap),
                'Galones actuales': float(galones),
                'Ocupación (%)': round(pct, 2),
                'Tipo producto': s.tipo_producto or '',
                'Estado': s.estado,
            })
        df = pd.DataFrame(filas)
        nombre = 'reporte_inventario_silos.xlsx'
    elif tipo == 'embarques':
        fecha_desde = _parse_date_or_none(request.args.get('fecha_desde'))
        fecha_hasta = _parse_date_or_none(request.args.get('fecha_hasta'))
        id_producto = _parse_int_or_none(request.args.get('id_producto'))
        id_cliente = _parse_int_or_none(request.args.get('id_cliente'))
        q = Embarque.query
        if fecha_desde:
            q = q.filter(Embarque.fecha_embarque >= fecha_desde)
        if fecha_hasta:
            q = q.filter(Embarque.fecha_embarque <= fecha_hasta)
        if id_producto:
            q = q.filter(Embarque.id_producto == id_producto)
        if id_cliente:
            q = q.filter(Embarque.id_cliente == id_cliente)
        embarques = q.order_by(Embarque.fecha_embarque.desc()).all()
        filas = []
        for e in embarques:
            galones = sum((Decimal(str(el.cantidad or 0)) for el in e.lotes), Decimal('0'))
            filas.append({
                'Fecha': e.fecha_embarque,
                'Cita': e.num_cita,
                'Producto': (e.producto.descripcion if e.producto else e.producto_texto) or '',
                'Cliente': (e.cliente.nombre_cliente if e.cliente else e.cliente_texto) or '',
                'Estatus': e.estatus,
                'Turno': e.turno,
                'Galones': float(galones),
            })
        df = pd.DataFrame(filas)
        nombre = 'reporte_embarques.xlsx'
    else:
        flash('Tipo de reporte no válido.', 'danger')
        return redirect(url_for('reportes'))

    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Reporte')
    output.seek(0)
    return send_file(output, download_name=nombre,
                     as_attachment=True,
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

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
    'clientes': {
        'model': Cliente,
        'nombre_visible': 'Clientes',
        'campos': [
            ('nombre_cliente', 'Nombre del cliente', 'text', True),
            ('codigo', 'Código (opcional)', 'text', False),
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

    # --- Tarjetas resumen (respetan los filtros de fecha del usuario) ---
    q_resumen = Embarque.query.filter(Embarque.estatus != 'cancelado')
    if fecha_desde:
        q_resumen = q_resumen.filter(Embarque.fecha_embarque >= fecha_desde)
    if fecha_hasta:
        q_resumen = q_resumen.filter(Embarque.fecha_embarque <= fecha_hasta)

    total_mes = q_resumen.count()
    embarques_mes = q_resumen.options(db.joinedload(Embarque.lotes)).all()
    kg_embarcados = Decimal('0')
    for emb in embarques_mes:
        if emb.producto and emb.producto.unidad_medida == 'KG':
            kg_embarcados += emb.cantidad_total

    # Tiempo medio en planta (solo embarques con tiempos completos dentro de los filtros).
    # Se lleva además un KPI desglosado por tipo de transporte, porque el proceso
    # es distinto: las pipas y los tambores no tardan lo mismo en planta.
    def _promedio_td(segundos):
        """Convierte una lista de segundos a su promedio en timedelta (None si vacía)."""
        return timedelta(seconds=sum(segundos) / len(segundos)) if segundos else None

    tiempos_tds = []
    tiempos_por_grupo = {'pipa': [], 'caja': [], 'tambor': []}
    for emb in embarques_mes:
        if emb.tiempos and emb.tiempos.tiempo_en_planta:
            seg = emb.tiempos.tiempo_en_planta.total_seconds()
            tiempos_tds.append(seg)
            grupo = TIPO_UNIDAD_GRUPO.get(emb.tipo_unidad)
            if grupo in tiempos_por_grupo:
                tiempos_por_grupo[grupo].append(seg)

    tiempo_medio_texto = _formatear_timedelta(_promedio_td(tiempos_tds)) or '0 min'

    # KPI por tipo de transporte (promedio y número de embarques considerados).
    tiempos_transporte = [
        {
            'etiqueta': etiqueta,
            'tiempo': _formatear_timedelta(_promedio_td(tiempos_por_grupo[clave])) or '-',
            'muestras': len(tiempos_por_grupo[clave]),
        }
        for clave, etiqueta in (('pipa', 'Pipas'), ('caja', 'Cajas'), ('tambor', 'Tambores'))
    ]

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
            'tiempos_transporte': tiempos_transporte,
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
        'silos': Silo.query.filter_by(estado='activo').order_by(Silo.nombre_silo).all(),
    }


def _resolver_unidad_transporte(raw_id, placa_nueva, tipo):
    """
    Resuelve la FK id_unidad para tractor / remolque:
      - Si raw_id es entero > 0: lo devuelve directo (unidad existente seleccionada).
      - Si raw_id == '__nuevo__' y viene placa_nueva no vacía:
          * busca unidad existente con esa placa (case insensitive), si existe devuelve su id.
          * si no existe: crea UnidadTransporte(tipo=tipo, placa=placa_nueva, activo=True),
            la agrega a la sesión (no hace commit, depende de la transacción exterior) y
            devuelve su id después de flush.
      - De lo contrario devuelve None.

    Devuelve: (id_unidad:int|None, mensaje_error:str|None)
    """
    if raw_id is None:
        return None, None
    raw_id_str = str(raw_id).strip()
    if raw_id_str == '' or raw_id_str.lower() == 'none':
        return None, None
    if raw_id_str == '__nuevo__':
        placa = _validar_y_normalizar_texto(placa_nueva, mayusculas=True)
        if not placa:
            return None, 'Placa para nueva unidad {} es obligatoria al elegir "Agregar nuevo".'.format(tipo)
        if len(placa) > 30:
            return None, 'La placa excede 30 caracteres.'
        existente = UnidadTransporte.query.filter(
            func.upper(UnidadTransporte.placa) == placa.upper()
        ).first()
        if existente:
            if existente.tipo != tipo:
                return None, (
                    'Ya existe una unidad con placa {} pero es tipo {}. '
                    'No se puede reutilizar como {}.'
                ).format(placa, existente.tipo, tipo)
            return existente.id_unidad, None
        nueva = UnidadTransporte(placa=placa, tipo=tipo, activo=True)
        db.session.add(nueva)
        db.session.flush()
        return nueva.id_unidad, None
    id_int = _parse_int_or_none(raw_id_str)
    if id_int:
        if not UnidadTransporte.query.filter_by(id_unidad=id_int).first():
            return None, ('La unidad seleccionada ya no existe. '
                          'Recarga la página y vuelve a seleccionarla.')
        return id_int, None
    return None, None


def _resolver_producto(raw_id, descripcion_nueva, tipo_nuevo, um_nuevo):
    """
    Resuelve id_producto:
      - entero > 0: devuelve el id.
      - '__nuevo__' con descripción: busca por descripción (case insensitive),
        si existe devuelve su id; si no, crea ProductoEmbarque con item
        auto-generado, activo=True, y flush.
    Devuelve (id_producto:int|None, error:str|None).
    """
    if raw_id is None:
        return None, None
    raw = str(raw_id).strip()
    if raw == '' or raw.lower() == 'none':
        return None, None
    if raw == '__nuevo__':
        descripcion = _validar_y_normalizar_texto(descripcion_nueva, mayusculas=False)
        if not descripcion:
            return None, 'La descripción del nuevo producto es obligatoria.'
        if len(descripcion) > 255:
            return None, 'La descripción del producto excede 255 caracteres.'
        tipo = (tipo_nuevo or 'concentrado').strip()
        if tipo not in ('concentrado', 'pulpa', 'colateral'):
            tipo = 'concentrado'
        um = (um_nuevo or 'KG').strip()
        if um not in ('KG', 'TAZ'):
            um = 'KG'
        existente = ProductoEmbarque.query.filter(
            db.func.upper(ProductoEmbarque.descripcion) == descripcion.upper()
        ).first()
        if existente:
            return existente.id_producto, None
        # Generar item único automáticamente
        import uuid
        item = 'AUTO-' + uuid.uuid4().hex[:8].upper()
        while ProductoEmbarque.query.filter_by(item=item).first():
            item = 'AUTO-' + uuid.uuid4().hex[:8].upper()
        nuevo = ProductoEmbarque(
            item=item, descripcion=descripcion, tipo=tipo,
            unidad_medida=um, activo=True)
        db.session.add(nuevo)
        db.session.flush()
        return nuevo.id_producto, None
    id_int = _parse_int_or_none(raw)
    if id_int:
        if not ProductoEmbarque.query.filter_by(id_producto=id_int).first():
            return None, ('El producto seleccionado ya no existe. '
                          'Recarga la página y vuelve a seleccionarlo.')
        return id_int, None
    return None, None


def _resolver_cliente(raw_id, nombre_nuevo):
    """
    Resuelve id_cliente:
      - entero > 0: devuelve el id.
      - '__nuevo__' con nombre: busca por nombre (case insensitive), si existe
        devuelve su id; si no, crea Cliente(nombre_cliente) y flush.
    Devuelve (id_cliente:int|None, error:str|None).
    """
    if raw_id is None:
        return None, None
    raw = str(raw_id).strip()
    if raw == '' or raw.lower() == 'none':
        return None, None
    if raw == '__nuevo__':
        nombre = _validar_y_normalizar_texto(nombre_nuevo, mayusculas=False)
        if not nombre:
            return None, 'El nombre del nuevo cliente es obligatorio.'
        if len(nombre) > 100:
            return None, 'El nombre del cliente excede 100 caracteres.'
        existente = Cliente.query.filter(
            db.func.upper(Cliente.nombre_cliente) == nombre.upper()
        ).first()
        if existente:
            return existente.id_cliente, None
        nuevo = Cliente(nombre_cliente=nombre)
        db.session.add(nuevo)
        db.session.flush()
        return nuevo.id_cliente, None
    id_int = _parse_int_or_none(raw)
    if id_int:
        if not Cliente.query.filter_by(id_cliente=id_int).first():
            return None, ('El cliente seleccionado ya no existe. '
                          'Recarga la página y vuelve a seleccionarlo.')
        return id_int, None
    return None, None


def _resolver_transportista(raw_id, nombre_nuevo):
    """
    Resuelve id_transportista:
      - entero > 0: devuelve el id.
      - '__nuevo__' con nombre: busca por nombre (case insensitive), si existe
        devuelve su id; si no, crea Transportista(nombre, activo=True) y flush.
    Devuelve (id_transportista:int|None, error:str|None).
    """
    if raw_id is None:
        return None, None
    raw = str(raw_id).strip()
    if raw == '' or raw.lower() == 'none':
        return None, None
    if raw == '__nuevo__':
        nombre = _validar_y_normalizar_texto(nombre_nuevo, mayusculas=False)
        if not nombre:
            return None, 'El nombre del nuevo transportista es obligatorio.'
        if len(nombre) > 200:
            return None, 'El nombre del transportista excede 200 caracteres.'
        existente = Transportista.query.filter(
            db.func.upper(Transportista.nombre) == nombre.upper()
        ).first()
        if existente:
            return existente.id_transportista, None
        nuevo = Transportista(nombre=nombre, activo=True)
        db.session.add(nuevo)
        db.session.flush()
        return nuevo.id_transportista, None
    id_int = _parse_int_or_none(raw)
    if id_int:
        if not Transportista.query.filter_by(id_transportista=id_int).first():
            return None, ('El transportista seleccionado ya no existe. '
                          'Recarga la página y vuelve a seleccionarlo.')
        return id_int, None
    return None, None


def _resolver_operador(raw_id, nombre_nuevo):
    """
    Resuelve id_operador igual que _resolver_transportista pero sobre Operador.
    Devuelve (id_operador:int|None, error:str|None).
    """
    if raw_id is None:
        return None, None
    raw = str(raw_id).strip()
    if raw == '' or raw.lower() == 'none':
        return None, None
    if raw == '__nuevo__':
        nombre = _validar_y_normalizar_texto(nombre_nuevo, mayusculas=False)
        if not nombre:
            return None, 'El nombre del nuevo operador es obligatorio.'
        if len(nombre) > 200:
            return None, 'El nombre del operador excede 200 caracteres.'
        existente = Operador.query.filter(
            db.func.upper(Operador.nombre) == nombre.upper()
        ).first()
        if existente:
            return existente.id_operador, None
        nuevo = Operador(nombre=nombre, activo=True)
        db.session.add(nuevo)
        db.session.flush()
        return nuevo.id_operador, None
    id_int = _parse_int_or_none(raw)
    if id_int:
        if not Operador.query.filter_by(id_operador=id_int).first():
            return None, ('El operador seleccionado ya no existe. '
                          'Recarga la página y vuelve a seleccionarlo.')
        return id_int, None
    return None, None


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


def _renumerar_posiciones_silo(id_silo):
    """Renumera 1..n las posiciones LIFO del inventario de un silo."""
    items = (InventarioSilo.query.filter_by(id_silo=id_silo)
             .order_by(InventarioSilo.posicion.asc(),
                       InventarioSilo.id_inventario.asc()).all())
    for i, it in enumerate(items, start=1):
        it.posicion = i


def _marca_salida_embarque(id_embarque):
    """Marca en observaciones que identifica los movimientos de salida de un embarque."""
    return f'Salida por embarque #{id_embarque}'


def _revertir_salida_inventario_embarque(embarque):
    """
    Devuelve al inventario los galones descontados por un embarque y elimina los
    movimientos de salida que se generaron (identificados por la marca del embarque).
    Se usa al editar o cancelar para recalcular desde cero.
    """
    if embarque.id_embarque is None:
        return
    marca = _marca_salida_embarque(embarque.id_embarque)
    movs = (Movimiento.query
            .filter(Movimiento.tipo_movimiento == 'salida')
            .filter(Movimiento.observaciones.like(f'{marca}%'))
            .all())
    if not movs:
        return
    # 1) Desvincular primero embarque_lotes (FK hacia movimientos) para poder
    #    eliminar los movimientos sin violar la restricción de integridad.
    EmbarqueLote.query.filter_by(id_embarque=embarque.id_embarque).update(
        {'id_movimiento': None}, synchronize_session=False)
    db.session.flush()
    # 2) Devolver los galones al inventario y eliminar los movimientos de salida.
    silos_afectados = set()
    for mv in movs:
        galones = Decimal(mv.galones or 0)
        if mv.id_silo is not None and mv.id_lote is not None:
            item = (InventarioSilo.query
                    .filter_by(id_silo=mv.id_silo, id_lote=mv.id_lote)
                    .order_by(InventarioSilo.posicion.asc()).first())
            if item:
                item.galones = Decimal(item.galones or 0) + galones
            else:
                # El lote se había vaciado del silo: se re-crea la fila al final.
                max_pos = (db.session.query(
                    db.func.coalesce(db.func.max(InventarioSilo.posicion), 0))
                    .filter(InventarioSilo.id_silo == mv.id_silo).scalar()) or 0
                db.session.add(InventarioSilo(
                    id_silo=mv.id_silo, id_lote=mv.id_lote,
                    posicion=int(max_pos) + 1, galones=galones))
            silos_afectados.add(mv.id_silo)
        db.session.delete(mv)
    db.session.flush()
    for id_silo in silos_afectados:
        _renumerar_posiciones_silo(id_silo)


def _aplicar_salida_inventario_embarque(embarque, lotes_info, id_usuario):
    """
    Descuenta del inventario (inventario_silos) los galones declarados por lote en el
    embarque, en orden LIFO por posición. Crea un Movimiento tipo 'salida' por cada
    silo afectado y enlaza el primero en embarque_lotes.id_movimiento.
    Lanza ValueError si algún lote no tiene inventario suficiente.
    """
    marca = _marca_salida_embarque(embarque.id_embarque)
    silos_afectados = set()
    for id_lote, cantidad, lote_obj in lotes_info:
        if cantidad is None:
            continue
        cantidad = Decimal(cantidad)
        if cantidad <= 0:
            continue
        codigo = lote_obj.codigo_lote if lote_obj else id_lote
        items = (InventarioSilo.query.filter_by(id_lote=id_lote)
                 .order_by(InventarioSilo.posicion.asc(),
                           InventarioSilo.id_inventario.asc()).all())
        disponible = sum((Decimal(i.galones or 0) for i in items), Decimal('0'))
        if cantidad > disponible:
            raise ValueError(
                f'Inventario insuficiente del lote {codigo}: '
                f'disponible {disponible} gal, solicitado {cantidad} gal.')
        restante = cantidad
        primer_mov = None
        for item in items:
            if restante <= 0:
                break
            en_lote = Decimal(item.galones or 0)
            sacar = min(en_lote, restante)
            if sacar <= 0:
                continue
            mv = Movimiento(
                tipo_movimiento='salida',
                id_silo=item.id_silo,
                id_lote=id_lote,
                galones=sacar,
                id_usuario=id_usuario,
                observaciones=(f'{marca} (LIFO Lote {codigo} '
                               f'- Pos {item.posicion})')
            )
            db.session.add(mv)
            db.session.flush()
            if primer_mov is None:
                primer_mov = mv
            if sacar >= en_lote:
                db.session.delete(item)
            else:
                item.galones = en_lote - sacar
            silos_afectados.add(item.id_silo)
            restante -= sacar
        el = EmbarqueLote.query.filter_by(
            id_embarque=embarque.id_embarque, id_lote=id_lote).first()
        if el is not None and primer_mov is not None:
            el.id_movimiento = primer_mov.id_movimiento
    db.session.flush()
    for id_silo in silos_afectados:
        _renumerar_posiciones_silo(id_silo)


def _calcular_promedio_ponderado(lotes_info, atributo):
    """
    Promedio ponderado por galones de un atributo (°Brix, relación o pulpa) de
    los lotes de origen. Devuelve None si no hay datos suficientes.
    """
    total = Decimal('0')
    acumulado = Decimal('0')
    for _id, cantidad, lote_obj in lotes_info:
        if lote_obj is None or cantidad is None:
            continue
        valor = getattr(lote_obj, atributo, None)
        if valor is None:
            continue
        c = Decimal(str(cantidad))
        total += c
        acumulado += c * Decimal(str(valor))
    if total > 0:
        return (acumulado / total).quantize(Decimal('0.01'))
    return None


def _guardar_lote_mezcla(embarque, request_form, lotes_info):
    """
    Crea/actualiza el lote de mezcla (asignado por INVOCA) de un embarque de pipa
    y sus componentes (lotes de origen con sus galones).

    Reglas:
      - El código del lote de mezcla lo asigna INVOCA; el sistema solo lo captura
        y valida el formato 005-AAAAMMDD-NNNNNN.
      - No puede existir ya como lote de producto con inventario.
      - °Brix, relación y pulpa se toman del formulario si se capturan; si no,
        se calculan ponderados por galones de los lotes de origen.
      - Se inserta una fila en lote_componentes por cada lote de origen; la suma
        de componentes debe cuadrar con lo cargado.

    Devuelve (lote_mezcla, error). error es None si todo está correcto.
    """
    # Al editar, se limpian los componentes previos para recalcularlos.
    if embarque.id_embarque is not None:
        LoteComponente.query.filter_by(id_embarque=embarque.id_embarque).delete(
            synchronize_session=False)
        db.session.flush()

    codigo = (request_form.get('lote_mezcla') or '').strip()
    if not codigo:
        return None, None
    if not REGEX_CODIGO_LOTE.match(codigo):
        return None, 'Formato del lote de mezcla incorrecto. Usa: 005-20251210-044497'

    lote = Lote.query.filter_by(codigo_lote=codigo).first()
    if lote is not None and not lote.es_mezcla:
        # No se puede reutilizar un lote de producto que ya tiene inventario.
        if InventarioSilo.query.filter_by(id_lote=lote.id_lote).first():
            return None, f'El lote {codigo} ya existe como lote de producto con inventario.'
    if lote is None:
        lote = Lote(codigo_lote=codigo)
        db.session.add(lote)
        db.session.flush()

    # °Brix, relación y pulpa: del formulario o ponderados por galones.
    brix = _parse_decimal_or_none(request_form.get('lote_mezcla_brix'))
    if brix is None:
        brix = _calcular_promedio_ponderado(lotes_info, 'brix')
    relacion = _parse_decimal_or_none(request_form.get('lote_mezcla_relacion'))
    if relacion is None:
        relacion = _calcular_promedio_ponderado(lotes_info, 'relacion')
    pulpa = _parse_decimal_or_none(request_form.get('lote_mezcla_pulpa'))
    if pulpa is None:
        pulpa = _calcular_promedio_ponderado(lotes_info, 'pulpa')

    lote.es_mezcla = True
    lote.asignado_por = ASIGNADO_POR_MEZCLA
    lote.brix = brix
    lote.relacion = relacion
    lote.pulpa = pulpa
    if lote.fecha_lote is None:
        lote.fecha_lote = embarque.fecha_embarque

    # Una fila por lote de origen con sus galones.
    total_componentes = Decimal('0')
    total_cargado = Decimal('0')
    for id_lote, cantidad, _lote_obj in lotes_info:
        if cantidad is None:
            continue
        c = Decimal(str(cantidad))
        if c <= 0:
            continue
        total_cargado += c
        db.session.add(LoteComponente(
            id_lote_mezcla=lote.id_lote,
            id_lote_origen=id_lote,
            id_embarque=embarque.id_embarque,
            galones=c,
        ))
        total_componentes += c

    if total_componentes <= 0:
        return None, 'El lote de mezcla requiere al menos un lote de origen con galones.'
    if total_componentes != total_cargado:
        return None, (
            f'La suma de los componentes ({float(total_componentes):.2f} gal) '
            f'no cuadra con lo cargado ({float(total_cargado):.2f} gal).')
    db.session.flush()
    return lote, None


def _eliminar_lote_mezcla(embarque):
    """
    Elimina los componentes y el lote de mezcla de un embarque (al cancelar).
    El lote de mezcla solo se borra del catálogo si ya no lo usa otro embarque.
    """
    if embarque.id_embarque is None:
        return
    componentes = LoteComponente.query.filter_by(id_embarque=embarque.id_embarque).all()
    if not componentes:
        return
    ids_mezcla = {c.id_lote_mezcla for c in componentes}
    for c in componentes:
        db.session.delete(c)
    db.session.flush()
    for id_mezcla in ids_mezcla:
        # Si el lote de mezcla ya no tiene componentes, se elimina del catálogo.
        if not LoteComponente.query.filter_by(id_lote_mezcla=id_mezcla).first():
            lote = Lote.query.get(id_mezcla)
            if lote is not None and lote.es_mezcla:
                db.session.delete(lote)


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

        # 2a) Resolver producto y cliente (soporta "Agregar nuevo")
        mensajes_unidad = []

        id_producto, err_p = _resolver_producto(
            request_form.get('id_producto'),
            request_form.get('nuevo_producto_descripcion'),
            request_form.get('nuevo_producto_tipo'),
            request_form.get('nuevo_producto_um'))
        if err_p:
            mensajes_unidad.append(err_p)

        id_cliente, err_c = _resolver_cliente(
            request_form.get('id_cliente'),
            request_form.get('nuevo_cliente_nombre'))
        if err_c:
            mensajes_unidad.append(err_c)

        embarque.id_producto = id_producto
        embarque.id_cliente = id_cliente
        # Limpiar campos de texto libre (ya no se usan; se crean catálogos)
        embarque.producto_texto = None
        embarque.cliente_texto = None

        tipo_unidad = (request_form.get('tipo_unidad') or '').strip()
        if tipo_unidad in TIPO_UNIDAD_GRUPO:
            embarque.tipo_unidad = tipo_unidad

        # Silo de origen del embarque (un solo silo por embarque).
        embarque.id_silo = _parse_int_or_none(request_form.get('id_silo'))

        # 2b) Resolver transportista / operador (soporta "Agregar nuevo")
        #     y tractor / remolque. Si cualquiera devuelve error, abortar.

        id_transportista, err_tr = _resolver_transportista(
            request_form.get('id_transportista'),
            request_form.get('nuevo_transportista_nombre'))
        if err_tr:
            mensajes_unidad.append(err_tr)

        id_operador, err_op = _resolver_operador(
            request_form.get('id_operador'),
            request_form.get('nuevo_operador_nombre'))
        if err_op:
            mensajes_unidad.append(err_op)

        id_tractor, err_t = _resolver_unidad_transporte(
            request_form.get('id_tractor'),
            request_form.get('nuevo_tractor_placa'),
            'tractor')
        if err_t:
            mensajes_unidad.append(err_t)

        id_remolque, err_r = _resolver_unidad_transporte(
            request_form.get('id_remolque'),
            request_form.get('nuevo_remolque_placa'),
            'remolque')
        if err_r:
            mensajes_unidad.append(err_r)

        if mensajes_unidad:
            db.session.rollback()
            for m in mensajes_unidad:
                flash(m, 'warning')
            return False, mensajes_unidad

        embarque.id_transportista = id_transportista
        embarque.id_operador = id_operador
        embarque.id_tractor = id_tractor
        embarque.id_remolque = id_remolque

        embarque.turno = datos['turno']
        if not 1 <= (embarque.turno or 0) <= 3:
            embarque.turno = datos['turno'] or 1
        temp_c = _parse_decimal_or_none(request_form.get('temperatura_c'))
        embarque.temperatura_c = temp_c
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

        # 5b) Edición: revertir los descuentos de inventario previos del embarque
        #     para recalcularlos desde cero con la lista de lotes actual.
        if id_embarque_actual:
            _revertir_salida_inventario_embarque(embarque)
            db.session.flush()

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
        db.session.flush()

        # 8b) Descontar del inventario los galones declarados por lote
        #     (crea movimientos de salida y enlaza embarque_lotes.id_movimiento).
        if embarque.estatus != 'cancelado':
            try:
                _aplicar_salida_inventario_embarque(
                    embarque, lotes_info, current_user.id_usuario)
            except ValueError as ve:
                db.session.rollback()
                flash(str(ve), 'danger')
                return False, [str(ve)]

            # 8c) Lote de mezcla (solo pipas): el código lo asigna INVOCA. Se
            #     captura y se generan sus componentes desde los lotes de origen.
            if embarque.es_pipa:
                _lote_mezcla, err_mezcla = _guardar_lote_mezcla(
                    embarque, request_form, lotes_info)
                if err_mezcla:
                    db.session.rollback()
                    flash(err_mezcla, 'danger')
                    return False, [err_mezcla]

        # 8a) Pesos (para cuadre de galonaje)
        bruto = _parse_decimal_or_none(request_form.get('peso_bruto_kg'))
        tara = _parse_decimal_or_none(request_form.get('tara_kg'))
        if bruto is not None or tara is not None:
            pesos = embarque.pesos or EmbarquePeso()
            pesos.peso_bruto_kg = bruto
            pesos.tara_kg = tara
            pesos.recalcular_neto()
            pesos.actualizado_por = current_user.id_usuario
            if not embarque.pesos:
                embarque.pesos = pesos
        elif embarque.pesos:
            # Si se borraron los pesos, eliminar el registro
            db.session.delete(embarque.pesos)

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
        if emb.estatus != 'cancelado':
            # Devolver al inventario los galones que este embarque había descontado.
            _revertir_salida_inventario_embarque(emb)
            # Eliminar el lote de mezcla (INVOCA) y sus componentes.
            _eliminar_lote_mezcla(emb)
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
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    def _fmt_fecha(valor):
        return valor.strftime('%d/%m/%Y') if valor else ''

    def _fmt_fecha_hora(valor):
        return valor.strftime('%d/%m/%Y %H:%M') if valor else ''

    def _mes_es(valor):
        if not valor:
            return ''
        meses = [
            'ENERO', 'FEBRERO', 'MARZO', 'ABRIL', 'MAYO', 'JUNIO',
            'JULIO', 'AGOSTO', 'SEPTIEMBRE', 'OCTUBRE', 'NOVIEMBRE', 'DICIEMBRE'
        ]
        return meses[valor.month - 1]

    def _txt_decimal(valor, decimales=2):
        if valor is None or valor == '':
            return ''
        return f'{float(valor):,.{decimales}f}'

    def _estatus_label(valor):
        labels = {
            'programado': 'PROGRAMADO',
            'en_planta': 'EN PLANTA',
            'cargado': 'CARGADO',
            'cancelado': 'CANCELADO',
        }
        return labels.get(valor, (valor or '').upper())

    def _sellos_por_tipo(emb, tipo):
        nums = [s.numero for s in (emb.sellos or []) if s.tipo == tipo and s.numero]
        return ', '.join(nums)

    def _promedio_lotes(emb, atributo):
        total = Decimal('0')
        acumulado = Decimal('0')
        for el in emb.lotes:
            if not el.lote or getattr(el.lote, atributo, None) is None:
                continue
            cantidad = Decimal(str(el.cantidad or 0))
            valor = Decimal(str(getattr(el.lote, atributo)))
            total += cantidad
            acumulado += cantidad * valor
        if total > 0:
            return acumulado / total
        return None

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
        db.joinedload(Embarque.detalle).joinedload(EmbarqueDetalle.lavadero),
        db.joinedload(Embarque.pesos),
        db.joinedload(Embarque.capturista),
        db.joinedload(Embarque.facilitador),
        db.joinedload(Embarque.sellos),
    )
    embarques = q.order_by(Embarque.fecha_embarque.desc()).all()

    filas = []
    tu_labels = {
        'pipa_jumbo': 'PIPA JUMBO',
        'pipa_chica': 'PIPA CHICA',
        'isotanque': 'ISOTANQUE',
        'flexitanque': 'FLEXITANQUE',
        'caja_refrigerada': 'CAJA REFRIGERADA',
        'caja_seca': 'CAJA SECA',
        'trailer': 'TRAILER',
        'tambores': 'TAMBORES',
    }
    columnas = [
        'Fecha de Embarque',
        'Semana',
        'Mes',
        'Estatus',
        'Fecha de Cita',
        'Hora de Cita',
        'Numero de Cita',
        'Numero de Orden (OV/OT)',
        'Item',
        'Descripcion',
        'Numero de ticket',
        'Numero de Packing',
        'Fecha y hora Registro llegada planta',
        'Fecha y hora de entrada a planta',
        'Pesado Inicial de la Unidad',
        'Pesaje de Salida',
        'Fecha y hora de documentacion',
        'Fecha y hora de salida de Planta',
        'Lote',
        'BRIX',
        'REL.',
        'Libras Solidos',
        'Cantidad Enviada "Gls"',
        'Cliente/Destino',
        'Tipo de producto',
        'Temperatura carga',
        'Variedad',
        'CANTIDAD EMBARCADA',
        'UNIDAD DE MEDIDA',
        'Numero Economico /Placa Tractor (CAMION)',
        'Numero Economico/Placa Caja/Tanque/Contenedor,Pipa (REMOLQUE)',
        'Tipo de Unidad',
        'Linea Transportista',
        'Operador',
        'Sellos de lavado',
        'Lavadero',
        'Sello Valvula (salida)',
        'Sellos Escotilla (salida)',
        'Sellos puerta trasera (salida)',
        'Turno',
        'Capturista',
        'Facilitador',
    ]
    for emb in embarques:
        brix_prom = _promedio_lotes(emb, 'brix')
        rel_prom = _promedio_lotes(emb, 'relacion')
        peso_neto = Decimal(str(emb.pesos.peso_neto_kg)) if emb.pesos and emb.pesos.peso_neto_kg is not None else None
        libras_solidos = None
        if peso_neto is not None and brix_prom is not None:
            libras_solidos = peso_neto * brix_prom / Decimal('100')

        cliente_txt = emb.cliente_texto or ''
        if emb.cliente:
            cliente_txt = f'{emb.cliente.codigo} - {emb.cliente.nombre_cliente}' if emb.cliente.codigo else emb.cliente.nombre_cliente

        lotes_codigos = ', '.join(
            el.lote.codigo_lote for el in emb.lotes if el.lote and el.lote.codigo_lote
        )
        variedad = ''
        if emb.producto:
            variedad = emb.producto.variedad or emb.producto.descripcion or ''

        filas.append({
            'Fecha de Embarque': _fmt_fecha(emb.fecha_embarque),
            'Semana': emb.fecha_embarque.isocalendar()[1] if emb.fecha_embarque else '',
            'Mes': _mes_es(emb.fecha_embarque),
            'Estatus': _estatus_label(emb.estatus),
            'Fecha de Cita': _fmt_fecha(emb.fecha_embarque),
            'Hora de Cita': '',
            'Numero de Cita': emb.num_cita or '',
            'Numero de Orden (OV/OT)': emb.num_orden or '',
            'Item': emb.producto.item if emb.producto and emb.producto.item else '',
            'Descripcion': emb.producto.descripcion if emb.producto and emb.producto.descripcion else (emb.producto_texto or ''),
            'Numero de ticket': emb.ticket or '',
            'Numero de Packing': emb.packing or '',
            'Fecha y hora Registro llegada planta': _fmt_fecha_hora(emb.tiempos.llegada if emb.tiempos else None),
            'Fecha y hora de entrada a planta': _fmt_fecha_hora(emb.tiempos.entrada if emb.tiempos else None),
            'Pesado Inicial de la Unidad': _fmt_fecha_hora(emb.tiempos.pesado_inicial if emb.tiempos else None),
            'Pesaje de Salida': _fmt_fecha_hora(emb.tiempos.pesaje_salida if emb.tiempos else None),
            'Fecha y hora de documentacion': _fmt_fecha_hora(emb.tiempos.documentacion if emb.tiempos else None),
            'Fecha y hora de salida de Planta': _fmt_fecha_hora(emb.tiempos.salida if emb.tiempos else None),
            'Lote': lotes_codigos,
            'BRIX': _txt_decimal(brix_prom),
            'REL.': _txt_decimal(rel_prom),
            'Libras Solidos': _txt_decimal(libras_solidos),
            'Cantidad Enviada "Gls"': _txt_decimal(emb.cantidad_total),
            'Cliente/Destino': cliente_txt,
            'Tipo de producto': emb.producto.tipo.upper() if emb.producto and emb.producto.tipo else '',
            'Temperatura carga': f'{float(emb.temperatura_c):,.1f}°C' if emb.temperatura_c is not None else '',
            'Variedad': variedad,
            'CANTIDAD EMBARCADA': _txt_decimal(peso_neto),
            'UNIDAD DE MEDIDA': emb.producto.unidad_medida if emb.producto and emb.producto.unidad_medida else '',
            'Numero Economico /Placa Tractor (CAMION)': emb.tractor.placa if emb.tractor else '',
            'Numero Economico/Placa Caja/Tanque/Contenedor,Pipa (REMOLQUE)': emb.remolque.placa if emb.remolque else '',
            'Tipo de Unidad': tu_labels.get(emb.tipo_unidad, (emb.tipo_unidad or '').upper()),
            'Linea Transportista': emb.transportista.nombre if emb.transportista else '',
            'Operador': emb.operador.nombre if emb.operador else '',
            'Sellos de lavado': _sellos_por_tipo(emb, 'lavado'),
            'Lavadero': emb.detalle.lavadero.nombre if emb.detalle and emb.detalle.lavadero else '',
            'Sello Valvula (salida)': _sellos_por_tipo(emb, 'valvula'),
            'Sellos Escotilla (salida)': _sellos_por_tipo(emb, 'escotilla'),
            'Sellos puerta trasera (salida)': _sellos_por_tipo(emb, 'puerta_trasera'),
            'Turno': emb.turno or '',
            'Capturista': emb.capturista.nombre if emb.capturista else '',
            'Facilitador': emb.facilitador.nombre if emb.facilitador else '',
        })

    df = pd.DataFrame(filas, columns=columnas)
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Embarques', startrow=1)
        ws = writer.sheets['Embarques']

        grupos = [
            ('Datos de plan', 1, 12, '1F4E78'),
            ('Tiempos de carga', 13, 18, '7F6000'),
            ('Datos de la carga', 19, 29, '548235'),
            ('Datos de la unidad', 30, 34, '1F4E78'),
            ('Carga de Pipa/Isotanque / Caja', 35, 39, '7F6000'),
            ('Desviacion', 40, 42, '548235'),
        ]

        fill_header = PatternFill(fill_type='solid', fgColor='0B6B3A')
        fill_subheader = PatternFill(fill_type='solid', fgColor='0D2F6E')
        font_white = Font(color='FFFFFF', bold=True)
        center = Alignment(horizontal='center', vertical='center', wrap_text=True)

        for titulo, col_ini, col_fin, color in grupos:
            ws.merge_cells(start_row=1, start_column=col_ini, end_row=1, end_column=col_fin)
            celda = ws.cell(row=1, column=col_ini)
            celda.value = titulo
            celda.fill = PatternFill(fill_type='solid', fgColor=color)
            celda.font = font_white
            celda.alignment = center

        for col_idx in range(1, len(columnas) + 1):
            celda = ws.cell(row=2, column=col_idx)
            celda.fill = fill_subheader
            celda.font = font_white
            celda.alignment = center

        ws.freeze_panes = 'A3'
        ws.auto_filter.ref = f'A2:{get_column_letter(len(columnas))}{ws.max_row}'
        ws.row_dimensions[1].height = 22
        ws.row_dimensions[2].height = 34

        for fila in ws.iter_rows(min_row=3, max_row=ws.max_row):
            for celda in fila:
                celda.alignment = Alignment(vertical='top', wrap_text=True)

        for idx, nombre_col in enumerate(columnas, start=1):
            largo = len(nombre_col)
            for celda in ws[get_column_letter(idx)]:
                if celda.value is not None:
                    largo = max(largo, len(str(celda.value)))
            ws.column_dimensions[get_column_letter(idx)].width = min(max(largo + 2, 12), 28)
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
    Pantalla de cuadre de galonaje.
    Compara por embarque: galones por peso, galones declarados por lote
    y galones de inventario (movimientos). Filtros por fecha, producto, cliente.
    """
    # --- Filtros ---
    fecha_desde = _parse_date_or_none(request.args.get('fecha_desde'))
    fecha_hasta = _parse_date_or_none(request.args.get('fecha_hasta'))
    id_producto = _parse_int_or_none(request.args.get('id_producto'))
    id_cliente = _parse_int_or_none(request.args.get('id_cliente'))
    estado_filtro = (request.args.get('estado') or '').strip() or None

    # Umbral de tolerancia
    tolerancia_pct = _get_parametro_float('cuadre_tolerancia_pct', 1.0)

    # --- Query ---
    q = Embarque.query.filter(Embarque.estatus != 'cancelado')
    if fecha_desde:
        q = q.filter(Embarque.fecha_embarque >= fecha_desde)
    if fecha_hasta:
        q = q.filter(Embarque.fecha_embarque <= fecha_hasta)
    if id_producto:
        q = q.filter(Embarque.id_producto == id_producto)
    if id_cliente:
        q = q.filter(Embarque.id_cliente == id_cliente)

    q = q.options(
        db.joinedload(Embarque.lotes).joinedload(EmbarqueLote.lote),
        db.joinedload(Embarque.lotes).joinedload(EmbarqueLote.movimiento),
        db.joinedload(Embarque.producto),
        db.joinedload(Embarque.cliente),
        db.joinedload(Embarque.pesos),
    ).order_by(Embarque.fecha_embarque.desc(), Embarque.id_embarque.desc())

    embarques = q.all()

    # --- Calcular cuadre por embarque ---
    resultados = []
    for emb in embarques:
        r = _calcular_cuadre_embarque(emb, tolerancia_pct)
        if estado_filtro and r['estado'] != estado_filtro:
            continue
        resultados.append(r)

    # --- Resumen ---
    total = len(resultados)
    por_estado = {}
    for r in resultados:
        por_estado[r['estado']] = por_estado.get(r['estado'], 0) + 1

    # --- Catálogos para filtros ---
    productos = ProductoEmbarque.query.filter_by(activo=True).order_by(ProductoEmbarque.descripcion).all()
    clientes = Cliente.query.order_by(Cliente.nombre_cliente).all()

    return render_template(
        'embarques/cuadre.html',
        resultados=resultados,
        tolerancia_pct=tolerancia_pct,
        filtros={
            'fecha_desde': fecha_desde,
            'fecha_hasta': fecha_hasta,
            'id_producto': id_producto,
            'id_cliente': id_cliente,
            'estado': estado_filtro,
        },
        productos=productos,
        clientes=clientes,
        resumen={
            'total': total,
            'cuadra': por_estado.get('cuadra', 0),
            'dentro_tolerancia': por_estado.get('dentro_tolerancia', 0),
            'descuadre': por_estado.get('descuadre', 0),
            'sin_datos': por_estado.get('sin_datos', 0),
        },
    )


@app.route('/embarques/cuadre/exportar')
@login_required
def exportar_cuadre():
    """
    Exporta a Excel el cuadre de galonaje con los mismos filtros de la pantalla.
    """
    fecha_desde = _parse_date_or_none(request.args.get('fecha_desde'))
    fecha_hasta = _parse_date_or_none(request.args.get('fecha_hasta'))
    id_producto = _parse_int_or_none(request.args.get('id_producto'))
    id_cliente = _parse_int_or_none(request.args.get('id_cliente'))
    estado_filtro = (request.args.get('estado') or '').strip() or None
    tolerancia_pct = _get_parametro_float('cuadre_tolerancia_pct', 1.0)

    q = Embarque.query.filter(Embarque.estatus != 'cancelado')
    if fecha_desde:
        q = q.filter(Embarque.fecha_embarque >= fecha_desde)
    if fecha_hasta:
        q = q.filter(Embarque.fecha_embarque <= fecha_hasta)
    if id_producto:
        q = q.filter(Embarque.id_producto == id_producto)
    if id_cliente:
        q = q.filter(Embarque.id_cliente == id_cliente)

    q = q.options(
        db.joinedload(Embarque.lotes).joinedload(EmbarqueLote.lote),
        db.joinedload(Embarque.lotes).joinedload(EmbarqueLote.movimiento),
        db.joinedload(Embarque.producto),
        db.joinedload(Embarque.cliente),
        db.joinedload(Embarque.pesos),
    ).order_by(Embarque.fecha_embarque.desc())

    resultados = []
    for emb in q.all():
        r = _calcular_cuadre_embarque(emb, tolerancia_pct)
        if estado_filtro and r['estado'] != estado_filtro:
            continue
        resultados.append(r)

    estado_labels = {
        'cuadra': 'Cuadra',
        'dentro_tolerancia': 'Dentro de tolerancia',
        'descuadre': 'Descuadre',
        'sin_datos': 'Sin datos',
    }

    filas = []
    for r in resultados:
        emb = r['embarque']
        prod_desc = emb.producto.descripcion if emb.producto else ''
        cliente_nombre = emb.cliente.nombre_cliente if emb.cliente else ''
        filas.append({
            'Fecha': emb.fecha_embarque.strftime('%d/%m/%Y') if emb.fecha_embarque else '',
            'Cita': emb.num_cita or '',
            'Producto': prod_desc,
            'Cliente': cliente_nombre,
            'Brix promedio': round(r['brix_promedio'], 2) if r['brix_promedio'] is not None else '',
            'Densidad (kg/L)': round(r['densidad'], 5) if r['densidad'] is not None else '',
            'Peso neto (kg)': round(r['peso_neto'], 2) if r['peso_neto'] is not None else '',
            'Galones por peso': round(r['galones_peso'], 2) if r['galones_peso'] is not None else '',
            'Galones por lote': round(r['galones_lotes'], 2),
            'Galones inventario': round(r['galones_inventario'], 2) if r['galones_inventario'] is not None else '',
            'Dif. peso vs lote (gal)': round(r['dif_peso_lotes_abs'], 2) if r['dif_peso_lotes_abs'] is not None else '',
            'Dif. peso vs lote (%)': round(r['dif_peso_lotes'], 2) if r['dif_peso_lotes'] is not None else '',
            'Dif. inventario vs lote (gal)': round(r['dif_lotes_abs'], 2) if r['dif_lotes_abs'] is not None else '',
            'Dif. inventario vs lote (%)': round(r['dif_inv_lotes'], 2) if r['dif_inv_lotes'] is not None else '',
            'Estado': estado_labels.get(r['estado'], r['estado']),
        })

    df = pd.DataFrame(filas)
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Cuadre')
    output.seek(0)
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=f'cuadre_galonaje_{datetime.now().strftime("%Y%m%d_%H%M")}.xlsx',
    )


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
    # Determinar el nombre del campo clave primaria para el template.
    pk_cols = list(Model.__mapper__.primary_key)
    pk_name = pk_cols[0].name if pk_cols else 'id'

    # Ordenar por nombre / descripción / placa / item si existen; de lo contrario
    # por la clave primaria.
    if hasattr(Model, 'nombre'):
        items = Model.query.order_by(Model.nombre).all()
    elif hasattr(Model, 'nombre_cliente'):
        items = Model.query.order_by(Model.nombre_cliente).all()
    elif hasattr(Model, 'descripcion'):
        items = Model.query.order_by(Model.descripcion).all()
    elif hasattr(Model, 'placa'):
        items = Model.query.order_by(Model.placa).all()
    elif hasattr(Model, 'item'):
        items = Model.query.order_by(Model.item).all()
    else:
        items = Model.query.order_by(getattr(Model, pk_name)).all()

    fk_opciones = {}
    if nombre == 'operadores':
        fk_opciones['id_transportista'] = Transportista.query.filter_by(activo=True).order_by(Transportista.nombre).all()

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


# =====================================================================
# ===== MÓDULO EMPAQUE - RUTAS ========================================
# =====================================================================
# 4 sub-pestañas:
#   A. Resumen      (lectura: todos los roles)
#   B. Inventario   (lectura: todos los roles)
#   C. Movimiento   (escritura: capturista / admin)
#   D. Catálogo     (admin: artículos, catálogos, kits, carga masiva,
#                    conciliación, ajustes, exportación)
# =====================================================================


def _empaque_render_base(tab_activa, template_hijo, **kwargs):
    """
    Helper interno. Renderiza la plantilla de Empaque inyectando
    cuál de las 4 sub-pestañas está activa y los catálogos básicos.

    Parámetros:
        tab_activa: 'resumen' | 'inventario' | 'movimiento' | 'catalogo'
        template_hijo: ruta del template específico a renderizar.
        **kwargs: variables adicionales para el template.

    Devuelve:
        Response de render_template con la página completa.
    """
    return render_template(
        template_hijo,
        _empaque_tab_activa=tab_activa,
        _empaque_hay_articulos=EmpaqueArticulo.query.count() > 0,
        _empaque_hay_categorias=EmpaqueCategoria.query.filter_by(activo=True).count() > 0,
        _empaque_hay_areas=EmpaqueArea.query.filter_by(activo=True).count() > 0,
        _empaque_hay_proveedores=EmpaqueProveedor.query.filter_by(activo=True).count() > 0,
        **kwargs
    )


# ---------------------------------------------------------------------
# Sub-pestaña A: Resumen
# ---------------------------------------------------------------------
@app.route('/embarques/empaque', methods=['GET'])
@login_required
def empaque_resumen():
    """
    Vista principal del módulo Material de Empaque.
    Muestra KPIs, tarjetas de atención y gráficas.
    Acceso: todos los roles (consulta inclusa).
    """
    hoy = date.today()
    mes_inicio = date(hoy.year, hoy.month, 1)

    articulos_todos = EmpaqueArticulo.query.all()
    articulos_activos = [a for a in articulos_todos if a.activo]

    stock_map, _dyn_map, _dif_map = {}, {}, {}
    if articulos_todos:
        cods = [a.codigo for a in articulos_todos]
        stock_map = _empaque_calcular_stock_batch(cods)

    # KPIs y atención
    kpis = {
        'articulos_activos': len(articulos_activos),
        'negativos_sin_stock': 0,
        'bajo_o_diferencia': 0,
        'sin_dato_dynamics': 0,
        'movs_mes': 0,
    }
    atencion_puntajes = []
    for a in articulos_activos:
        stock = stock_map.get(a.codigo, 0)
        dyn = a.fisico_dynamics
        dif = (stock - dyn) if dyn is not None else None
        minimo = a.stock_minimo if a.stock_minimo is not None else 0
        clave, etiq, color = _empaque_estado_desde_valores(stock, dyn, minimo)
        if clave in {'neg_dynamics', 'sin_stock'}:
            kpis['negativos_sin_stock'] += 1
            atencion_puntajes.append((0, a.codigo, clave, etiq, color, stock, dyn, dif, minimo))
        elif clave in {'bajo_min', 'con_diferencia'}:
            kpis['bajo_o_diferencia'] += 1
            atencion_puntajes.append((1, a.codigo, clave, etiq, color, stock, dyn, dif, minimo))
        elif clave == 'sin_dynamics':
            kpis['sin_dato_dynamics'] += 1
            atencion_puntajes.append((2, a.codigo, clave, etiq, color, stock, dyn, dif, minimo))
    atencion_puntajes.sort(key=lambda r: (r[0], r[1]))
    requieren_atencion = []
    for _prio, cod, clave, etiq, color, stock, dyn, dif, minimo in atencion_puntajes[:12]:
        art = next((a for a in articulos_activos if a.codigo == cod), None)
        if not art:
            continue
        requieren_atencion.append({
            'codigo': cod,
            'nombre': art.nombre,
            'um': art.um,
            'categoria': art.categoria.nombre if art.categoria else None,
            'estado_clave': clave,
            'estado_etiqueta': etiq,
            'estado_color': color,
            'stock': float(stock),
            'dynamics': (float(dyn) if dyn is not None else None),
            'diferencia': (float(dif) if dif is not None else None),
            'minimo': float(minimo) if minimo else None,
        })

    # Movimientos del mes (conteo simple)
    from sqlalchemy import func as sqla_func
    cnt_e = db.session.query(sqla_func.count(EmpaqueEntrada.id_entrada)).filter(EmpaqueEntrada.fecha >= mes_inicio).scalar() or 0
    cnt_s = db.session.query(sqla_func.count(EmpaqueSalida.id_salida)).filter(EmpaqueSalida.fecha >= mes_inicio).scalar() or 0
    cnt_a = db.session.query(sqla_func.count(EmpaqueAjuste.id_ajuste)).filter(EmpaqueAjuste.fecha >= mes_inicio).scalar() or 0
    kpis['movs_mes'] = cnt_e + cnt_s + cnt_a

    # Salidas x mes (últimos 6 meses)
    salidas_mes = []
    for i in range(5, -1, -1):
        if hoy.month - i <= 0:
            y = hoy.year - 1
            m = hoy.month - i + 12
        else:
            y = hoy.year
            m = hoy.month - i
        ini = date(y, m, 1)
        if m == 12:
            fin_m = date(y + 1, 1, 1)
        else:
            fin_m = date(y, m + 1, 1)
        total = db.session.query(sqla_func.coalesce(sqla_func.sum(EmpaqueSalida.cantidad), 0)) \
            .filter(EmpaqueSalida.fecha >= ini, EmpaqueSalida.fecha < fin_m).scalar() or 0
        salidas_mes.append({'mes': ini.strftime('%b %Y'), 'cantidad': float(total)})

    # Salidas x área (mes actual)
    salidas_area = []
    for area in EmpaqueArea.query.filter_by(activo=True).order_by(EmpaqueArea.nombre).all():
        total = db.session.query(sqla_func.coalesce(sqla_func.sum(EmpaqueSalida.cantidad), 0)) \
            .filter(EmpaqueSalida.id_area == area.id_area, EmpaqueSalida.fecha >= mes_inicio).scalar() or 0
        if total:
            salidas_area.append({'area': area.nombre, 'cantidad': float(total)})
    salidas_area.sort(key=lambda r: r['cantidad'], reverse=True)

    # Entradas recientes (últimas 6)
    entradas_recientes = []
    for e in EmpaqueEntrada.query.order_by(EmpaqueEntrada.fecha.desc(), EmpaqueEntrada.id_entrada.desc()).limit(6).all():
        entradas_recientes.append({
            'fecha': e.fecha.isoformat() if e.fecha else '',
            'articulo': e.articulo.nombre if e.articulo else e.codigo,
            'um': e.articulo.um if e.articulo else 'Pz',
            'cantidad': float(e.cantidad),
            'proveedor': e.proveedor.nombre if e.proveedor else None,
        })

    # Salidas x lote de pulpa (mes actual, top 5)
    lotes_pulpa = []
    area_pulpa = next((a for a in EmpaqueArea.query.filter_by(activo=True).all() if (a.nombre or '').strip().lower() == 'pulpa'), None)
    if area_pulpa:
        rows = db.session.query(
            EmpaqueSalida.id_lote, sqla_func.coalesce(sqla_func.sum(EmpaqueSalida.cantidad), 0)
        ).filter(EmpaqueSalida.id_area == area_pulpa.id_area, EmpaqueSalida.fecha >= mes_inicio, EmpaqueSalida.id_lote.isnot(None)) \
         .group_by(EmpaqueSalida.id_lote).order_by(sqla_func.sum(EmpaqueSalida.cantidad).desc()).limit(5).all()
        for id_lote, total in rows:
            lote_obj = Lote.query.get(id_lote)
            if lote_obj:
                lotes_pulpa.append({
                    'lote': lote_obj.codigo_lote,
                    'producto': lote_obj.producto,
                    'cantidad': float(total),
                })

    return _empaque_render_base(
        'resumen',
        'empaque/resumen.html',
        kpis=kpis,
        requieren_atencion=requieren_atencion,
        salidas_mes=salidas_mes,
        salidas_area=salidas_area,
        entradas_recientes=entradas_recientes,
        lotes_pulpa=lotes_pulpa,
        mes_actual=mes_inicio.strftime('%B %Y').capitalize(),
    )


# ---------------------------------------------------------------------
# Sub-pestaña B: Inventario
# ---------------------------------------------------------------------
@app.route('/embarques/empaque/inventario', methods=['GET'])
@login_required
def empaque_inventario():
    """
    Listado de artículos con stock, filtros y botones de estado.
    Acceso: todos los roles.
    """
    q_buscar = (request.args.get('buscar') or '').strip()
    q_categoria = _parse_int_or_none(request.args.get('categoria'))
    q_estado = (request.args.get('estado') or 'todos').strip().lower()

    query = EmpaqueArticulo.query.order_by(EmpaqueArticulo.nombre)
    if q_buscar:
        like = f'%{q_buscar}%'
        query = query.filter(db.or_(
            EmpaqueArticulo.codigo.ilike(like),
            EmpaqueArticulo.nombre.ilike(like),
        ))
    if q_categoria:
        query = query.filter_by(id_categoria=q_categoria)

    articulos_raw = query.all()
    categorias = EmpaqueCategoria.query.filter_by(activo=True).order_by(EmpaqueCategoria.nombre).all()

    stock_map, dynamics_map, diferencia_map = {}, {}, {}
    if articulos_raw:
        cods = [a.codigo for a in articulos_raw]
        stock_map = _empaque_calcular_stock_batch(cods)
        for a in articulos_raw:
            dynamics_map[a.codigo] = a.fisico_dynamics
            if a.fisico_dynamics is None:
                diferencia_map[a.codigo] = None
            else:
                diferencia_map[a.codigo] = stock_map.get(a.codigo, 0) - a.fisico_dynamics

    # Filtro por estado (calculado después de batch)
    estados_visibles = {
        'negativo_dynamics': {'neg_dynamics'},
        'sin_stock': {'sin_stock'},
        'bajo_minimo': {'bajo_min'},
        'sin_dynamics': {'sin_dynamics'},
        'con_diferencia': {'con_diferencia'},
        'cuadra': {'cuadra'},
    }
    articulos = []
    for a in articulos_raw:
        stock = stock_map.get(a.codigo, 0)
        dyn = dynamics_map.get(a.codigo)
        dif = diferencia_map.get(a.codigo)
        minimo = a.stock_minimo if a.stock_minimo is not None else 0
        clave, _etiq, _color = _empaque_estado_desde_valores(stock, dyn, minimo)
        if q_estado == 'todos' or clave in estados_visibles.get(q_estado, set()):
            articulos.append(a)

    return _empaque_render_base(
        'inventario',
        'empaque/inventario.html',
        articulos=articulos,
        categorias=categorias,
        filtros={
            'buscar': q_buscar,
            'id_categoria': q_categoria,
            'estado': q_estado,
        },
        stock_map=stock_map,
        dynamics_map=dynamics_map,
        diferencia_map=diferencia_map,
    )


# API auxiliar (GET) para el panel lateral de historial por artículo.
@app.route('/embarques/empaque/api/articulo/<codigo>', methods=['GET'])
@login_required
def empaque_api_articulo_detalle(codigo):
    """
    Endpoint JSON auxiliar para el panel lateral del Inventario.
    Devuelve historial de movimientos y existencia en el tiempo (últimos 30 días).
    Acceso: todos los roles.
    """
    art = EmpaqueArticulo.query.get_or_404(codigo)
    entradas = EmpaqueEntrada.query.filter_by(codigo=codigo).order_by(EmpaqueEntrada.fecha.desc(), EmpaqueEntrada.id_entrada.desc()).limit(20).all()
    salidas = EmpaqueSalida.query.filter_by(codigo=codigo).order_by(EmpaqueSalida.fecha.desc(), EmpaqueSalida.id_salida.desc()).limit(20).all()
    ajustes = EmpaqueAjuste.query.filter_by(codigo=codigo).order_by(EmpaqueAjuste.fecha.desc(), EmpaqueAjuste.id_ajuste.desc()).limit(20).all()

    def serializar_entrada(m):
        return {'tipo': 'entrada', 'fecha': m.fecha.isoformat() if m.fecha else None,
                'cantidad': float(m.cantidad), 'rechazos': float(m.rechazos or 0),
                'detalle': m.proveedor.nombre if m.proveedor else '',
                'comentario': m.comentario,
                'usuario': m.usuario.usuario if m.usuario else ''}
    def serializar_salida(m):
        return {'tipo': 'salida', 'fecha': m.fecha.isoformat() if m.fecha else None,
                'cantidad': float(m.cantidad),
                'detalle': (m.area.nombre if m.area else '') +
                           (f' (Lote {m.lote.codigo_lote})' if m.lote else ''),
                'comentario': m.comentario,
                'usuario': m.usuario.usuario if m.usuario else ''}
    def serializar_ajuste(m):
        return {'tipo': 'ajuste', 'fecha': m.fecha.isoformat() if m.fecha else None,
                'cantidad': float(m.cantidad),
                'detalle': m.motivo,
                'comentario': '',
                'usuario': m.usuario.usuario if m.usuario else ''}

    movs = (
        [serializar_entrada(e) for e in entradas] +
        [serializar_salida(s) for s in salidas] +
        [serializar_ajuste(a) for a in ajustes]
    )
    movs.sort(key=lambda r: (r.get('fecha') or '', r['tipo']), reverse=True)

    stock = art.stock_actual
    clave, etiq, color = art.estado_articulo

    return jsonify({
        'ok': True,
        'articulo': {
            'codigo': art.codigo,
            'nombre': art.nombre,
            'um': art.um,
            'categoria': art.categoria.nombre if art.categoria else None,
            'stock_actual': float(stock),
            'fisico_dynamics': float(art.fisico_dynamics) if art.fisico_dynamics is not None else None,
            'diferencia': float(art.diferencia) if art.diferencia is not None else None,
            'estado_clave': clave,
            'estado_etiqueta': etiq,
            'estado_color': color,
        },
        'movimientos': movs[:60],
    })


# ---------------------------------------------------------------------
# Sub-pestaña C: Registrar movimiento (Entrada / Salida / Kit)
# ---------------------------------------------------------------------
@app.route('/embarques/empaque/movimiento', methods=['GET', 'POST'])
@login_required
def empaque_movimiento():
    """
    Formulario de registro de Entrada o Salida individual.
    POST: guarda el movimiento en transacción y valida stock / fecha / UM / lote para Pulpa.
    Acceso: capturista / admin.
    """
    if _empaque_deny_if_guest_or_consulta():
        return redirect(url_for('empaque_resumen'))

    if request.method == 'POST':
        tipo = (request.form.get('mov_tipo') or '').strip().lower()
        codigo = (request.form.get('codigo') or '').strip()
        cantidad_raw = (request.form.get('cantidad') or '').strip()
        fecha_str = (request.form.get('fecha') or '').strip()
        comentario = (request.form.get('comentario') or '').strip() or None

        art = EmpaqueArticulo.query.get(codigo) if codigo else None
        if not art or not art.activo:
            flash('Artículo no válido.', 'error')
            return redirect(url_for('empaque_movimiento'))
        if tipo not in ('entrada', 'salida'):
            flash('Tipo de movimiento no válido.', 'error')
            return redirect(url_for('empaque_movimiento'))

        cant_ok, cantidad, msg_cant = _validar_cantidad_por_um(cantidad_raw, art.um)
        if not cant_ok:
            flash(f'Cantidad: {msg_cant}', 'error')
            return redirect(url_for('empaque_movimiento'))
        if cantidad <= 0:
            flash('Cantidad debe ser mayor a 0.', 'error')
            return redirect(url_for('empaque_movimiento'))

        fecha_mov = _parse_date_or_none(fecha_str)
        hoy = date.today()
        if fecha_mov is None:
            flash('Fecha no válida (usa AAAA-MM-DD).', 'error')
            return redirect(url_for('empaque_movimiento'))
        if fecha_mov > hoy:
            flash('La fecha no puede ser futura.', 'error')
            return redirect(url_for('empaque_movimiento'))

        if tipo == 'entrada':
            rechazos_raw = (request.form.get('rechazos') or '0').strip()
            rec_ok, rechazos, msg_rec = _validar_cantidad_por_um(rechazos_raw, art.um)
            if not rec_ok:
                flash(f'Rechazos: {msg_rec}', 'error')
                return redirect(url_for('empaque_movimiento'))
            if rechazos < 0:
                rechazos = 0
            if rechazos > cantidad:
                flash('Rechazos no pueden superar la cantidad recibida.', 'error')
                return redirect(url_for('empaque_movimiento'))

            id_proveedor = _parse_int_or_none(request.form.get('id_proveedor'))
            entrada = EmpaqueEntrada(
                codigo=art.codigo,
                cantidad=cantidad,
                rechazos=rechazos,
                fecha=fecha_mov,
                id_proveedor=id_proveedor,
                comentario=comentario,
                creado_por=current_user.id_usuario,
            )
            db.session.add(entrada)
            db.session.commit()
            flash(f'Entrada registrada: {art.nombre} · {_format_numero(cantidad, art.um)} {art.um}.', 'success')
            return redirect(url_for('empaque_movimiento'))

        # Salida
        id_area = _parse_int_or_none(request.form.get('id_area'))
        area = EmpaqueArea.query.get(id_area) if id_area else None
        if not area:
            flash('Selecciona un área que solicite.', 'error')
            return redirect(url_for('empaque_movimiento'))

        id_lote = _parse_int_or_none(request.form.get('id_lote'))
        es_pulpa = (area.nombre or '').strip().lower() == 'pulpa'
        if es_pulpa and not id_lote:
            flash('Para el área Pulpa es obligatorio elegir un lote.', 'error')
            return redirect(url_for('empaque_movimiento'))
        if id_lote:
            lote_obj = Lote.query.get(id_lote)
            if not lote_obj:
                flash('Lote no válido.', 'error')
                return redirect(url_for('empaque_movimiento'))

        stock_actual = art.stock_actual
        if stock_actual < cantidad:
            flash(
                f'Stock insuficiente para "{art.nombre}". Disponible: {_format_numero(stock_actual, art.um)} {art.um}, '
                f'solicitaste {_format_numero(cantidad, art.um)} {art.um}.',
                'error'
            )
            return redirect(url_for('empaque_movimiento'))

        salida = EmpaqueSalida(
            codigo=art.codigo,
            cantidad=cantidad,
            fecha=fecha_mov,
            id_area=area.id_area,
            id_lote=id_lote,
            comentario=comentario,
            creado_por=current_user.id_usuario,
        )
        db.session.add(salida)
        db.session.commit()
        flash(f'Salida registrada: {art.nombre} · {_format_numero(cantidad, art.um)} {art.um} hacia {area.nombre}.', 'success')
        return redirect(url_for('empaque_movimiento'))

    articulos = EmpaqueArticulo.query.filter_by(activo=True).order_by(EmpaqueArticulo.nombre).all()
    areas = EmpaqueArea.query.filter_by(activo=True).order_by(EmpaqueArea.nombre).all()
    proveedores = EmpaqueProveedor.query.filter_by(activo=True).order_by(EmpaqueProveedor.nombre).all()
    lotes = Lote.query.order_by(Lote.codigo_lote.desc()).limit(200).all()

    # Listado mix movimientos recientes (últimas 30 filas)
    recientes = []
    for e in EmpaqueEntrada.query.order_by(EmpaqueEntrada.fecha.desc(), EmpaqueEntrada.id_entrada.desc()).limit(15).all():
        recientes.append((
            e.fecha, 'E',
            e.articulo.nombre if e.articulo else e.codigo,
            e.cantidad,
            (e.proveedor.nombre if e.proveedor else '') + (f' · rechazos {e.rechazos}' if e.rechazos else ''),
            'chip-success',
        ))
    for s in EmpaqueSalida.query.order_by(EmpaqueSalida.fecha.desc(), EmpaqueSalida.id_salida.desc()).limit(15).all():
        detalle = s.area.nombre if s.area else ''
        if s.lote:
            detalle += f' · lote {s.lote.codigo_lote}'
        recientes.append((
            s.fecha, 'S',
            s.articulo.nombre if s.articulo else s.codigo,
            s.cantidad,
            detalle,
            'chip-danger',
        ))
    recientes.sort(key=lambda r: (r[0] or date.min), reverse=True)
    movimientos_recientes = []
    for fecha, tipo, nombre, cant, detalle, chip in recientes[:30]:
        movimientos_recientes.append({
            'tipo': 'Entrada' if tipo == 'E' else 'Salida',
            'articulo': nombre,
            'cantidad': _format_numero(cant),
            'fecha': fecha.isoformat() if fecha else '',
            'detalle': detalle,
            'chip': chip,
        })

    # Kit sugerido para el área Pulpa
    kit_filas = []
    from decimal import Decimal
    from sqlalchemy import func as sqla_func
    # Buscar el área "Pulpa"
    area_pulpa = next(
        (a for a in areas if (a.nombre or '').strip().lower() == 'pulpa'),
        None
    )
    if area_pulpa:
        cmap = {}
        for cod, val in db.session.query(
            EmpaqueEntrada.codigo, sqla_func.coalesce(sqla_func.sum(EmpaqueEntrada.cantidad - sqla_func.coalesce(EmpaqueEntrada.rechazos, 0)), 0)
        ).group_by(EmpaqueEntrada.codigo).all():
            cmap[cod] = Decimal(str(val))
        smap = {}
        for cod, val in db.session.query(EmpaqueSalida.codigo, sqla_func.coalesce(sqla_func.sum(EmpaqueSalida.cantidad), 0)).group_by(EmpaqueSalida.codigo).all():
            smap[cod] = Decimal(str(val))
        amap = {}
        for cod, val in db.session.query(EmpaqueAjuste.codigo, sqla_func.coalesce(sqla_func.sum(EmpaqueAjuste.cantidad), 0)).group_by(EmpaqueAjuste.codigo).all():
            amap[cod] = Decimal(str(val))
        kits = EmpaqueKit.query.filter_by(id_area=area_pulpa.id_area).all()
        for kc in kits:
            art = EmpaqueArticulo.query.get(kc.codigo)
            stock = (cmap.get(kc.codigo, Decimal('0')) - smap.get(kc.codigo, Decimal('0')) + amap.get(kc.codigo, Decimal('0')))
            um = art.um if art else 'Pz'
            kit_filas.append({
                'articulo': art,
                'cantidad_sugerida': _format_numero(kc.cantidad_sugerida, um),
                'disponible': _format_numero(stock, um),
                'codigo': kc.codigo,
                'cantidad_raw': float(kc.cantidad_sugerida),
                'stock_raw': float(stock),
            })

    return _empaque_render_base(
        'movimiento',
        'empaque/movimiento.html',
        articulos=articulos,
        areas=areas,
        proveedores=proveedores,
        lotes=lotes,
        movimientos_recientes=movimientos_recientes,
        kit_filas=kit_filas,
        area_pulpa_nombre='Pulpa',
    )


@app.route('/embarques/empaque/kit', methods=['POST'])
@login_required
def empaque_registrar_kit():
    """
    Registra el kit COMPLETO de una sola vez (transacción TODO O NADA).
    Si un artículo no tiene stock suficiente NO se guarda NINGUNA salida.
    Acceso: capturista / admin.
    """
    if _empaque_deny_if_guest_or_consulta():
        return redirect(url_for('empaque_resumen'))

    area_pulpa = EmpaqueArea.query.filter(EmpaqueArea.activo == True).all()
    area_pulpa = next((a for a in area_pulpa if (a.nombre or '').strip().lower() == 'pulpa'), None)
    if not area_pulpa:
        flash('No existe el área "Pulpa" para registrar el kit.', 'error')
        return redirect(url_for('empaque_movimiento'))

    kits = EmpaqueKit.query.filter_by(id_area=area_pulpa.id_area).all()
    if not kits:
        flash('No hay un kit configurado para el área Pulpa. Defínelo en Catálogo · Kits (solo admin).', 'error')
        return redirect(url_for('empaque_movimiento'))

    id_lote = _parse_int_or_none(request.form.get('id_lote') or request.args.get('id_lote'))
    fecha_str = (request.form.get('fecha') or '').strip() or date.today().isoformat()
    comentario = (request.form.get('comentario') or '').strip() or None
    comentario_final = f'[Kit Pulpa] ' + (comentario or '')

    fecha_mov = _parse_date_or_none(fecha_str) or date.today()
    if fecha_mov > date.today():
        flash('Fecha del kit no puede ser futura.', 'error')
        return redirect(url_for('empaque_movimiento'))

    if not id_lote:
        flash('Para registrar el kit se requiere un lote de Pulpa. Selecciónalo antes de enviar.', 'error')
        return redirect(url_for('empaque_movimiento'))
    lote_obj = Lote.query.get(id_lote)
    if not lote_obj:
        flash('Lote no válido.', 'error')
        return redirect(url_for('empaque_movimiento'))

    # Resolver artículos y validar stock TODO O NADA
    articulos_kit = []
    faltantes = []
    for kc in kits:
        art = EmpaqueArticulo.query.get(kc.codigo)
        if not art or not art.activo:
            faltantes.append(f'Artículo {kc.codigo} no existe o está inactivo.')
            continue
        if art.stock_actual < kc.cantidad_sugerida:
            faltantes.append(
                f'{art.nombre}: disponible {_format_numero(art.stock_actual, art.um)} {art.um} '
                f'< {_format_numero(kc.cantidad_sugerida, art.um)} {art.um}'
            )
        articulos_kit.append((art, kc.cantidad_sugerida))
    if faltantes:
        flash('No se registró nada (kit todo o nada). Faltan: ' + ' | '.join(faltantes), 'error')
        return redirect(url_for('empaque_movimiento'))

    # Paso 2: registrar salidas en transacción única
    try:
        for art, cantidad in articulos_kit:
            db.session.add(EmpaqueSalida(
                codigo=art.codigo,
                cantidad=cantidad,
                fecha=fecha_mov,
                id_area=area_pulpa.id_area,
                id_lote=id_lote,
                comentario=comentario_final,
                creado_por=current_user.id_usuario,
            ))
        db.session.commit()
        flash(f'Kit registrado: {len(articulos_kit)} artículos · lote {lote_obj.codigo_lote}.', 'success')
    except Exception as exc:  # pragma: no cover - rollback por error de BD
        db.session.rollback()
        flash(f'Error al guardar el kit: {exc}', 'error')
    return redirect(url_for('empaque_movimiento'))


# ---------------------------------------------------------------------
# Sub-pestaña D: Catálogo y configuración (solo admin)
# ---------------------------------------------------------------------
@app.route('/embarques/empaque/catalogo', methods=['GET', 'POST'])
@login_required
def empaque_catalogo():
    """
    Sub-pestaña D: Catálogo + Carga masiva + Conciliación + Ajustes + Export.
    Contiene secciones (anclas): articulos, categorias, areas, proveedores,
    kits, carga_masiva, conciliacion, ajustes, exportacion.
    Acceso: solo administrador.
    """
    if _empaque_deny_if_not_admin():
        return redirect(url_for('empaque_resumen'))
    ultimos_ajustes_raw = EmpaqueAjuste.query.order_by(
        EmpaqueAjuste.fecha.desc(), EmpaqueAjuste.id_ajuste.desc()
    ).limit(15).all()
    ultimos_ajustes = []
    for a in ultimos_ajustes_raw:
        ultimos_ajustes.append({
            'fecha': a.fecha.isoformat() if a.fecha else '',
            'articulo': a.articulo.nombre if a.articulo else a.codigo,
            'cantidad': _format_numero(a.cantidad, a.articulo.um if a.articulo else 'Pz'),
            'motivo': a.motivo,
            'usuario': a.usuario.usuario if a.usuario else None,
        })

    # --- Fase 3: implementación completa (CRUD + cargas) ---
    return _empaque_render_base(
        'catalogo',
        'empaque/catalogo.html',
        seccion=(request.args.get('seccion') or 'articulos'),
        articulos=EmpaqueArticulo.query.order_by(EmpaqueArticulo.nombre).all(),
        categorias=EmpaqueCategoria.query.order_by(EmpaqueCategoria.activo.desc(), EmpaqueCategoria.nombre).all(),
        areas=EmpaqueArea.query.order_by(EmpaqueArea.activo.desc(), EmpaqueArea.nombre).all(),
        proveedores=EmpaqueProveedor.query.order_by(EmpaqueProveedor.activo.desc(), EmpaqueProveedor.nombre).all(),
        kits=EmpaqueKit.query.order_by(EmpaqueKit.id_area, EmpaqueKit.codigo).all(),
        # Datos de sesión para preview de cargas masivas
        carga_articulos=session.get('empaque_carga_articulos'),
        carga_entradas=session.get('empaque_carga_movs_entradas'),
        carga_salidas=session.get('empaque_carga_movs_salidas'),
        ultimos_ajustes=ultimos_ajustes,
    )


# --- Stubs de escritura del Catálogo (Fase 3, luego se llena) ---

@app.route('/embarques/empaque/catalogo/articulo', methods=['POST'])
@login_required
def empaque_catalogo_guardar_articulo():
    """
    Alta o edición de un artículo de empaque. Solo administrador.

    Reglas de negocio:
      - Código único (PK natural).
      - Nombre único.
      - Si el artículo ya tiene movimientos NO SE PUEDE MODIFICAR código,
        ni UM (ambos comprometen stock / auditoría).
      - No se elimina físicamente; si tiene movimientos solo inactivar.
    """
    if _empaque_deny_if_not_admin():
        return redirect(url_for('empaque_resumen'))
    form = request.form

    # Si viene codigo_original es edición; de lo contrario alta nueva.
    codigo_original = (form.get('codigo_original') or '').strip()
    nuevo_codigo = (form.get('codigo') or '').strip().upper()
    nombre = _validar_y_normalizar_texto(form.get('nombre'), mayusculas=False)
    id_categoria = _parse_int_or_none(form.get('id_categoria'))
    um = (form.get('um') or '').strip()
    almacen = (form.get('almacen') or 'CP005').strip().upper() or 'CP005'
    stock_minimo = _parse_decimal_or_none(form.get('stock_minimo'))
    fisico_dynamics = _parse_decimal_or_none(form.get('fisico_dynamics'))

    errores = []
    if not nuevo_codigo:
        errores.append('El código es obligatorio.')
    if not nombre:
        errores.append('El nombre es obligatorio.')
    if um not in ('Pz', 'Kg'):
        errores.append('La unidad de medida debe ser Pz o Kg.')
    if stock_minimo is not None and stock_minimo < 0:
        errores.append('El stock mínimo no puede ser negativo.')

    if errores:
        for e in errores:
            flash(e, 'danger')
        return redirect(url_for('empaque_catalogo', seccion='articulos'))

    # Si es edición
    if codigo_original:
        art = EmpaqueArticulo.query.filter_by(codigo=codigo_original).first()
        if not art:
            flash('Artículo original no encontrado.', 'danger')
            return redirect(url_for('empaque_catalogo', seccion='articulos'))

        tiene_movs = _empaque_tiene_movimientos(codigo_original)

        # Restricción: no cambiar código ni UM si tiene movimientos.
        if tiene_movs and nuevo_codigo != codigo_original:
            flash('No se puede cambiar el código: el artículo ya tiene movimientos asociados.', 'danger')
            return redirect(url_for('empaque_catalogo', seccion='articulos'))
        if tiene_movs and um != art.um:
            flash('No se puede cambiar la unidad: el artículo ya tiene movimientos asociados.', 'danger')
            return redirect(url_for('empaque_catalogo', seccion='articulos'))

        # Validar que el nuevo código no exista en otro artículo.
        if nuevo_codigo != codigo_original:
            if EmpaqueArticulo.query.filter_by(codigo=nuevo_codigo).first():
                flash(f'Ya existe un artículo con el código {nuevo_codigo}.', 'danger')
                return redirect(url_for('empaque_catalogo', seccion='articulos'))
            art.codigo = nuevo_codigo

        # Validar que el nombre no se duplique en otro artículo.
        otro = EmpaqueArticulo.query.filter(
            db.func.lower(EmpaqueArticulo.nombre) == nombre.lower(),
            EmpaqueArticulo.codigo != art.codigo
        ).first()
        if otro:
            flash('Ya existe un artículo con ese nombre.', 'danger')
            return redirect(url_for('empaque_catalogo', seccion='articulos'))

        art.nombre = nombre
        art.um = um
        art.almacen = almacen
        art.id_categoria = id_categoria
        art.stock_minimo = stock_minimo
        art.fisico_dynamics = fisico_dynamics
        art.activo = True if (form.get('activo') or '1') == '1' else art.activo

        try:
            db.session.commit()
            flash(f'Artículo {art.codigo} actualizado correctamente.', 'success')
        except Exception as ex:
            db.session.rollback()
            flash(f'Error al guardar: {ex}', 'danger')

        return redirect(url_for('empaque_catalogo', seccion='articulos'))

    # --- Alta nueva ---
    if EmpaqueArticulo.query.filter_by(codigo=nuevo_codigo).first():
        flash(f'Ya existe un artículo con el código {nuevo_codigo}.', 'danger')
        return redirect(url_for('empaque_catalogo', seccion='articulos'))
    if EmpaqueArticulo.query.filter(
        db.func.lower(EmpaqueArticulo.nombre) == nombre.lower()
    ).first():
        flash('Ya existe un artículo con ese nombre.', 'danger')
        return redirect(url_for('empaque_catalogo', seccion='articulos'))

    nuevo = EmpaqueArticulo(
        codigo=nuevo_codigo,
        nombre=nombre,
        id_categoria=id_categoria,
        um=um,
        almacen=almacen,
        stock_minimo=stock_minimo,
        fisico_dynamics=fisico_dynamics,
        activo=True,
    )
    db.session.add(nuevo)
    try:
        db.session.commit()
        flash(f'Artículo {nuevo.codigo} creado correctamente.', 'success')
    except Exception as ex:
        db.session.rollback()
        flash(f'Error al crear: {ex}', 'danger')
    return redirect(url_for('empaque_catalogo', seccion='articulos'))


@app.route('/embarques/empaque/catalogo/articulo/toggle', methods=['POST'])
@login_required
def empaque_catalogo_toggle_articulo():
    """
    Activa o inactiva un artículo (baja lógica).
    Si tiene movimientos NUNCA se borra; solo se desactiva.
    """
    if _empaque_deny_if_not_admin():
        return redirect(url_for('empaque_resumen'))
    codigo = (request.form.get('codigo') or '').strip()
    art = EmpaqueArticulo.query.filter_by(codigo=codigo).first()
    if not art:
        flash('Artículo no encontrado.', 'danger')
        return redirect(url_for('empaque_catalogo', seccion='articulos'))
    art.activo = not art.activo
    db.session.commit()
    flash(f'Artículo {art.codigo} {"activado" if art.activo else "inactivado"} correctamente.',
          'success')
    return redirect(url_for('empaque_catalogo', seccion='articulos'))


# =====================================================================
# CRUD simple de catálogos (Categoría / Área / Proveedor).
# Todos comparten la misma lógica: UNIQUE(nombre), activo, nunca borrar.
# =====================================================================

def _empaque_guardar_catalogo_simple(Model, attr_nombre, seccion):
    """Reutilizable para los 3 catálogos simples de Empaque."""
    if _empaque_deny_if_not_admin():
        return redirect(url_for('empaque_resumen'))
    nombre = _validar_y_normalizar_texto(request.form.get('nombre'), mayusculas=False)
    id_item = _parse_int_or_none(request.form.get('id_item'))
    if not nombre:
        flash('Nombre es obligatorio.', 'danger')
        return redirect(url_for('empaque_catalogo', seccion=seccion))
    # Editar
    if id_item:
        obj = Model.query.get(id_item)
        if not obj:
            flash('Registro no encontrado.', 'danger')
            return redirect(url_for('empaque_catalogo', seccion=seccion))
        # Validar que no exista el mismo nombre en otro registro
        otro = Model.query.filter(
            db.func.lower(getattr(Model, attr_nombre)) == nombre.lower(),
            Model.__table__.primary_key.columns.values()[0] != id_item
        ).first()
        if otro:
            flash(f'Ya existe un registro con ese nombre en {seccion}.', 'danger')
            return redirect(url_for('empaque_catalogo', seccion=seccion))
        setattr(obj, attr_nombre, nombre)
        if request.form.get('activo') is not None:
            obj.activo = request.form.get('activo') == '1'
        db.session.commit()
        flash('Registro actualizado.', 'success')
        return redirect(url_for('empaque_catalogo', seccion=seccion))
    # Nuevo
    if Model.query.filter(db.func.lower(getattr(Model, attr_nombre)) == nombre.lower()).first():
        flash(f'Ya existe un registro con ese nombre en {seccion}.', 'danger')
        return redirect(url_for('empaque_catalogo', seccion=seccion))
    nuevo = Model(**{attr_nombre: nombre, 'activo': True})
    db.session.add(nuevo)
    db.session.commit()
    flash('Registro agregado correctamente.', 'success')
    return redirect(url_for('empaque_catalogo', seccion=seccion))


@app.route('/embarques/empaque/catalogo/categoria', methods=['POST'])
@login_required
def empaque_catalogo_guardar_categoria():
    return _empaque_guardar_catalogo_simple(EmpaqueCategoria, 'nombre', 'categorias')


@app.route('/embarques/empaque/catalogo/area', methods=['POST'])
@login_required
def empaque_catalogo_guardar_area():
    return _empaque_guardar_catalogo_simple(EmpaqueArea, 'nombre', 'areas')


@app.route('/embarques/empaque/catalogo/proveedor', methods=['POST'])
@login_required
def empaque_catalogo_guardar_proveedor():
    return _empaque_guardar_catalogo_simple(EmpaqueProveedor, 'nombre', 'proveedores')


# =====================================================================
# CRUD de Kit por área
# =====================================================================

@app.route('/embarques/empaque/catalogo/kit', methods=['POST'])
@login_required
def empaque_catalogo_guardar_kit():
    """
    Agrega o actualiza una fila de kit por (área, artículo).
    Si la combinación ya existe actualiza cantidad_sugerida; si no crea.
    """
    if _empaque_deny_if_not_admin():
        return redirect(url_for('empaque_resumen'))
    form = request.form
    id_area = _parse_int_or_none(form.get('id_area'))
    codigo = (form.get('codigo') or '').strip()
    cant = _parse_decimal_or_none(form.get('cantidad_sugerida'))

    if not id_area or not EmpaqueArea.query.get(id_area):
        flash('Área no válida.', 'danger')
        return redirect(url_for('empaque_catalogo', seccion='kits'))
    if not codigo or not EmpaqueArticulo.query.filter_by(codigo=codigo).first():
        flash('Artículo no válido.', 'danger')
        return redirect(url_for('empaque_catalogo', seccion='kits'))
    if not cant or cant <= 0:
        flash('Cantidad sugerida debe ser mayor a cero.', 'danger')
        return redirect(url_for('empaque_catalogo', seccion='kits'))

    existente = EmpaqueKit.query.filter_by(id_area=id_area, codigo=codigo).first()
    if existente:
        existente.cantidad_sugerida = cant
    else:
        db.session.add(EmpaqueKit(id_area=id_area, codigo=codigo, cantidad_sugerida=cant))
    try:
        db.session.commit()
        flash('Fila de kit guardada correctamente.', 'success')
    except Exception as ex:
        db.session.rollback()
        flash(f'Error: {ex}', 'danger')
    return redirect(url_for('empaque_catalogo', seccion='kits'))


@app.route('/embarques/empaque/catalogo/kit/<int:id_kit>/eliminar', methods=['POST'])
@login_required
def empaque_catalogo_eliminar_kit(id_kit):
    """Elimina una fila del kit. El kit no es movimiento, no requiere auditoría."""
    if _empaque_deny_if_not_admin():
        return redirect(url_for('empaque_resumen'))
    k = EmpaqueKit.query.get(id_kit)
    if not k:
        flash('Kit no encontrado.', 'danger')
    else:
        db.session.delete(k)
        db.session.commit()
        flash('Fila de kit eliminada.', 'success')
    return redirect(url_for('empaque_catalogo', seccion='kits'))


# ---------------------------------------------------------------------
# Carga masiva
# ---------------------------------------------------------------------

# Plantillas Excel descargables (vacías, con encabezados).
_EMPAQUE_PLANTILLAS_COLUMNAS = {
    # tipo -> (nombre_base, columnas ordenadas, comentario de hoja)
    'articulos': (
        'Plantilla_Catalogo_Empaque',
        ['codigo', 'nombre', 'categoria', 'UM', 'almacen', 'stock_minimo', 'fisico_dynamics', 'activo'],
        (
            'Carga de catálogo de artículos de empaque.\n'
            '- codigo: único, 20 caracteres máximo (ej. IN00120071).\n'
            '- nombre: único, no se duplica.\n'
            '- categoria: nombre EXACTO (sensible a mayúsculas/minúsculas) de una categoría existente\n'
            '  o creada previamente en Catálogos · Categorías. Vacío = sin categoría.\n'
            '- UM: "Pz" o "Kg" (sensible a mayúsculas/minúsculas).\n'
            '- almacen: default CP005 si se deja vacío.\n'
            '- stock_minimo y fisico_dynamics: números. Vacíos se dejan NULL (opcionales).\n'
            '- activo: 1 = sí, 0 = no. Default 1.'
        ),
    ),
    'entradas': (
        'Plantilla_Entradas_Empaque',
        ['codigo', 'cantidad', 'fecha', 'proveedor', 'rechazos', 'comentario'],
        (
            'Carga de entradas históricas de empaque.\n'
            '- codigo: debe existir previamente en el catálogo de artículos.\n'
            '- cantidad: > 0. Para Pz debe ser entera; para Kg se permiten hasta 3 decimales.\n'
            '- fecha: YYYY-MM-DD. No futura.\n'
            '- proveedor: nombre EXACTO de un proveedor existente o dado de alta antes.\n'
            '- rechazos: >= 0 y <= cantidad. Default 0 si se deja vacío.\n'
            '- comentario: texto libre (opcional).'
        ),
    ),
    'salidas': (
        'Plantilla_Salidas_Empaque',
        ['codigo', 'cantidad', 'fecha', 'area', 'lote', 'comentario'],
        (
            'Carga de salidas históricas de empaque.\n'
            '- codigo: debe existir previamente en el catálogo de artículos.\n'
            '- cantidad: > 0 y debe haber stock suficiente (se valida TODO antes de guardar).\n'
            '- fecha: YYYY-MM-DD. No futura.\n'
            '- area: nombre EXACTO de un área existente.\n'
            '- lote: código del lote de pulpa EXISTENTE en SICSE (SÓLO si área es Pulpa;\n'
            '  en ese caso OBLIGATORIO). Para otras áreas dejar vacío.'
        ),
    ),
    'dynamics': (
        'Plantilla_Conciliacion_Dynamics',
        ['codigo', 'fisico_dynamics'],
        (
            'Conciliación con Dynamics.\n'
            '- codigo: artículo existente.\n'
            '- fisico_dynamics: número oficial de Dynamics. Puede ser positivo o negativo.\n'
            '  Se actualiza ÚNICAMENTE el campo fisico_dynamics; NO se tocan movimientos ni stock interno.'
        ),
    ),
}


@app.route('/embarques/empaque/carga/plantilla/<tipo>')
@login_required
def empaque_carga_masiva_plantilla(tipo):
    """
    Descarga una plantilla de Excel vacía con encabezados.
    tipos soportados: articulos, entradas, salidas, dynamics.
    """
    if _empaque_deny_if_not_admin():
        return redirect(url_for('empaque_resumen'))
    tipo = (tipo or '').strip().lower()
    if tipo not in _EMPAQUE_PLANTILLAS_COLUMNAS:
        flash('Plantilla no válida.', 'danger')
        return redirect(url_for('empaque_catalogo', seccion='carga_masiva'))
    nombre_base, cols, comentario = _EMPAQUE_PLANTILLAS_COLUMNAS[tipo]
    # Una hoja con los encabezados + una hoja con instrucciones.
    df = pd.DataFrame(columns=cols)
    comentarios_filas = [[cols[i], comentario] for i in range(len(cols))]
    # Para tipos artículos/entradas/salidas agregamos una fila de ejemplo vacía
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Plantilla')
        # Ancho automático básico
        ws = writer.sheets['Plantilla']
        for i, c in enumerate(cols, start=1):
            ws.column_dimensions[chr(64 + i) if i <= 26 else 'A' + chr(64 + i - 26)].width = max(18, len(c) + 4)
        pd.DataFrame(
            [['Campo', 'Descripción']] + comentarios_filas,
            columns=None
        ).to_excel(writer, index=False, header=False, sheet_name='Instrucciones')
    output.seek(0)
    filename = f'{nombre_base}.xlsx'
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=filename,
    )

@app.route('/embarques/empaque/carga/articulos', methods=['POST'])
@login_required
def empaque_carga_masiva_articulos():
    """
    Carga masiva de artículos. Flujo:
      1. Recibe Excel.
      2. VALIDA TODO fila por fila.
      3. Guarda el resultado en SESIÓN y redirige a Catálogo con vista previa:
          - Sección: lista de filas correctas (checkbox aplicar)
          - Reporte descargable de rechazados (Excel con columna "error")
          - Botón "Aplicar filas correctas" que inserta en transacción.
    """
    if _empaque_deny_if_not_admin():
        return redirect(url_for('empaque_resumen'))

    archivo = request.files.get('archivo')
    if not archivo or not archivo.filename:
        flash('No seleccionaste ningún archivo.', 'danger')
        return redirect(url_for('empaque_catalogo', seccion='carga_masiva'))
    if not archivo.filename.lower().endswith(('.xlsx', '.xls')):
        flash('Formato no válido: sube un archivo .xlsx o .xls.', 'danger')
        return redirect(url_for('empaque_catalogo', seccion='carga_masiva'))

    try:
        df = pd.read_excel(archivo, dtype=str)
        df.columns = [str(c).strip() for c in df.columns]
        cols_norm = {_empaque_normalizar_clave_importacion(c): c for c in df.columns}
        col_codigo = _empaque_resolver_columna(cols_norm, 'codigo', 'código', 'numero de articulo', 'numero de artículo')
        col_nombre = _empaque_resolver_columna(cols_norm, 'nombre', 'nombre del producto', 'producto')
        col_um = _empaque_resolver_columna(cols_norm, 'um')
        col_almacen = _empaque_resolver_columna(cols_norm, 'almacen', 'almacén')
        col_categoria = _empaque_resolver_columna(cols_norm, 'categoria', 'categoría')
        col_stock_minimo = _empaque_resolver_columna(cols_norm, 'stock minimo', 'stock mínimo')
        col_fisico = _empaque_resolver_columna(
            cols_norm,
            'fisico_dynamics', 'físico_dynamics', 'inventario fisico actual',
            'inventario fisico', 'inventario fis', 'fisico', 'físico'
        )
        col_activo = _empaque_resolver_columna(cols_norm, 'activo')
        faltan = []
        if not col_codigo:
            faltan.append('codigo / Número de artículo')
        if not col_nombre:
            faltan.append('nombre / Nombre del producto')
        if not col_um:
            faltan.append('UM')
        if faltan:
            flash(f'Faltan columnas obligatorias: {", ".join(faltan)}', 'danger')
            return redirect(url_for('empaque_catalogo', seccion='carga_masiva'))
    except Exception as ex:
        flash(f'No se pudo leer el archivo: {ex}', 'danger')
        return redirect(url_for('empaque_catalogo', seccion='carga_masiva'))

    # Precacheo catálogos para O(1) lookup en validación
    categorias_map = {c.nombre: c.id_categoria for c in EmpaqueCategoria.query.all()}
    codigos_bd = {a.codigo for a in EmpaqueArticulo.query.with_entities(EmpaqueArticulo.codigo).all()}
    nombres_bd_lower = {a.nombre.lower(): a.codigo for a in EmpaqueArticulo.query.with_entities(
        EmpaqueArticulo.codigo, EmpaqueArticulo.nombre).all()}

    correctas = []       # lista dict para insertar
    rechazadas = []      # lista dict con 'error'
    fecha_hoy = date.today()
    for idx, row in df.iterrows():
        n_fila = idx + 2   # +1 por encabezado, +1 base 1
        # Limpiar celdas
        vals = {c: (str(row[c]).strip() if pd.notna(row[c]) else '') for c in df.columns}
        codigo = (vals.get(col_codigo, '') or '').upper()
        nombre = _validar_y_normalizar_texto(vals.get(col_nombre), mayusculas=False) or ''
        categoria_nombre = (vals.get(col_categoria, '') if col_categoria else '').strip()
        um = (vals.get(col_um, '') or '').strip().title()
        almacen = ((vals.get(col_almacen, '') if col_almacen else '').strip() or 'CP005')
        sm = (vals.get(col_stock_minimo, '') if col_stock_minimo else '').strip()
        fd = (vals.get(col_fisico, '') if col_fisico else '').strip()
        activo_raw = (vals.get(col_activo, '1') if col_activo else '1').strip()

        errores = []
        # Código
        if not codigo:
            errores.append('Código vacío.')
        elif len(codigo) > 20:
            errores.append('Código > 20 caracteres.')
        elif codigo in codigos_bd:
            errores.append(f'Código {codigo} ya existe en la BD.')
        # Nombre
        if not nombre:
            errores.append('Nombre vacío.')
        elif nombre.lower() in nombres_bd_lower and nombres_bd_lower[nombre.lower()] != codigo:
            errores.append('Nombre duplicado.')
        # UM
        if um not in ('Pz', 'Kg'):
            errores.append('UM debe ser "Pz" o "Kg".')
        # Categoría
        id_categoria = None
        if categoria_nombre:
            if categoria_nombre in categorias_map:
                id_categoria = categorias_map[categoria_nombre]
            else:
                errores.append(f'Categoría "{categoria_nombre}" no existe en Catálogos · Categorías.')
        # Stock mínimo
        stock_minimo = None
        if sm:
            try:
                d = _empaque_parse_decimal_importacion(sm)
                if d < 0:
                    errores.append('stock_minimo no puede ser negativo.')
                else:
                    stock_minimo = d
            except Exception:
                errores.append('stock_minimo no es numérico.')
        # Físico Dynamics
        fisico_dynamics = None
        if fd:
            try:
                fisico_dynamics = _empaque_parse_decimal_importacion(fd)
            except Exception:
                errores.append('fisico_dynamics no es numérico.')
        # Activo
        activo = True
        if activo_raw != '' and activo_raw not in ('1', '0'):
            try:
                activo = bool(int(activo_raw))
            except Exception:
                errores.append('activo debe ser 1 o 0.')
        elif activo_raw == '0':
            activo = False

        fila_salida = {
            'fila': n_fila,
            'codigo': codigo,
            'nombre': nombre,
            'categoria': categoria_nombre,
            'UM': um,
            'almacen': almacen,
            'stock_minimo': sm,
            'fisico_dynamics': fd,
            'activo': '1' if activo else '0',
        }
        if errores:
            fila_salida['error'] = ' | '.join(errores)
            rechazadas.append(fila_salida)
        else:
            fila_salida['id_categoria'] = id_categoria
            fila_salida['_stock_minimo'] = float(stock_minimo) if stock_minimo is not None else None
            fila_salida['_fisico_dynamics'] = float(fisico_dynamics) if fisico_dynamics is not None else None
            fila_salida['activo'] = activo
            correctas.append(fila_salida)
            # Evitar duplicados INTERNOS dentro del mismo archivo
            codigos_bd.add(codigo)
            nombres_bd_lower[nombre.lower()] = codigo

    # Guardar en sesión para poder mostrar preview y aplicar luego
    session['empaque_carga_articulos'] = {
        'correctas': correctas,
        'rechazadas': rechazadas,
        'fecha': fecha_hoy.isoformat(),
        'archivo': archivo.filename,
    }
    msg = f'Archivo procesado: {len(correctas)} filas OK, {len(rechazadas)} rechazadas.'
    if correctas:
        flash(msg + ' Revisa la vista previa y aplica las filas correctas.', 'info')
    else:
        flash(msg + ' No hay filas para aplicar.', 'warning')
    return redirect(url_for('empaque_catalogo', seccion='carga_masiva') + '#sec-carga_masiva')


@app.route('/embarques/empaque/carga/articulos/aplicar', methods=['POST'])
@login_required
def empaque_carga_masiva_articulos_aplicar():
    """
    Toma el listado guardado en sesión y aplica (inserta) las filas marcadas
    o todas si no se marca ninguna. Regresa reporte final.
    """
    if _empaque_deny_if_not_admin():
        return redirect(url_for('empaque_resumen'))
    data = session.get('empaque_carga_articulos')
    if not data or not data.get('correctas'):
        flash('No hay un lote pendiente para aplicar.', 'warning')
        return redirect(url_for('empaque_catalogo', seccion='carga_masiva'))

    # Si el usuario marcó filas con checkbox 'aplicar_<idx>'
    indices_aplicar = request.form.getlist('aplicar')
    if indices_aplicar:
        indices_aplicar = {int(i) for i in indices_aplicar if i.isdigit()}
        filas = [f for i, f in enumerate(data['correctas']) if i in indices_aplicar]
    else:
        filas = data['correctas']

    insertados = 0
    fallidos = []
    for f in filas:
        try:
            nuevo = EmpaqueArticulo(
                codigo=f['codigo'],
                nombre=f['nombre'],
                id_categoria=f.get('id_categoria'),
                um=f['UM'],
                almacen=f['almacen'] or 'CP005',
                stock_minimo=Decimal(str(f['_stock_minimo'])) if f.get('_stock_minimo') is not None else None,
                fisico_dynamics=Decimal(str(f['_fisico_dynamics'])) if f.get('_fisico_dynamics') is not None else None,
                activo=bool(f['activo']),
            )
            db.session.add(nuevo)
            insertados += 1
        except Exception as ex:
            fallidos.append({'fila': f.get('fila'), 'codigo': f['codigo'], 'error': str(ex)})

    try:
        db.session.commit()
    except Exception as ex:
        db.session.rollback()
        flash(f'Error al guardar lote: {ex}', 'danger')
        return redirect(url_for('empaque_catalogo', seccion='carga_masiva') + '#sec-carga_masiva')

    # Limpiar sesión al final
    del session['empaque_carga_articulos']
    session.modified = True

    if fallidos:
        flash(f'Se insertaron {insertados} artículos. {len(fallidos)} fallaron durante commit.', 'warning')
    else:
        flash(f'Se insertaron {insertados} artículos correctamente.', 'success')
    return redirect(url_for('empaque_catalogo', seccion='carga_masiva') + '#sec-carga_masiva')


@app.route('/embarques/empaque/carga/articulos/rechazados.xlsx')
@login_required
def empaque_carga_masiva_articulos_rechazados():
    """Descarga el reporte de filas rechazadas con su error."""
    if _empaque_deny_if_not_admin():
        return redirect(url_for('empaque_resumen'))
    data = session.get('empaque_carga_articulos') or {}
    rechazadas = data.get('rechazadas') or []
    cols = ['fila', 'codigo', 'nombre', 'categoria', 'UM', 'almacen', 'stock_minimo', 'fisico_dynamics', 'activo', 'error']
    df = pd.DataFrame(rechazadas, columns=cols)
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Rechazados')
    output.seek(0)
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name='Reporte_Rechazados_Catalogo_Empaque.xlsx',
    )


@app.route('/embarques/empaque/carga/movimientos', methods=['POST'])
@login_required
def empaque_carga_masiva_movimientos():
    """
    Carga masiva de entradas o salidas históricas.

    Parámetro oculto 'tipo' con valor 'entradas' o 'salidas'
    Flujo idéntico a artículos: validar -> sesión -> preview -> aplicar.

    Reglas de negocio:
      - Entradas: artículo existe, proveedor existe, cantidad > 0,
        rechazos >= 0 y <= cantidad, fecha no futura, UM coherente.
      - Salidas: además stock suficiente (válido acumulando lo que
        venía en BD + lo que va del archivo), área existe,
        lote obligatorio si área es Pulpa.
      - Todo se valida antes de guardar; si una fila falla no
        bloquea las demás (se reporta); las salidas se validan
        contra stock acumulando todo el archivo.
    """
    if _empaque_deny_if_not_admin():
        return redirect(url_for('empaque_resumen'))

    archivo = request.files.get('archivo')
    tipo = (request.form.get('tipo') or '').strip().lower()
    if tipo not in ('entradas', 'salidas'):
        flash('Tipo de carga no válido (debe ser entradas o salidas).', 'danger')
        return redirect(url_for('empaque_catalogo', seccion='carga_masiva') + '#sec-carga_masiva')
    if not archivo or not archivo.filename:
        flash('No seleccionaste ningún archivo.', 'danger')
        return redirect(url_for('empaque_catalogo', seccion='carga_masiva') + '#sec-carga_masiva')
    if not archivo.filename.lower().endswith(('.xlsx', '.xls')):
        flash('Formato no válido: sube un archivo .xlsx o .xls.', 'danger')
        return redirect(url_for('empaque_catalogo', seccion='carga_masiva') + '#sec-carga_masiva')

    try:
        df = pd.read_excel(archivo, dtype=str)
        df.columns = [str(c).strip() for c in df.columns]
        cols_norm = {_empaque_normalizar_clave_importacion(c): c for c in df.columns}
        if tipo == 'entradas':
            col_codigo = _empaque_resolver_columna(cols_norm, 'codigo', 'código', 'numero de articulo', 'numero de artículo')
            col_cantidad = _empaque_resolver_columna(cols_norm, 'cantidad', 'entradas', 'entrada')
            col_fecha = _empaque_resolver_columna(cols_norm, 'fecha', 'fecha entrada')
            col_proveedor = _empaque_resolver_columna(cols_norm, 'proveedor')
            col_rechazos = _empaque_resolver_columna(cols_norm, 'rechazos', 'rechazo')
            col_comentario = _empaque_resolver_columna(cols_norm, 'comentario', 'comentarios')
            faltan = []
            if not col_codigo:
                faltan.append('codigo / Número de artículo')
            if not col_cantidad:
                faltan.append('cantidad / Entradas')
            if not col_fecha:
                faltan.append('fecha / Fecha Entrada')
            if not col_proveedor:
                faltan.append('proveedor / Proveedor')
        else:
            col_codigo = _empaque_resolver_columna(cols_norm, 'codigo', 'código')
            col_cantidad = _empaque_resolver_columna(cols_norm, 'cantidad')
            col_fecha = _empaque_resolver_columna(cols_norm, 'fecha')
            col_area = _empaque_resolver_columna(cols_norm, 'area', 'área')
            col_lote = _empaque_resolver_columna(cols_norm, 'lote')
            col_comentario = _empaque_resolver_columna(cols_norm, 'comentario', 'comentarios')
            faltan = []
            if not col_codigo:
                faltan.append('codigo')
            if not col_cantidad:
                faltan.append('cantidad')
            if not col_fecha:
                faltan.append('fecha')
            if not col_area:
                faltan.append('area')
        if faltan:
            flash(f'Faltan columnas obligatorias: {", ".join(faltan)}', 'danger')
            return redirect(url_for('empaque_catalogo', seccion='carga_masiva') + '#sec-carga_masiva')
    except Exception as ex:
        flash(f'No se pudo leer el archivo: {ex}', 'danger')
        return redirect(url_for('empaque_catalogo', seccion='carga_masiva') + '#sec-carga_masiva')

    # Precacheos
    articulos_db = {a.codigo: a for a in EmpaqueArticulo.query.all()}
    proveedores_db = {_empaque_normalizar_nombre_importacion(p.nombre): p.id_proveedor for p in EmpaqueProveedor.query.all()}
    areas_db = {_empaque_normalizar_nombre_importacion(a.nombre): a for a in EmpaqueArea.query.all()}
    lotes_db = {l.codigo_lote: l.id_lote for l in Lote.query.all()}
    fecha_hoy = date.today()
    # Stock acumulativo para validar salidas secuencialmente contra la nueva carga
    stock_actual_bd = _empaque_calcular_stock_batch(list(articulos_db.keys()))
    # Clon mutable con Decimal
    stock_corrido = {k: Decimal(str(v)) for k, v in stock_actual_bd.items()}

    correctas = []
    rechazadas = []
    cols_reportes = (
        ['fila', 'codigo', 'cantidad', 'fecha', 'proveedor', 'rechazos', 'comentario', 'error']
        if tipo == 'entradas' else
        ['fila', 'codigo', 'cantidad', 'fecha', 'area', 'lote', 'comentario', 'error']
    )
    for idx, row in df.iterrows():
        n_fila = idx + 2
        vals = {c: (str(row[c]).strip() if pd.notna(row[c]) else '') for c in df.columns}
        errores = []
        fila_base = {'fila': n_fila}
        # Comunes
        codigo = (vals.get(col_codigo, '') or '').strip().upper()
        art = articulos_db.get(codigo)
        if not art:
            errores.append(f'Artículo "{codigo}" no existe en el catálogo.')
        else:
            fila_base['codigo'] = codigo
            fila_base['_um'] = art.um
            fila_base['_articulo_activo'] = art.activo
            if not art.activo:
                errores.append('El artículo está inactivo.')

        # Cantidad
        cantidad = None
        try:
            cantidad = _empaque_parse_decimal_importacion(vals.get(col_cantidad, '0') or '0')
        except Exception:
            errores.append('Cantidad no es numérica.')
        if cantidad is not None and cantidad <= 0:
            errores.append('Cantidad debe ser mayor a cero.')
        fila_base['cantidad'] = vals.get(col_cantidad, '') or ''

        # Fecha
        fecha = _empaque_parse_fecha_importacion(vals.get(col_fecha, ''))
        if not fecha:
            errores.append('Fecha inválida.')
        elif fecha > fecha_hoy:
            errores.append('Fecha futura no permitida.')
        fila_base['fecha'] = vals.get(col_fecha, '') or ''
        fila_base['_fecha_iso'] = fecha.isoformat() if fecha else None

        # Validar cantidad por UM
        if cantidad is not None and art:
            ok, msg = _empaque_validar_cantidad_por_um(cantidad, art.um)
            if not ok:
                errores.append(msg)
        fila_base['_cantidad'] = float(cantidad) if cantidad is not None else None

        if tipo == 'entradas':
            prov_nombre = (vals.get(col_proveedor, '') or '').strip()
            id_proveedor = proveedores_db.get(_empaque_normalizar_nombre_importacion(prov_nombre))
            fila_base['proveedor'] = prov_nombre
            if not prov_nombre:
                errores.append('Proveedor vacío.')
            elif id_proveedor is None:
                errores.append(f'Proveedor "{prov_nombre}" no existe en Catálogos · Proveedores.')
            else:
                fila_base['_id_proveedor'] = id_proveedor

            rechazos_raw = ((vals.get(col_rechazos, '0') if col_rechazos else '0') or '0').strip() or '0'
            fila_base['rechazos'] = rechazos_raw
            try:
                rechazos = _empaque_parse_decimal_importacion(rechazos_raw)
                if rechazos < 0:
                    errores.append('Rechazos no puede ser negativo.')
                elif cantidad is not None and rechazos > cantidad:
                    errores.append('Rechazos no puede ser mayor a la cantidad.')
                fila_base['_rechazos'] = float(rechazos)
            except Exception:
                errores.append('Rechazos no es numérico.')

            fila_base['comentario'] = (vals.get(col_comentario, '') if col_comentario else '') or ''

        else:  # salidas
            area_nombre = (vals.get(col_area, '') or '').strip()
            fila_base['area'] = area_nombre
            area = areas_db.get(_empaque_normalizar_nombre_importacion(area_nombre))
            if not area_nombre:
                errores.append('Área vacía.')
            elif not area:
                errores.append(f'Área "{area_nombre}" no existe en Catálogos · Áreas.')
            else:
                fila_base['_id_area'] = area.id_area
                # Lote obligatorio si área es Pulpa
                lote_codigo = ((vals.get(col_lote, '') if col_lote else '') or '').strip()
                fila_base['lote'] = lote_codigo
                if area.nombre.lower() == 'pulpa':
                    if not lote_codigo:
                        errores.append('Para área Pulpa se requiere el código del lote.')
                    elif lote_codigo not in lotes_db:
                        errores.append(f'Lote "{lote_codigo}" no existe en SICSE.')
                    else:
                        fila_base['_id_lote'] = lotes_db[lote_codigo]
                else:
                    if lote_codigo:
                        errores.append(f'Solo se permite lote cuando el área es Pulpa.')
                    fila_base['_id_lote'] = None
                fila_base['comentario'] = (vals.get(col_comentario, '') if col_comentario else '') or ''

                # Stock suficiente (stock actual - salidas validadas previas)
                if cantidad is not None and art:
                    stock_previo = stock_corrido.get(codigo, Decimal('0'))
                    if stock_previo < cantidad:
                        errores.append(
                            f'Stock insuficiente: quedan {empaque_format_numero(stock_previo, art.um)} {art.um}'
                            f' y se intenta sacar {empaque_format_numero(cantidad, art.um)}.'
                        )
                    else:
                        stock_corrido[codigo] = stock_previo - cantidad

        if errores:
            fila_base['error'] = ' | '.join(errores)
            rechazadas.append(fila_base)
        else:
            correctas.append(fila_base)

    # Guardar en sesión
    clave_sesion = 'empaque_carga_movs_' + tipo
    session[clave_sesion] = {
        'tipo': tipo,
        'correctas': correctas,
        'rechazadas': rechazadas,
        'fecha': fecha_hoy.isoformat(),
        'archivo': archivo.filename,
        'columnas_reporte': cols_reportes,
    }
    msg = f'Archivo procesado: {len(correctas)} filas OK, {len(rechazadas)} rechazadas.'
    if correctas:
        flash(msg + ' Revisa la vista previa y aplica las filas correctas.', 'info')
    else:
        flash(msg + ' No hay filas para aplicar.', 'warning')
    return redirect(url_for('empaque_catalogo', seccion='carga_masiva') + '#sec-carga_masiva')


@app.route('/embarques/empaque/carga/movimientos/aplicar/<tipo>', methods=['POST'])
@login_required
def empaque_carga_masiva_movimientos_aplicar(tipo):
    """Aplica las filas correctas (o seleccionadas) de la última carga."""
    if _empaque_deny_if_not_admin():
        return redirect(url_for('empaque_resumen'))
    tipo = (tipo or '').strip().lower()
    if tipo not in ('entradas', 'salidas'):
        flash('Tipo inválido.', 'danger')
        return redirect(url_for('empaque_catalogo', seccion='carga_masiva') + '#sec-carga_masiva')

    clave_sesion = 'empaque_carga_movs_' + tipo
    data = session.get(clave_sesion)
    if not data or not data.get('correctas'):
        flash('No hay un lote pendiente para aplicar.', 'warning')
        return redirect(url_for('empaque_catalogo', seccion='carga_masiva') + '#sec-carga_masiva')

    indices_aplicar = request.form.getlist('aplicar')
    if indices_aplicar:
        s = {int(i) for i in indices_aplicar if i.isdigit()}
        filas = [f for i, f in enumerate(data['correctas']) if i in s]
    else:
        filas = data['correctas']

    insertados = 0
    fallidos = []
    # Salidas: usar transacción TODO O NADA para evitar descuadre
    try:
        for f in filas:
            try:
                if tipo == 'entradas':
                    obj = EmpaqueEntrada(
                        codigo=f['codigo'],
                        cantidad=Decimal(str(f['_cantidad'])),
                        fecha=_parse_date_or_none(f.get('_fecha_iso')) or date.today(),
                        id_proveedor=f['_id_proveedor'],
                        rechazos=Decimal(str(f.get('_rechazos') or 0)),
                        comentario=f.get('comentario') or None,
                        creado_por=current_user.id_usuario,
                    )
                else:
                    # Salida: revalidar stock final a cierre (otras cargas concurrentes)
                    art = EmpaqueArticulo.query.get(f['codigo'])
                    if art:
                        if art.stock_actual < Decimal(str(f['_cantidad'])):
                            fallidos.append({
                                'fila': f.get('fila'),
                                'codigo': f['codigo'],
                                'error': f'Stock insuficiente en el momento de guardar (quedan {empaque_format_numero(art.stock_actual, art.um)} {art.um}).'
                            })
                            continue
                    obj = EmpaqueSalida(
                        codigo=f['codigo'],
                        cantidad=Decimal(str(f['_cantidad'])),
                        fecha=_parse_date_or_none(f.get('_fecha_iso')) or date.today(),
                        id_area=f['_id_area'],
                        id_lote=f.get('_id_lote'),
                        comentario=f.get('comentario') or None,
                        creado_por=current_user.id_usuario,
                    )
                db.session.add(obj)
                insertados += 1
            except Exception as ex:
                fallidos.append({'fila': f.get('fila'), 'codigo': f.get('codigo'), 'error': str(ex)})
        db.session.commit()
    except Exception as ex:
        db.session.rollback()
        flash(f'Error al guardar: {ex}', 'danger')
        return redirect(url_for('empaque_catalogo', seccion='carga_masiva') + '#sec-carga_masiva')

    del session[clave_sesion]
    session.modified = True
    if fallidos:
        flash(f'Se insertaron {insertados} movimientos. {len(fallidos)} fallaron.', 'warning')
    else:
        flash(f'Se insertaron {insertados} movimientos correctamente.', 'success')
    return redirect(url_for('empaque_catalogo', seccion='carga_masiva') + '#sec-carga_masiva')


@app.route('/embarques/empaque/carga/movimientos/rechazados/<tipo>.xlsx')
@login_required
def empaque_carga_masiva_movimientos_rechazados(tipo):
    """Reporte descargable de filas rechazadas de movimientos."""
    if _empaque_deny_if_not_admin():
        return redirect(url_for('empaque_resumen'))
    tipo = (tipo or '').strip().lower()
    if tipo not in ('entradas', 'salidas'):
        return ('Tipo inválido', 400)
    data = session.get('empaque_carga_movs_' + tipo) or {}
    cols = data.get('columnas_reporte') or ['fila', 'error']
    df = pd.DataFrame(data.get('rechazadas') or [], columns=cols)
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Rechazados')
    output.seek(0)
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=f'Reporte_Rechazados_{tipo.capitalize()}_Empaque.xlsx',
    )


# ---------------------------------------------------------------------
# Conciliación Dynamics + Ajustes + Exportación
# ---------------------------------------------------------------------
def _empaque_normalizar_clave_importacion(texto):
    """
    Normaliza encabezados o llaves de archivos Excel para compararlos.

    Convierte a minúsculas, quita acentos, reemplaza guiones bajos por
    espacios y colapsa espacios repetidos.
    """
    s = str(texto or '').strip().lower()
    reemplazos = str.maketrans('áéíóúüñ', 'aeiouun')
    s = s.translate(reemplazos).replace('_', ' ')
    s = re.sub(r'\s+', ' ', s)
    return s


def _empaque_normalizar_nombre_importacion(texto):
    """
    Normaliza el nombre del artículo para búsquedas por nombre.

    Se usa en conciliación cuando el archivo real no trae `código` y sólo
    identifica al artículo por "Nombre del producto".
    """
    return _empaque_normalizar_clave_importacion(texto)


def _empaque_resolver_columna(cols_norm, *aliases):
    """Devuelve el nombre real de la primera columna cuyo alias exista."""
    for alias in aliases:
        col = cols_norm.get(_empaque_normalizar_clave_importacion(alias))
        if col:
            return col
    return None


def _empaque_parse_decimal_importacion(valor):
    """
    Convierte números provenientes de Excel a Decimal.

    Soporta:
      - celdas vacías / "sin dato" -> None
      - separador de miles con coma: 15,504 -> Decimal('15504')
      - valores negativos: -70
    """
    if valor is None:
        return None
    s = str(valor).strip()
    if _empaque_normalizar_clave_importacion(s) in ('', 'sin dato', 'n/a', 'null', 'none', '—', '-'):
        return None
    s = s.replace(',', '').replace(' ', '')
    return Decimal(s)


def _empaque_parse_fecha_importacion(valor):
    """
    Convierte fechas de importación de empaque a `date`.

    Soporta:
      - YYYY-MM-DD
      - DD/MM/YYYY
      - "30 de septiembre de 2025"
      - "04 DE MARZO DEL 2026"
    """
    if valor is None:
        return None
    texto = str(valor).strip()
    if not texto:
        return None

    fecha = _parse_date_or_none(texto)
    if fecha:
        return fecha

    for fmt in ('%d/%m/%Y', '%d-%m-%Y'):
        try:
            return datetime.strptime(texto, fmt).date()
        except Exception:
            pass

    t = _empaque_normalizar_clave_importacion(texto)
    t = re.sub(r'\bdel\b', 'de', t)
    t = re.sub(r'\s+', ' ', t).strip()
    meses = {
        'enero': '01', 'febrero': '02', 'marzo': '03', 'abril': '04',
        'mayo': '05', 'junio': '06', 'julio': '07', 'agosto': '08',
        'septiembre': '09', 'setiembre': '09', 'octubre': '10',
        'noviembre': '11', 'diciembre': '12',
    }
    m = re.match(r'^(\d{1,2}) de ([a-z]+) de (\d{4})$', t)
    if not m:
        return None
    dia, mes_txt, anio = m.groups()
    mes = meses.get(mes_txt)
    if not mes:
        return None
    try:
        return datetime.strptime(f'{anio}-{mes}-{int(dia):02d}', '%Y-%m-%d').date()
    except Exception:
        return None


@app.route('/embarques/empaque/conciliacion', methods=['GET', 'POST'])
@login_required
def empaque_conciliacion():
    """
    Vista previa y aplicación de conciliación (solo actualiza fisico_dynamics,
    nunca modifica movimientos).
    """
    if _empaque_deny_if_not_admin():
        return redirect(url_for('empaque_resumen'))
    if request.method == 'POST':
        file = request.files.get('archivo')
        if not file or not file.filename:
            flash('Selecciona un archivo Excel para conciliación.', 'error')
            return redirect(url_for('empaque_catalogo', seccion='conciliacion'))
        try:
            df = pd.read_excel(file, dtype=str, keep_default_na=False)
        except Exception as exc:
            flash(f'No se pudo leer el archivo: {exc}', 'error')
            return redirect(url_for('empaque_catalogo', seccion='conciliacion'))

        # Soporta dos layouts:
        # 1) Plantilla del sistema: código + físico_dynamics
        # 2) Formato real del usuario: Nombre del producto + Almacén + UM +
        #    Inventario Fisico Actual
        cols = {_empaque_normalizar_clave_importacion(c): c for c in df.columns}
        col_cod = cols.get('codigo') or cols.get('codigo articulo') or cols.get('code')
        col_nombre = cols.get('nombre del producto') or cols.get('nombre') or cols.get('producto')
        col_almacen = cols.get('almacen')
        col_um = cols.get('um')
        col_val = (
            cols.get('fisico dynamics') or
            cols.get('fisico') or
            cols.get('dynamics') or
            cols.get('inventario fisico actual') or
            cols.get('inventario fisico')
        )
        usa_formato_real = bool(col_nombre and col_val)
        if not col_val or (not col_cod and not usa_formato_real):
            flash(
                'El archivo requiere columnas "código" y "físico_dynamics", o el formato '
                'real con "Nombre del producto", "Almacén", "UM" e "Inventario Fisico Actual".',
                'error'
            )
            return redirect(url_for('empaque_catalogo', seccion='conciliacion'))

        articulos_por_nombre = {}
        if usa_formato_real:
            articulos_por_nombre = {
                _empaque_normalizar_nombre_importacion(a.nombre): a
                for a in EmpaqueArticulo.query.all()
            }

        ok, fail = 0, []
        for idx, row in df.iterrows():
            fila_no = idx + 2
            codigo = (row.get(col_cod) or '').strip() if col_cod else ''
            nombre = (row.get(col_nombre) or '').strip() if col_nombre else ''
            almacen = (row.get(col_almacen) or '').strip() if col_almacen else ''
            um = (row.get(col_um) or '').strip() if col_um else ''
            raw = (row.get(col_val) or '').strip()

            art = None
            if codigo:
                art = db.session.get(EmpaqueArticulo, codigo)
            elif usa_formato_real:
                art = articulos_por_nombre.get(_empaque_normalizar_nombre_importacion(nombre))
                if art and almacen and (art.almacen or '').strip().upper() != almacen.strip().upper():
                    fail.append(
                        f'Fila {fila_no}: almacén "{almacen}" no coincide con el artículo '
                        f'"{nombre}" ({art.almacen}).'
                    )
                    continue
                if art and um and (art.um or '').strip() != um.strip():
                    fail.append(
                        f'Fila {fila_no}: UM "{um}" no coincide con el artículo "{nombre}" ({art.um}).'
                    )
                    continue

            if not art:
                if codigo:
                    fail.append(f'Fila {fila_no}: código "{codigo}" no existe.')
                else:
                    fail.append(f'Fila {fila_no}: producto "{nombre}" no existe en el catálogo.')
                continue
            try:
                nuevo = _empaque_parse_decimal_importacion(raw)
            except Exception:
                fail.append(f'Fila {fila_no}: valor "{raw}" no es numérico.')
                continue
            if art.fisico_dynamics != nuevo:
                art.fisico_dynamics = nuevo
                art.actualizado_en = datetime.utcnow()
                ok += 1
        db.session.commit()
        msg = f'Conciliación aplicada: {ok} actualizado(s).'
        if fail:
            msg += f' {len(fail)} fila(s) ignorada(s). Primero: {fail[0]}'
            session['empaque_conciliacion_rechazos'] = fail
        else:
            session.pop('empaque_conciliacion_rechazos', None)
        flash(msg, 'success' if ok else 'info')
    return redirect(url_for('empaque_catalogo', seccion='conciliacion'))


@app.route('/embarques/empaque/ajuste', methods=['POST'])
@login_required
def empaque_registrar_ajuste():
    """
    Registra un ajuste (± cantidad) con motivo obligatorio.
    Única vía de corrección de inventario.
    """
    if _empaque_deny_if_not_admin():
        return redirect(url_for('empaque_resumen'))
    codigo = (request.form.get('codigo') or '').strip()
    cantidad_raw = (request.form.get('cantidad') or '').strip()
    fecha_str = (request.form.get('fecha') or '').strip()
    motivo = (request.form.get('motivo') or '').strip()
    comentario = (request.form.get('comentario') or '').strip() or None

    art = EmpaqueArticulo.query.get(codigo) if codigo else None
    if not art or not art.activo:
        flash('Artículo no válido.', 'error')
        return redirect(url_for('empaque_catalogo', seccion='ajustes'))
    if len(motivo) < 3:
        flash('Motivo obligatorio (al menos 3 caracteres).', 'error')
        return redirect(url_for('empaque_catalogo', seccion='ajustes'))

    ok, cantidad, msg = _validar_cantidad_por_um(cantidad_raw, art.um, allow_negative=True)
    if not ok:
        flash(f'Cantidad: {msg}', 'error')
        return redirect(url_for('empaque_catalogo', seccion='ajustes'))
    if cantidad == 0:
        flash('Cantidad del ajuste no puede ser cero (usa positivo para sumar, negativo para restar).', 'error')
        return redirect(url_for('empaque_catalogo', seccion='ajustes'))

    fecha_aj = _parse_date_or_none(fecha_str) or date.today()
    if fecha_aj > date.today():
        flash('Fecha no puede ser futura.', 'error')
        return redirect(url_for('empaque_catalogo', seccion='ajustes'))

    db.session.add(EmpaqueAjuste(
        codigo=art.codigo,
        cantidad=cantidad,
        fecha=fecha_aj,
        motivo=motivo,
        comentario=comentario,
        id_usuario=current_user.get_id(),
    ))
    db.session.commit()
    signo = '+' if cantidad > 0 else ''
    flash(f'Ajuste registrado: {art.nombre} · {signo}{_format_numero(cantidad, art.um)} {art.um}. Motivo: {motivo}.', 'success')
    return redirect(url_for('empaque_catalogo', seccion='ajustes'))


@app.route('/embarques/empaque/exportar/inventario')
@login_required
def empaque_exportar_inventario():
    """Exporta el inventario actual a Excel."""
    if _empaque_deny_if_not_admin():
        return redirect(url_for('empaque_resumen'))
    articulos = EmpaqueArticulo.query.order_by(EmpaqueArticulo.nombre).all()
    cods = [a.codigo for a in articulos]
    stock_map = _empaque_calcular_stock_batch(cods) if cods else {}
    rows = []
    for a in articulos:
        stock = stock_map.get(a.codigo, 0)
        dyn = a.fisico_dynamics
        dif = (stock - dyn) if dyn is not None else None
        minimo = a.stock_minimo if a.stock_minimo is not None else 0
        _clave, etiq, _color = _empaque_estado_desde_valores(stock, dyn, minimo)
        rows.append({
            'Código': a.codigo,
            'Nombre': a.nombre,
            'Categoría': a.categoria.nombre if a.categoria else '',
            'UM': a.um,
            'Almacén': a.almacen or '',
            'Stock actual': float(stock),
            'Físico Dynamics': (float(dyn) if dyn is not None else ''),
            'Diferencia (interno - Dynamics)': (float(dif) if dif is not None else ''),
            'Stock mínimo': (float(minimo) if minimo else ''),
            'Estado': etiq,
            'Activo': 'Sí' if a.activo else 'No',
        })
    out = io.BytesIO()
    with pd.ExcelWriter(out, engine='openpyxl') as w:
        pd.DataFrame(rows).to_excel(w, index=False, sheet_name='Inventario')
    out.seek(0)
    nombre = f"inventario_empaque_{date.today().isoformat().replace('-', '')}.xlsx"
    return send_file(out, as_attachment=True, download_name=nombre,
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


@app.route('/embarques/empaque/exportar/movimientos')
@login_required
def empaque_exportar_movimientos():
    """Exporta movimientos (entradas/salidas/ajustes) filtrados a Excel."""
    if _empaque_deny_if_not_admin():
        return redirect(url_for('empaque_resumen'))
    q_desde = _parse_date_or_none((request.args.get('desde') or '').strip())
    q_hasta = _parse_date_or_none((request.args.get('hasta') or '').strip())
    q_tipo = (request.args.get('tipo') or 'todos').strip().lower()

    def filtrar_fecha(q, col):
        if q_desde:
            q = q.filter(col >= q_desde)
        if q_hasta:
            q = q.filter(col <= q_hasta)
        return q
    rows = []
    if q_tipo in ('todos', 'entrada'):
        for e in filtrar_fecha(EmpaqueEntrada.query, EmpaqueEntrada.fecha).all():
            rows.append((
                e.fecha or date.min, 0,
                'Entrada', e.codigo, e.articulo.nombre if e.articulo else '',
                float(e.cantidad),
                (e.proveedor.nombre if e.proveedor else ''),
                e.usuario.usuario if e.usuario else '',
                e.comentario or '',
            ))
    if q_tipo in ('todos', 'salida'):
        for s in filtrar_fecha(EmpaqueSalida.query, EmpaqueSalida.fecha).all():
            detalle = (s.area.nombre if s.area else '') + (f' · Lote {s.lote.codigo_lote}' if s.lote else '')
            rows.append((
                s.fecha or date.min, 1,
                'Salida', s.codigo, s.articulo.nombre if s.articulo else '',
                float(s.cantidad),
                detalle,
                s.usuario.usuario if s.usuario else '',
                s.comentario or '',
            ))
    if q_tipo in ('todos', 'ajuste'):
        for a in filtrar_fecha(EmpaqueAjuste.query, EmpaqueAjuste.fecha).all():
            rows.append((
                a.fecha or date.min, 2,
                'Ajuste', a.codigo, a.articulo.nombre if a.articulo else '',
                float(a.cantidad),
                a.motivo or '',
                a.usuario.usuario if a.usuario else '',
                a.comentario or '',
            ))
    rows.sort(key=lambda r: (r[0], r[1]), reverse=True)
    tabla = []
    for _f, _p, tipo, codigo, nombre, cantidad, detalle, usuario, comentario in rows:
        tabla.append({
            'Fecha': _f.isoformat() if _f and _f != date.min else '',
            'Tipo': tipo,
            'Código': codigo,
            'Artículo': nombre,
            'Cantidad': cantidad,
            'Detalle (proveedor/área/lote/motivo)': detalle,
            'Usuario': usuario,
            'Comentario': comentario,
        })
    out = io.BytesIO()
    with pd.ExcelWriter(out, engine='openpyxl') as w:
        pd.DataFrame(tabla).to_excel(w, index=False, sheet_name='Movimientos')
    out.seek(0)
    nombre = f"movimientos_empaque_{date.today().isoformat().replace('-', '')}.xlsx"
    return send_file(out, as_attachment=True, download_name=nombre,
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


# =====================================================================
# ===== FIN RUTAS EMPAQUE =============================================
# =====================================================================

if __name__ == '__main__':
    debug = os.getenv('FLASK_DEBUG', '0').strip() in ('1', 'true', 'TRUE', 'yes', 'YES')
    port = int(os.getenv('PORT', 5000))
    host = os.getenv('HOST', '127.0.0.1')
    from werkzeug.serving import run_simple
    print(f"Iniciando SICSE en http://{host}:{port}/login", flush=True)
    try:
        with app.app_context():
            conn = db.engine.connect()
            conn.close()
    except Exception as ex:
        print("No se pudo conectar a la base de datos.", flush=True)
        print(
            "Revisa que MySQL esté encendido (XAMPP), y que tu .env tenga DATABASE_URL "
            "o DB_USER/DB_PASSWORD/DB_HOST/DB_NAME correctos.",
            flush=True,
        )
        print(f"Detalle: {ex}", flush=True)
        raise
    print("Arrancando servidor (si regresa inmediatamente, algo está deteniendo el proceso)...", flush=True)
    run_simple(
        hostname=host,
        port=port,
        application=app,
        use_reloader=False,
        use_debugger=debug,
        threaded=True,
    )
    print("Servidor detenido.", flush=True)
