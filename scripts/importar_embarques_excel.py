"""
Script para importar datos históricos del Excel "REPORTE_DE_FCOJ_Y_PULPA_2025-2026.xlsx"
al módulo de embarques de SICSE.

Reglas (Sección 9 del documento de especificaciones):
  - Modo simulación por defecto (no escribe en la base de datos). Usa --commit para persistir.
  - Genera reporte_importacion.xlsx con 3 hojas: importados, corregidos (con la regla que
    se aplicó y el valor original vs corregido), rechazados (con el motivo del rechazo).
  - Normalización: espacios (strip), mayúsculas en catálogos, unidades "kg" a "KG",
    nombres repetidos con distinta escritura ("JESU ELI MANUEL" ~ "JESUS ELI MANUEL").
  - Corrección fecha DÍA/MES invertidos: se usa evidencia de SEMANA (ISO), MES y FECHA_LOTE
    del lote. Si la evidencia es suficiente, corrige y marca "corregidos"; si no, envía a
    "rechazados". Nunca corrige en silencio sin dejar rastro.
  - Fechas/horas inválidas (31/06/2026, "19:43 PM") → rechazados con motivo.
  - Lotes múltiples en una celda: separados por coma; una fila en embarque_lotes por lote.
    Si no hay reparto de cantidad, se guarda el total en el primer lote y se marca
    "reparto pendiente" en la hoja de corregidos.
  - Sellos: separados por ',', '/', '-' o espacio. Si un valor viene pegado (ej: 302637302638)
    y no se puede separar con certeza, se reporta (no se adivina).
  - Idempotente por `num_cita`: ejecutar el script dos veces NO duplica registros.
  - No importa valores de calidad al embarque. Si un código de lote no existe en la
    tabla `lotes`, se reporta en "rechazados" (no se crea el lote en esta importación).
"""

import argparse
import os
import re
import sys
from datetime import date, datetime, timedelta
from io import BytesIO

import pandas as pd

# --------------------------------------------------------------------------
# Hacer importable el app.py desde la raíz del proyecto.
# --------------------------------------------------------------------------
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from app import (  # noqa: E402 (import después de sys.path)
    db,
    app,
    Lote,
    Cliente,
    ProductoEmbarque,
    Transportista,
    Operador,
    UnidadTransporte,
    Lavadero,
    Facilitador,
    Embarque,
    EmbarqueTiempos,
    EmbarqueDetalle,
    EmbarqueSello,
    EmbarqueLote,
    TIPO_UNIDAD_GRUPO,
)

# ==========================================================================
# Constantes
# ==========================================================================
ARCHIVO_EXCEL_DEFAULT = "REPORTE_DE_FCOJ_Y_PULPA_2025-2026.xlsx"
ARCHIVO_REPORTE_DEFAULT = "reporte_importacion.xlsx"

HOJAS_A_IMPORTAR = [
    "Reporte Pulpa Aseptica",
    "Reporte Emb Concentrado",
    "Embarque tbr concentrado ",  # el nombre termina con espacio
    "Reporte Colaterales",
]

# Mapeo rápido de unidad (label en el Excel) → tipo_unidad del modelo.
TIPO_UNIDAD_MAP = {
    "PIPA JUMBO": "pipa_jumbo",
    "PIPA CHICA": "pipa_chica",
    "ISOTANQUE": "isotanque",
    "FLEXITANQUE": "flexitanque",
    "CAJA REFRIGERADA": "caja_refrigerada",
    "CAJA SECA": "caja_seca",
    "TRAILER": "trailer",
    "TAMBORES": "tambores",
}

# Regex (los mismos del backend, aquí solo para validar y reportar).
RX_NUM_CITA = re.compile(r"^2101-CITA-\d{6}$")
RX_NUM_ORDEN = re.compile(r"^(2101-OT|2101-OV|1101-OV)\d{6}$")
RX_TICKET = re.compile(r"^ALA\d{7}$")
RX_PACKING = re.compile(r"^2101-\d{6}$")
RX_LOTE = re.compile(r"^\d{3}-\d{8}-\d{6}$")

# Nombres de meses (para columnas que traen mes como texto).
MESES_ES = {
    "ENERO": 1, "FEBRERO": 2, "MARZO": 3, "ABRIL": 4, "MAYO": 5, "JUNIO": 6,
    "JULIO": 7, "AGOSTO": 8, "SEPTIEMBRE": 9, "OCTUBRE": 10, "NOVIEMBRE": 11, "DICIEMBRE": 12,
}

# Separadores para sellos.
SEP_SELLOS = re.compile(r"[,\-/\s]+")


# ==========================================================================
# Helpers de normalización y parsing
# ==========================================================================
def strip_up(val, mayusculas=True):
    """
    Recorta espacios de un valor y opcionalmente pasa a mayúsculas.
    Devuelve str vacío si el valor es nulo/NaN.
    """
    if val is None:
        return ""
    try:
        if pd.isna(val):
            return ""
    except Exception:
        pass
    s = str(val).strip()
    if s.lower() in ("nan", "nat", "none"):
        return ""
    if mayusculas:
        s = s.upper()
    return s


def separar_sellos(texto):
    """
    Separa sellos desde una cadena usando ',', '/', '-' o espacio.
    Si detecta una cadena larga pegada (más de 7 caracteres consecutivos sin
    separador) reporta el problema pero devuelve el valor crudo: la decisión
    no se adivina.
    """
    raw = strip_up(texto, mayusculas=True)
    if not raw:
        return [], None
    partes = [p for p in SEP_SELLOS.split(raw) if p]
    # Evitar duplicados en la misma celda
    unicas = list(dict.fromkeys(partes))
    # Detectar casos "pegados" que probablemente son múltiples pero el separador
    # no es claro: por ejemplo "123456123457".
    largo_inusual = [s for s in unicas if len(s) > 7 and s.isdigit()]
    advertencia = None
    if largo_inusual:
        advertencia = (
            "Sellos potencialmente pegados (no se separaron): "
            + ", ".join(largo_inusual)
            + ". Revisar manualmente."
        )
    return unicas, advertencia


def es_fecha_valida(dia, mes, anio):
    """Valida que día/mes/año sea una fecha calendario correcta."""
    try:
        date(anio, mes, dia)
        return True
    except Exception:
        return False


def parsear_fecha_candidata(val):
    """
    Intenta parsear un valor de fecha de Excel, que puede venir:
      - Como objeto datetime de pandas/Excel.
      - Como cadena con dd/mm/aaaa, dd-mm-aaaa, aaaa-mm-dd.
      - Como fecha serial de Excel (no se maneja aquí, pandas lo convierte).
    Devuelve (fecha_objeto, formato_usado) o (None, None) si no se parsea.
    """
    if val is None:
        return None, None
    try:
        if pd.isna(val):
            return None, None
    except Exception:
        pass
    if isinstance(val, datetime):
        return val.date(), "datetime"
    if isinstance(val, date):
        return val, "date"
    s = str(val).strip()
    if not s:
        return None, None
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%y"):
        try:
            return datetime.strptime(s, fmt).date(), fmt
        except Exception:
            continue
    return None, None


def parsear_hora_candidata(val, base_fecha):
    """
    Intenta parsear una hora. Si base_fecha se da, devuelve datetime combinado.
    Valores aceptados: "HH:MM", "HH:MM:SS", "H:MM AM/PM" (descarta PM/AM inválidos).
    Devuelve datetime o None.
    """
    if val is None:
        return None
    try:
        if pd.isna(val):
            return None
    except Exception:
        pass
    # Si ya es un datetime, retornar
    if isinstance(val, datetime):
        return val
    s = str(val).strip().upper()
    if not s:
        return None
    # Quitar AM/PM si vienen
    s_sin = s.replace("AM", "").replace("PM", "").strip()
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            t = datetime.strptime(s_sin, fmt).time()
            if base_fecha:
                return datetime.combine(base_fecha, t)
            return t
        except Exception:
            continue
    # Caso Excel trae timedelta (h00:mm)
    try:
        if "days" in s.lower() or isinstance(val, timedelta):
            td = val if isinstance(val, timedelta) else None
            if td is None:
                return None
            total_seg = int(td.total_seconds())
            h = total_seg // 3600
            m = (total_seg % 3600) // 60
            if h < 24 and m < 60:
                from datetime import time
                t = time(h, m)
                if base_fecha:
                    return datetime.combine(base_fecha, t)
                return t
    except Exception:
        pass
    return None


def semana_iso(fecha_obj):
    """Devuelve número de semana ISO (1-53) para una fecha."""
    if not fecha_obj:
        return None
    if isinstance(fecha_obj, datetime):
        fecha_obj = fecha_obj.date()
    return fecha_obj.isocalendar()[1]


# ==========================================================================
# Normalizadores de catálogos (heurística basada en mayúsculas + strip +
# pequeñas correcciones de nombres frecuentes)
# ==========================================================================
NOMBRES_CORRECCIONES = {
    "JESU ELI MANUEL": "JESUS ELI MANUEL",
    "JESUS  ELI MANUEL": "JESUS ELI MANUEL",
}


def normalizar_nombre(nom):
    """Aplica strip, mayúsculas, y correcciones conocidas."""
    s = strip_up(nom)
    # Quitar espacios duplicados internos
    s = re.sub(r"\s+", " ", s)
    return NOMBRES_CORRECCIONES.get(s, s)


def normalizar_codigo(s):
    """Normaliza un código (cita, orden, ticket, packing, etc.)."""
    return strip_up(s)


# ==========================================================================
# Resolución de catálogos (obtener o crear)
# Nota: el usuario dijo NO inventar datos; estos catálogos son "de listas",
# es decir, se crean automáticamente porque son valores válidos del Excel
# histórico. Se reportan en el reporte para revisión.
# ==========================================================================
def get_or_create_cliente(nombre_cliente, codigo_cliente=None):
    """Devuelve (cliente_obj, creado_bool). Normaliza nombre y código."""
    nom = normalizar_nombre(nombre_cliente)
    cod = normalizar_codigo(codigo_cliente) if codigo_cliente else None
    if not nom:
        return None, False
    if cod:
        c = Cliente.query.filter(Cliente.codigo == cod).first()
        if c:
            return c, False
    # Buscar por nombre exacto
    c = Cliente.query.filter(db.func.upper(Cliente.nombre_cliente) == nom).first()
    if c:
        if cod and not c.codigo:
            c.codigo = cod
            db.session.flush()
        return c, False
    # Crear nuevo
    nuevo = Cliente(nombre_cliente=nom[:120], codigo=cod or None)
    db.session.add(nuevo)
    db.session.flush()
    return nuevo, True


def get_or_create_producto_embarque(descripcion, item=None, variedad=None, tipo=None, unidad=None):
    """Devuelve (producto, creado) a partir de item único o descripción."""
    desc = strip_up(descripcion, mayusculas=False)  # descripción conserva como fue escrito
    item_c = strip_up(item) if item else None
    var_c = strip_up(variedad, mayusculas=False) if variedad else None
    tipo_c = strip_up(tipo) if tipo else None
    unidad_c = strip_up(unidad) if unidad else None
    # Normalizar tipo a ENUM permitido
    if tipo_c:
        if tipo_c.startswith("CONC"):
            tipo_c = "concentrado"
        elif tipo_c.startswith("PULP"):
            tipo_c = "pulpa"
        elif tipo_c.startswith("COLAT") or tipo_c.startswith("COLA"):
            tipo_c = "colateral"
        elif tipo_c not in ("concentrado", "pulpa", "colateral"):
            tipo_c = None
    if unidad_c and unidad_c == "KG":
        unidad_c = "KG"
    if unidad_c not in ("KG", "TAZ"):
        unidad_c = "KG"  # default; las colaterales usan KG/TAZ
    if item_c:
        p = ProductoEmbarque.query.filter_by(item=item_c).first()
        if p:
            return p, False
    # Buscar por descripción
    p = ProductoEmbarque.query.filter(db.func.upper(ProductoEmbarque.descripcion) == desc.upper()).first()
    if p:
        return p, False
    nuevo = ProductoEmbarque(
        item=item_c or None,
        descripcion=desc or "SIN DESCRIPCION",
        variedad=var_c or None,
        tipo=tipo_c or "concentrado",
        unidad_medida=unidad_c,
    )
    db.session.add(nuevo)
    db.session.flush()
    return nuevo, True


def get_or_create_transportista(nombre):
    n = normalizar_nombre(nombre)
    if not n:
        return None, False
    t = Transportista.query.filter(db.func.upper(Transportista.nombre) == n.upper()).first()
    if t:
        return t, False
    t = Transportista(nombre=n[:120])
    db.session.add(t)
    db.session.flush()
    return t, True


def get_or_create_operador(nombre, id_transportista=None):
    n = normalizar_nombre(nombre)
    if not n:
        return None, False
    o = Operador.query.filter(db.func.upper(Operador.nombre) == n.upper()).first()
    if o:
        if id_transportista and not o.id_transportista:
            o.id_transportista = id_transportista
            db.session.flush()
        return o, False
    o = Operador(nombre=n[:120], id_transportista=id_transportista)
    db.session.add(o)
    db.session.flush()
    return o, True


def get_or_create_unidad_transporte(placa, tipo="tractor"):
    p = strip_up(placa)
    if not p:
        return None, False
    if tipo not in ("tractor", "remolque"):
        tipo = "tractor"
    u = UnidadTransporte.query.filter_by(placa=p).first()
    if u:
        if u.tipo != tipo:
            # No se cambia; devolver existente
            pass
        return u, False
    u = UnidadTransporte(placa=p[:20], tipo=tipo)
    db.session.add(u)
    db.session.flush()
    return u, True


def get_or_create_lavadero(nombre):
    n = normalizar_nombre(nombre)
    if not n:
        return None, False
    lv = Lavadero.query.filter(db.func.upper(Lavadero.nombre) == n.upper()).first()
    if lv:
        return lv, False
    lv = Lavadero(nombre=n[:120])
    db.session.add(lv)
    db.session.flush()
    return lv, True


def get_or_create_facilitador(nombre):
    n = normalizar_nombre(nombre)
    if not n:
        return None, False
    f = Facilitador.query.filter(db.func.upper(Facilitador.nombre) == n.upper()).first()
    if f:
        return f, False
    f = Facilitador(nombre=n[:120])
    db.session.add(f)
    db.session.flush()
    return f, True


# ==========================================================================
# Detección de inversión día/mes
# ==========================================================================
def corregir_fecha_con_evidencia(fecha_original, mes_texto, semana_num, fecha_lote_ref, num_fila):
    """
    Intenta detectar si la fecha_original tiene día/mes invertidos.
    Evidencia usada:
      - mes_texto (puede venir como "FEBRERO" o "2")
      - semana_num (semana ISO, int o None)
      - fecha_lote_ref (fecha del lote o None)

    Devuelve:
      (fecha_final, dict_info_correccion_o_None)  →  dict_info sólo si se corrigió.
    """
    if fecha_original is None:
        return None, {"motivo": "Fecha original ausente."}
    # Preparar mes de referencia (int)
    mes_ref = None
    if isinstance(mes_texto, str):
        mt = strip_up(mes_texto)
        if mt in MESES_ES:
            mes_ref = MESES_ES[mt]
        elif mt.isdigit() and 1 <= int(mt) <= 12:
            mes_ref = int(mt)
    elif isinstance(mes_texto, int) and 1 <= mes_texto <= 12:
        mes_ref = mes_texto
    # Preparar semana
    sem_ref = None
    try:
        if semana_num is not None and not pd.isna(semana_num):
            sem_ref = int(float(str(semana_num)))
            if not (1 <= sem_ref <= 53):
                sem_ref = None
    except Exception:
        sem_ref = None

    # Caso 1: fecha original cumple con toda evidencia → no corregir
    evidencias_ok = 0
    evidencias_total = 0
    if mes_ref is not None:
        evidencias_total += 1
        if fecha_original.month == mes_ref:
            evidencias_ok += 1
    if sem_ref is not None:
        evidencias_total += 1
        if semana_iso(fecha_original) == sem_ref:
            evidencias_ok += 1
    if fecha_lote_ref is not None:
        evidencias_total += 1
        if fecha_original >= fecha_lote_ref:
            evidencias_ok += 1

    if evidencias_total > 0 and evidencias_ok == evidencias_total:
        return fecha_original, None
    # Caso 2: probar inversión día <-> mes
    d, m, a = fecha_original.day, fecha_original.month, fecha_original.year
    if d == m:
        # Invertir no cambia nada
        if evidencias_total > 0 and evidencias_ok < evidencias_total:
            return fecha_original, None  # devolver original; problema no resoluble
        return fecha_original, None
    if not es_fecha_valida(m, d, a):
        # La fecha invertida ni siquiera es válida
        return fecha_original, None
    invertida = date(a, m, d)
    # Contar evidencias sobre la invertida
    evidencias_ok_inv = 0
    if mes_ref is not None and invertida.month == mes_ref:
        evidencias_ok_inv += 1
    if sem_ref is not None and semana_iso(invertida) == sem_ref:
        evidencias_ok_inv += 1
    if fecha_lote_ref is not None and invertida >= fecha_lote_ref:
        evidencias_ok_inv += 1

    if evidencias_ok_inv > evidencias_ok and evidencias_ok_inv >= max(1, evidencias_total - 1):
        info = {
            "campo": "fecha_embarque",
            "valor_original": fecha_original.strftime("%d/%m/%Y"),
            "valor_corregido": invertida.strftime("%d/%m/%Y"),
            "regla": (
                f"Inversión día/mes detectada (mes_ref={mes_ref}, sem_ref={sem_ref}, "
                f"lote_ref={fecha_lote_ref.strftime('%d/%m/%Y') if fecha_lote_ref else 'ND'}, "
                f"fila={num_fila})."
            ),
        }
        return invertida, info
    # Si no se puede decidir, marcar problema
    return fecha_original, None


# ==========================================================================
# Construcción de un embarque a partir de una fila del Excel (una hoja)
# ==========================================================================
def procesar_fila(row, hoja, num_fila, catalogos_nuevos, corregidos_acum, rechazados_acum, importados_acum):
    """
    row: pandas Series (fila)
    hoja: str, nombre de la hoja.
    num_fila: int, número de fila (para reporte).

    Esta función NO escribe en DB, construye un dict de datos y devuelve
    (resultado, categoria, info_extra).
    categoria: 'importable', 'rechazado'
    info_extra: dict con reporte.

    IMPORTANTE: Cada hoja tiene columnas distintas. Hacemos un mapeo
    flexible por nombre de columna normalizado.
    """
    # Normalizar nombres de columnas accediendo a row.index
    # Nota: row es un Series con nombres de columna originales.
    def col(*nombres, default=None):
        """Busca el primer valor de la fila para cualquiera de los nombres dados (insensible mayúsculas y espacios)."""
        for n in nombres:
            n_cmp = strip_up(n)
            for col_real in row.index:
                cr = strip_up(col_real)
                if cr == n_cmp:
                    return row[col_real]
        return default

    fecha_raw = col("FECHA", "FECHA EMBARQUE", "FECHA DE EMBARQUE", "EMBARQUE", "F.EMBARQUE", "F. EMBARQUE")
    fecha_embarque, _fmt_fecha = parsear_fecha_candidata(fecha_raw)

    # Columnas Plan
    num_cita_raw = col("NUMERO DE CITA", "NÚMERO DE CITA", "CITA", "NUM. CITA")
    num_cita = normalizar_codigo(num_cita_raw)

    num_orden_raw = col("NUMERO DE ORDEN", "NÚMERO DE ORDEN", "ORDEN", "NUM. ORDEN", "ORDEN DE TRABAJO")
    num_orden = normalizar_codigo(num_orden_raw)

    ticket_raw = col("TICKET", "NUM. TICKET", "NÚMERO DE TICKET")
    ticket = normalizar_codigo(ticket_raw)

    packing_raw = col("PACKING", "PACKING LIST", "NUM. PACKING", "NÚMERO DE PACKING")
    packing = normalizar_codigo(packing_raw)

    turno_raw = col("TURNO")
    turno = None
    if turno_raw is not None:
        try:
            tv = int(float(str(turno_raw).strip()))
            if tv in (1, 2, 3):
                turno = tv
        except Exception:
            pass

    # Producto / cliente / unidad
    prod_desc_raw = col("PRODUCTO", "DESCRIPCION PRODUCTO", "DESCRIPCIÓN PRODUCTO", "PRODUCTO/DESCRIPCION")
    prod_item_raw = col("ITEM", "CÓDIGO PRODUCTO", "CODIGO PRODUCTO", "CVE. PRODUCTO")
    prod_variedad_raw = col("VARIEDAD", "VARIEDADES")
    prod_tipo_hoja = None
    if "PULPA" in hoja.upper():
        prod_tipo_hoja = "pulpa"
    elif "CONCENTRADO" in hoja.upper():
        prod_tipo_hoja = "concentrado"
    elif "COLATERAL" in hoja.upper():
        prod_tipo_hoja = "colateral"
    prod_unidad_raw = col("UNIDAD", "MEDIDA", "U.M.", "UM")
    prod_unidad = strip_up(prod_unidad_raw) or None

    cliente_nom_raw = col("CLIENTES", "CLIENTE", "CLIENTE/DESTINO", "CLIENTE / DESTINO", "DESTINO")
    cliente_cod_raw = col("CODIGO CLIENTE", "CÓDIGO CLIENTE", "COD. CLIENTE", "CP")

    # Tipo unidad
    tipo_unidad_raw = col("TIPO UNIDAD", "TIPO DE UNIDAD", "TIPO DE VEHICULO", "TIPO", "UNIDAD")
    tipo_unidad = None
    tu_txt = strip_up(tipo_unidad_raw)
    if tu_txt:
        # Match contra TIPO_UNIDAD_MAP (key o label conocido)
        for k, v in TIPO_UNIDAD_MAP.items():
            if tu_txt == k or tu_txt == v or (tu_txt in k.replace("_", " ")):
                tipo_unidad = v
                break
        if not tipo_unidad and tu_txt.startswith("PIPA"):
            if "JUMBO" in tu_txt:
                tipo_unidad = "pipa_jumbo"
            elif "CHICA" in tu_txt:
                tipo_unidad = "pipa_chica"
            else:
                tipo_unidad = "pipa_jumbo"
        if not tipo_unidad and "ISOTANQUE" in tu_txt:
            tipo_unidad = "isotanque"
        if not tipo_unidad and "TRAILER" in tu_txt:
            tipo_unidad = "trailer"
        if not tipo_unidad and ("CAJA" in tu_txt or "REFRIGER" in tu_txt):
            if "SECA" in tu_txt:
                tipo_unidad = "caja_seca"
            else:
                tipo_unidad = "caja_refrigerada"
        if not tipo_unidad and "TAMBOR" in tu_txt:
            tipo_unidad = "tambores"

    # Cantidad total (luego desglosada por lotes)
    cantidad_raw = col("PESO (KG)", "CANTIDAD KG", "KG", "PESO", "CANTIDAD", "TAZ")
    cantidad_total = None
    try:
        if cantidad_raw is not None and not (hasattr(cantidad_raw, "__float__") and str(cantidad_raw).lower() == "nan"):
            c = str(cantidad_raw).replace(",", "").strip()
            if c:
                cantidad_total = float(c)
    except Exception:
        cantidad_total = None

    # Lotes (pueden ser múltiples)
    lote_raw = col("LOTE", "LOTES", "NUMERO DE LOTE", "NÚMERO DE LOTE", "NUM. LOTE", "LOTE (S)")
    # Ignorar columna LOTES que es fórmula de numeración (Pulpa). La heurística:
    # si el valor es un número entero simple y NO coincide con RX_LOTE → omitir

    # Transporte y lavadero
    transportista_raw = col("TRANSPORTISTA", "NOMBRE TRANSPORTISTA", "TRASPORTISTA")
    operador_raw = col("OPERADOR", "NOMBRE OPERADOR", "CHOFER", "OPERADOR/CHOFER")
    tractor_raw = col("TRACTOR", "PLACA TRACTOR", "PLACA TRACTE", "PLACA")
    remolque_raw = col("REMOLQUE", "PLACA REMOLQUE", "CONTENEDOR")
    lavadero_raw = col("LAVADERO", "NOMBRE LAVADERO")
    facilitador_raw = col("FACILITADOR")

    temperatura_raw = col("TEMPERATURA", "T (C)", "TEMP (C)", "TEMPERATURA (C)")
    temperatura_c = None
    try:
        if temperatura_raw is not None:
            tv = float(str(temperatura_raw).replace(",", ".").strip())
            temperatura_c = round(tv, 1)
    except Exception:
        pass

    # Sellos por tipo
    sellos_lavado_raw = col("SELLO(S) LAVADO", "SELLOS LAVADO", "SELLO LAVADO")
    sello_valvula_raw = col("SELLO VALVULA", "SELLO VÁLVULA", "VALVULA")
    sellos_escotilla_raw = col("SELLOS ESCOTILLA", "SELLO(S) ESCOTILLA", "ESCOTILLA")
    sellos_puerta_raw = col("SELLOS PUERTA TRASERA", "SELLOS PUERTAS", "SELLOS DE PUERTA", "SELLOS SEGURIDAD")

    # Detalle pulpa/tambor
    check_list_raw = col("CHECK LIST", "CHECKLIST")
    lote_tambor_raw = col("NUMERO DE LOTE DE TAMBOR", "NÚMERO DE LOTE DE TAMBOR", "LOTE TAMBOR")

    # Tiempos
    llegada_d_raw = col("FECHA LLEGADA", "LLEGADA FECHA", "F. LLEGADA")
    llegada_h_raw = col("HORA LLEGADA", "LLEGADA HORA")
    entrada_d_raw = col("FECHA ENTRADA", "F. ENTRADA", "ENTRADA FECHA")
    entrada_h_raw = col("HORA ENTRADA", "ENTRADA HORA")
    pes_ini_d_raw = col("FECHA PESAJE INICIAL", "F. PESO INICIAL", "PESADO INICIAL FECHA")
    pes_ini_h_raw = col("HORA PESAJE INICIAL", "Pesaje Inicial", "PESADO INICIAL HORA")
    pes_sal_d_raw = col("FECHA PESAJE SALIDA", "F. PESO SALIDA", "PESAJE SALIDA FECHA")
    pes_sal_h_raw = col("HORA PESAJE SALIDA", "PESAJE SALIDA", "PESADO SALIDA HORA")
    doc_d_raw = col("FECHA DOCUMENTACION", "F. DOCUMENTO", "F. DOC")
    doc_h_raw = col("HORA DOCUMENTACION", "HORA DOC")
    salida_d_raw = col("FECHA SALIDA", "F. SALIDA", "SALIDA FECHA")
    salida_h_raw = col("HORA SALIDA", "SALIDA HORA")

    # Mes / Semana (para detección inversión)
    mes_raw = col("MES")
    semana_raw = col("SEMANA", "SEMANA ISO", "NUM. SEMANA")

    # ===================== VALIDACIONES =====================
    errores = []

    if not fecha_embarque:
        errores.append("Fecha de embarque no legible.")
    if not num_cita:
        errores.append("Número de cita vacío.")
    elif not RX_NUM_CITA.match(num_cita):
        errores.append(f"Número de cita no cumple formato: '{num_cita}'.")
    if not num_orden:
        errores.append("Número de orden vacío.")
    elif not RX_NUM_ORDEN.match(num_orden):
        errores.append(f"Número de orden no cumple formato: '{num_orden}'.")
    if ticket and not RX_TICKET.match(ticket):
        errores.append(f"Ticket no cumple formato: '{ticket}'.")
    if packing and not RX_PACKING.match(packing):
        errores.append(f"Packing no cumple formato: '{packing}'.")
    if not tipo_unidad:
        errores.append(f"Tipo de unidad no reconocido: '{tu_txt}'.")

    # Procesar lotes
    lote_codigos = []
    lotes_reparto_pendiente = False
    if lote_raw is not None:
        lt = strip_up(lote_raw, mayusculas=False)
        if lt:
            # Separar por coma, punto y coma, ' y '
            partes = re.split(r"[;,]| y |/", lt)
            for p in partes:
                pc = p.strip().upper()
                if not pc:
                    continue
                if pc.isdigit() and len(pc) <= 5:
                    # Es la fórmula de numeración de Pulpa (LOTES), ignorar
                    continue
                if RX_LOTE.match(pc):
                    lote_codigos.append(pc)
                else:
                    # Intentar separar si están pegados (muy raro) → reportar
                    # A veces viene "005-12345678-123456 005-12345678-123457" → espacio es separador
                    for sub in re.split(r"\s+", pc):
                        if RX_LOTE.match(sub):
                            lote_codigos.append(sub)
                        else:
                            errores.append(f"Código de lote inválido: '{sub}'.")
    # Desduplicar
    lote_codigos = list(dict.fromkeys(lote_codigos))
    if not lote_codigos:
        errores.append("Sin códigos de lote válidos.")
    if cantidad_total is None or cantidad_total <= 0:
        errores.append(f"Cantidad embarcno legible o cero: '{cantidad_raw}'.")

    # Validar que cada código de lote existe en la tabla lotes y extraer fecha_lote de ref
    lotes_obj = []
    fecha_lote_ref_global = None
    for lcod in lote_codigos:
        lot = Lote.query.filter_by(codigo_lote=lcod).first()
        if not lot:
            errores.append(f"Lote no existe en tabla lotes: '{lcod}'.")
            continue
        lotes_obj.append(lot)
        if lot.fecha_lote and (fecha_lote_ref_global is None or lot.fecha_lote < fecha_lote_ref_global):
            fecha_lote_ref_global = lot.fecha_lote

    # Validaciones de fecha futura / anterior a lote
    if fecha_embarque and fecha_embarque > date.today():
        errores.append(f"Fecha futura: {fecha_embarque.strftime('%d/%m/%Y')}.")
    if fecha_embarque and fecha_lote_ref_global and fecha_embarque < fecha_lote_ref_global:
        # Intentar corregir con evidencia
        pass  # lo manejamos abajo con la detección inversión

    # Detección inversión día/mes
    correcciones = []
    fecha_final = fecha_embarque
    if fecha_embarque:
        fecha_corregida, info_corr = corregir_fecha_con_evidencia(
            fecha_embarque, mes_raw, semana_raw, fecha_lote_ref_global, num_fila
        )
        if info_corr:
            correcciones.append(info_corr)
            fecha_final = fecha_corregida
        # Validar fecha final >= fecha lote (si aún no es así → rechazar)
        if fecha_final and fecha_lote_ref_global and fecha_final < fecha_lote_ref_global:
            errores.append(
                "Fecha embarque ("
                + fecha_final.strftime("%d/%m/%Y")
                + ") anterior a la fecha del lote más viejo ("
                + fecha_lote_ref_global.strftime("%d/%m/%Y")
                + ")."
            )

    # Si hay errores → rechazado
    if errores:
        info_r = {
            "hoja": hoja,
            "fila": num_fila,
            "num_cita": num_cita or "",
            "num_orden": num_orden or "",
            "motivo": " | ".join(errores),
            "fecha_candidata": str(fecha_raw),
        }
        rechazados_acum.append(info_r)
        return None, "rechazado", info_r

    # Preparar reparto de cantidades entre lotes
    if cantidad_total and len(lote_codigos) > 1:
        # Si no hay info del reparto, se va todo al primero y marca pendiente
        lotes_reparto_pendiente = True
        correcciones.append({
            "campo": "embarque_lotes.cantidad",
            "valor_original": f"{len(lote_codigos)} lotes, sin reparto",
            "valor_corregido": (
                f"Total ({cantidad_total:,.2f}) guardado en el primer lote "
                f"({lote_codigos[0]})."
            ),
            "regla": "Múltiples lotes en celda sin reparto. Reparto pendiente.",
        })

    # Parsear tiempos (combinar fecha de embarque como base si la fecha de tiempo no está)
    def combinar_fecha_hora(f_raw, h_raw, base_f):
        f = parsear_fecha_candidata(f_raw)[0] or base_f
        if not f:
            return None
        dt = parsear_hora_candidata(h_raw, f)
        if dt:
            return dt
        # Si la hora es nula pero la fecha existe, dejar None (no inventar)
        return None

    tiempos = {}
    t_llegada = combinar_fecha_hora(llegada_d_raw, llegada_h_raw, fecha_final)
    t_entrada = combinar_fecha_hora(entrada_d_raw, entrada_h_raw, fecha_final)
    t_pesado_ini = combinar_fecha_hora(pes_ini_d_raw, pes_ini_h_raw, fecha_final)
    t_pesaje_sal = combinar_fecha_hora(pes_sal_d_raw, pes_sal_h_raw, fecha_final)
    t_doc = combinar_fecha_hora(doc_d_raw, doc_h_raw, fecha_final)
    t_salida = combinar_fecha_hora(salida_d_raw, salida_h_raw, fecha_final)
    tiempos["llegada"] = t_llegada
    tiempos["entrada"] = t_entrada
    tiempos["pesado_inicial"] = t_pesado_ini
    tiempos["pesaje_salida"] = t_pesaje_sal
    tiempos["documentacion"] = t_doc
    tiempos["salida"] = t_salida

    # Validar orden de tiempos si todos existen
    tiempos_lista = [
        ("llegada", t_llegada), ("entrada", t_entrada), ("pesado_inicial", t_pesado_ini),
        ("pesaje_salida", t_pesaje_sal), ("documentacion", t_doc), ("salida", t_salida),
    ]
    valores_dt = [v for _, v in tiempos_lista if v is not None]
    if len(valores_dt) == len(tiempos_lista):
        for i in range(1, len(valores_dt)):
            if valores_dt[i] < valores_dt[i - 1]:
                errores.append(
                    f"Tiempos en desorden: {tiempos_lista[i-1][0]}={valores_dt[i-1]} > "
                    f"{tiempos_lista[i][0]}={valores_dt[i]}"
                )

    # Preparar sellos y advertencia de pegados
    advertencias = []
    sl, adv = separar_sellos(sellos_lavado_raw)
    if adv:
        advertencias.append(adv)
    sv_raw = strip_up(sello_valvula_raw)
    sv = [sv_raw] if sv_raw else []
    if sv_raw and len(sv_raw) > 7 and sv_raw.isdigit():
        advertencias.append(f"Sello válvula potencialmente inválido/pegado: {sv_raw}")
    se, adv2 = separar_sellos(sellos_escotilla_raw)
    if adv2:
        advertencias.append(adv2)
    sp, adv3 = separar_sellos(sellos_puerta_raw)
    if adv3:
        advertencias.append(adv3)
    # Desduplicación global de sellos
    todos_sellos_numeros = []
    for sn in sl:
        todos_sellos_numeros.append(("lavado", sn))
    for sn in sv:
        todos_sellos_numeros.append(("valvula", sn))
    for sn in se:
        todos_sellos_numeros.append(("escotilla", sn))
    for sn in sp:
        todos_sellos_numeros.append(("puerta_trasera", sn))

    # Validar unicidad de sellos dentro de la fila (duplicados)
    vistos = {}
    for tipo_s, num_s in todos_sellos_numeros:
        if num_s in vistos:
            errores.append(f"Sello duplicado dentro de fila: {num_s} ({vistos[num_s]} y {tipo_s}).")
        vistos[num_s] = tipo_s

    if errores:
        info_r = {
            "hoja": hoja,
            "fila": num_fila,
            "num_cita": num_cita or "",
            "num_orden": num_orden or "",
            "motivo": " | ".join(errores),
        }
        rechazados_acum.append(info_r)
        return None, "rechazado", info_r

    # Construir objeto "embarque" en memoria (dict)
    embarque_datos = {
        "fecha_embarque": fecha_final,
        "num_cita": num_cita,
        "num_orden": num_orden,
        "ticket": ticket or None,
        "packing": packing or None,
        "turno": turno or 1,
        "tipo_unidad": tipo_unidad,
        "temperatura_c": temperatura_c,
        "observaciones": (
            ("Importación histórica. Advertencias: " + " | ".join(advertencias))
            if advertencias else "Importación histórica."
        ),
        "producto": {
            "descripcion": prod_desc_raw or "Sin nombre",
            "item": prod_item_raw or None,
            "variedad": prod_variedad_raw or None,
            "tipo": prod_tipo_hoja,
            "unidad": prod_unidad,
        },
        "cliente": {
            "nombre": cliente_nom_raw or ("Cliente sin nombre " + num_cita),
            "codigo": cliente_cod_raw or None,
        },
        "transportista": transportista_raw,
        "operador": operador_raw,
        "tractor": tractor_raw,
        "remolque": remolque_raw,
        "lavadero": lavadero_raw,
        "facilitador": facilitador_raw,
        "detalle_check_list": bool(check_list_raw and str(check_list_raw).strip().lower()
                                    not in ("", "0", "no", "nan", "false")),
        "detalle_lote_tambor": strip_up(lote_tambor_raw) or None,
        "tiempos": tiempos,
        "sellos": todos_sellos_numeros,  # lista (tipo, numero)
        "lotes_codigos": lote_codigos,
        "cantidad_total": cantidad_total,
        "lotes_reparto_pendiente": lotes_reparto_pendiente,
    }

    info_corregidos_esta_fila = [
        {
            "hoja": hoja,
            "fila": num_fila,
            "num_cita": num_cita,
            "campo": c["campo"],
            "valor_original": c["valor_original"],
            "valor_corregido": c["valor_corregido"],
            "regla": c["regla"],
        }
        for c in correcciones
    ]
    if lotes_reparto_pendiente:
        # Regla especial: marcar en importados (no se pierde)
        pass
    corregidos_acum.extend(info_corregidos_esta_fila)

    return embarque_datos, "importable", {"correcciones": len(correcciones)}


# ==========================================================================
# Persistir un embarque en la base de datos (sólo si --commit)
# ==========================================================================
def persistir_embarque(data):
    """
    Persiste en la BD el diccionario `data` devuelto por procesar_fila.
    Idempotente por num_cita.
    Devuelve (embarque_obj, creado_bool) o (None, False) si ya existía.
    """
    nc = data["num_cita"]
    ex = Embarque.query.filter_by(num_cita=nc).first()
    if ex:
        return ex, False

    # Resolver catálogos
    prod, _ = get_or_create_producto_embarque(
        data["producto"]["descripcion"],
        data["producto"]["item"],
        data["producto"]["variedad"],
        data["producto"]["tipo"],
        data["producto"]["unidad"],
    )
    cli, _ = get_or_create_cliente(
        data["cliente"]["nombre"],
        data["cliente"]["codigo"],
    )
    t = None
    if data["transportista"]:
        t, _ = get_or_create_transportista(data["transportista"])
    op = None
    if data["operador"]:
        op, _ = get_or_create_operador(data["operador"], t.id_transportista if t else None)
    tr = None
    if data["tractor"]:
        tr, _ = get_or_create_unidad_transporte(data["tractor"], "tractor")
    re = None
    if data["remolque"]:
        re, _ = get_or_create_unidad_transporte(data["remolque"], "remolque")
    lv = None
    if data["lavadero"]:
        lv, _ = get_or_create_lavadero(data["lavadero"])
    fc = None
    if data["facilitador"]:
        fc, _ = get_or_create_facilitador(data["facilitador"])

    # Determinar estatus según tiempos completos
    completos = all(data["tiempos"].values())
    estatus = "cargado" if completos else "en_planta"

    emb = Embarque(
        fecha_embarque=data["fecha_embarque"],
        estatus=estatus,
        num_cita=nc,
        num_orden=data["num_orden"],
        ticket=data["ticket"],
        packing=data["packing"],
        id_producto=prod.id_producto if prod else None,
        id_cliente=cli.id_cliente if cli else None,
        tipo_unidad=data["tipo_unidad"],
        id_transportista=t.id_transportista if t else None,
        id_operador=op.id_operador if op else None,
        id_tractor=tr.id_unidad if tr else None,
        id_remolque=re.id_unidad if re else None,
        turno=data["turno"] or 1,
        temperatura_c=data["temperatura_c"],
        id_capturista=None,  # None por ser importación histórica (sin sesión)
        id_facilitador=fc.id_facilitador if fc else None,
        observaciones=data["observaciones"],
        actualizado_por=None,
    )
    db.session.add(emb)
    db.session.flush()

    # Tiempos 1:1
    tiempos_obj = EmbarqueTiempos(
        id_embarque=emb.id_embarque,
        llegada=data["tiempos"]["llegada"],
        entrada=data["tiempos"]["entrada"],
        pesado_inicial=data["tiempos"]["pesado_inicial"],
        pesaje_salida=data["tiempos"]["pesaje_salida"],
        documentacion=data["tiempos"]["documentacion"],
        salida=data["tiempos"]["salida"],
    )
    db.session.add(tiempos_obj)

    # Detalle 1:1 opcional
    detalle_necesario = (
        lv is not None
        or data["detalle_check_list"] is True
        or bool(data["detalle_lote_tambor"])
    )
    if detalle_necesario:
        det_obj = EmbarqueDetalle(
            id_embarque=emb.id_embarque,
            id_lavadero=lv.id_lavadero if lv else None,
            check_list=data["detalle_check_list"] or False,
            lote_tambor=data["detalle_lote_tambor"],
        )
        db.session.add(det_obj)

    # Sellos
    for tipo_s, num_s in data["sellos"]:
        s = EmbarqueSello(id_embarque=emb.id_embarque, tipo=tipo_s, numero=num_s)
        db.session.add(s)

    # Lotes (asignar cantidad)
    cods = data["lotes_codigos"]
    if cods:
        # Resolver objetos lotes (deberían existir porque se validó antes)
        lot_objs = Lote.query.filter(Lote.codigo_lote.in_(cods)).all()
        cod_to_lote = {l.codigo_lote: l for l in lot_objs}
        for idx, lc in enumerate(cods):
            lot = cod_to_lote.get(lc)
            if not lot:
                continue
            if idx == 0:
                ctd = data["cantidad_total"]
            else:
                ctd = 0.0 if data["lotes_reparto_pendiente"] else 0.0
            el = EmbarqueLote(
                id_embarque=emb.id_embarque,
                id_lote=lot.id_lote,
                cantidad=ctd,
            )
            db.session.add(el)

    return emb, True


# ==========================================================================
# Main
# ==========================================================================
def main():
    parser = argparse.ArgumentParser(
        description="Importa datos históricos del Excel de embarques a SICSE.",
    )
    parser.add_argument(
        "--input",
        default=ARCHIVO_EXCEL_DEFAULT,
        help=f"Ruta al archivo Excel origen (default: {ARCHIVO_EXCEL_DEFAULT}).",
    )
    parser.add_argument(
        "--output",
        default=ARCHIVO_REPORTE_DEFAULT,
        help=f"Ruta del reporte XLSX resultante (default: {ARCHIVO_REPORTE_DEFAULT}).",
    )
    parser.add_argument(
        "--commit",
        action="store_true",
        default=False,
        help="Si se indica, escribe en la base de datos (default: simulación).",
    )
    args = parser.parse_args()

    print(f"[INFO] Modo: {'PERSISTIR (commit)' if args.commit else 'SIMULACIÓN (sin commit)'}")
    print(f"[INFO] Input : {args.input}")
    print(f"[INFO] Output: {args.output}")

    if not os.path.isfile(args.input):
        print(f"[ERROR] No existe el archivo Excel: {args.input}")
        sys.exit(1)

    # Listas de reporte
    importados_rep = []
    corregidos_rep = []
    rechazados_rep = []

    total_candidatos = 0
    total_importados_db = 0
    total_ya_existian = 0

    # Entrar al contexto de la app Flask para usar SQLAlchemy.
    with app.app_context():
        # Precachear lotes para búsquedas rápidas.
        print("[INFO] Precargando lotes existentes en memoria...")
        _precache = Lote.query.all()  # noqa: F841

        for hoja in HOJAS_A_IMPORTAR:
            print(f"[INFO] Procesando hoja: '{hoja}'")
            try:
                # header=1 → los encabezados están en la fila 2 del Excel.
                df = pd.read_excel(args.input, sheet_name=hoja, header=1)
            except Exception as e:
                print(f"  [WARN] No se pudo leer hoja '{hoja}': {e}")
                continue

            # Quitar filas totalmente vacías
            df = df.dropna(how="all")
            # Resetear índice para que num_fila sea relativo al Excel real
            for idx_0, (_idx_df, row) in enumerate(df.iterrows(), start=0):
                num_fila_excel = 3 + idx_0  # 1=header1, 2=header2, 3=primera fila datos
                total_candidatos += 1
                embarque_datos, categoria, _info = procesar_fila(
                    row, hoja, num_fila_excel,
                    None,  # catalogos_nuevos (acum en corregidos no se usa param)
                    corregidos_rep, rechazados_rep, importados_rep,
                )
                if categoria == "importable" and embarque_datos is not None:
                    # Añadir a importados_rep (incluso en simulación)
                    importados_rep.append({
                        "hoja": hoja,
                        "fila_excel": num_fila_excel,
                        "fecha_embarque": embarque_datos["fecha_embarque"].strftime("%d/%m/%Y"),
                        "num_cita": embarque_datos["num_cita"],
                        "num_orden": embarque_datos["num_orden"],
                        "ticket": embarque_datos["ticket"] or "",
                        "packing": embarque_datos["packing"] or "",
                        "cliente": embarque_datos["cliente"]["nombre"],
                        "producto": embarque_datos["producto"]["descripcion"],
                        "tipo_unidad": embarque_datos["tipo_unidad"],
                        "lotes": "; ".join(embarque_datos["lotes_codigos"]),
                        "cantidad_total": f"{embarque_datos['cantidad_total']:.2f}",
                        "reparto_pendiente": "SÍ" if embarque_datos["lotes_reparto_pendiente"] else "NO",
                    })
                    if args.commit:
                        try:
                            emb_obj, creado = persistir_embarque(embarque_datos)
                            if creado:
                                total_importados_db += 1
                                db.session.commit()
                            else:
                                total_ya_existian += 1
                                db.session.rollback()
                        except Exception as ex:
                            db.session.rollback()
                            msg_bd = str(ex)
                            if "Duplicate entry" in msg_bd:
                                if "num_cita" in msg_bd:
                                    msg_bd = "Cita duplicada (ya existe)."
                                elif "ticket" in msg_bd:
                                    msg_bd = "Ticket duplicado (ya existe)."
                                elif "packing" in msg_bd:
                                    msg_bd = "Packing duplicado (ya existe)."
                                elif "numero" in msg_bd.lower() or "sello" in msg_bd.lower():
                                    msg_bd = "Número de sello duplicado."
                            rechazados_rep.append({
                                "hoja": hoja,
                                "fila": num_fila_excel,
                                "num_cita": embarque_datos["num_cita"],
                                "num_orden": embarque_datos["num_orden"],
                                "motivo": f"Error BD: {msg_bd}",
                            })

    # Escribir reporte
    print(f"[INFO] Escribiendo reporte: {args.output}")
    with pd.ExcelWriter(args.output, engine="openpyxl") as wr:
        pd.DataFrame(importados_rep).to_excel(wr, index=False, sheet_name="importados")
        pd.DataFrame(corregidos_rep).to_excel(wr, index=False, sheet_name="corregidos")
        pd.DataFrame(rechazados_rep).to_excel(wr, index=False, sheet_name="rechazados")

    print("=" * 60)
    print(f"Candidatos totales leídos        : {total_candidatos}")
    print(f"Filas importables en reporte      : {len(importados_rep)}")
    print(f"Filas con correcciones reportadas : {len(corregidos_rep)}")
    print(f"Filas rechazadas                  : {len(rechazados_rep)}")
    if args.commit:
        print(f"Embarques insertados nuevos       : {total_importados_db}")
        print(f"Embarques ya existentes (skip)    : {total_ya_existian}")
    print("=" * 60)
    print("[OK] Importación finalizada.")


if __name__ == "__main__":
    main()
