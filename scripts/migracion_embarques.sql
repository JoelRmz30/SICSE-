-- ============================================================
-- MIGRACIÓN: MÓDULO DE EMBARQUES SICSE
-- Idempotente: se puede ejecutar múltiples veces sin error.
-- Fecha creación: basada en especificaciones del módulo.
-- ============================================================

USE sistema_silos;

-- ============================================================
-- 1. EXTENSIÓN DE TABLA EXISTENTE: clientes (agregar código)
-- ============================================================
-- Si la columna codigo no existe en clientes, se agrega.
SET @col_exists = (
    SELECT COUNT(*)
    FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'clientes'
      AND COLUMN_NAME = 'codigo'
);
SET @sql = IF(@col_exists = 0,
    'ALTER TABLE clientes ADD COLUMN codigo VARCHAR(20) NULL UNIQUE COMMENT ''Código corto de cliente (Ej: CP002, CP003)''',
    'SELECT ''columna codigo ya existe en clientes'' AS mensaje'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- ============================================================
-- 2. CATÁLOGOS NUEVOS (todos con activo = TRUE por defecto)
-- ============================================================

-- 2.1 productos_embarque
CREATE TABLE IF NOT EXISTS productos_embarque (
    id_producto INT AUTO_INCREMENT PRIMARY KEY,
    item VARCHAR(50) NOT NULL UNIQUE COMMENT 'Código de item único (Ej: PT1701P004)',
    descripcion VARCHAR(255) NOT NULL COMMENT 'Descripción comercial del producto',
    variedad VARCHAR(100) NULL COMMENT 'Variedad del producto (Ej: Valencia, Temple)',
    tipo ENUM('concentrado','pulpa','colateral') NOT NULL COMMENT 'Clasificación del producto',
    unidad_medida ENUM('KG','TAZ') NOT NULL COMMENT 'Unidad de medida para este producto',
    activo BOOLEAN DEFAULT TRUE COMMENT 'Indica si el registro está activo (nunca se borra, solo desactiva)',
    creado_en DATETIME DEFAULT CURRENT_TIMESTAMP,
    actualizado_en DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Catálogo de productos que se embarcan';

-- 2.2 transportistas
CREATE TABLE IF NOT EXISTS transportistas (
    id_transportista INT AUTO_INCREMENT PRIMARY KEY,
    nombre VARCHAR(200) NOT NULL UNIQUE COMMENT 'Nombre de la línea transportista',
    activo BOOLEAN DEFAULT TRUE,
    creado_en DATETIME DEFAULT CURRENT_TIMESTAMP,
    actualizado_en DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Catálogo de líneas transportistas';

-- 2.3 operadores
CREATE TABLE IF NOT EXISTS operadores (
    id_operador INT AUTO_INCREMENT PRIMARY KEY,
    nombre VARCHAR(200) NOT NULL COMMENT 'Nombre completo del operador (en mayúsculas)',
    id_transportista INT NULL COMMENT 'Transportista al que pertenece el operador (puede ser nulo)',
    activo BOOLEAN DEFAULT TRUE,
    creado_en DATETIME DEFAULT CURRENT_TIMESTAMP,
    actualizado_en DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_operadores_transportista FOREIGN KEY (id_transportista)
        REFERENCES transportistas(id_transportista) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Catálogo de operadores / choferes';

-- 2.4 unidades_transporte
CREATE TABLE IF NOT EXISTS unidades_transporte (
    id_unidad INT AUTO_INCREMENT PRIMARY KEY,
    placa VARCHAR(30) NOT NULL UNIQUE COMMENT 'Placa o número económico, guardado en mayúsculas',
    tipo ENUM('tractor','remolque') NOT NULL COMMENT 'Tipo de unidad de transporte',
    activo BOOLEAN DEFAULT TRUE,
    creado_en DATETIME DEFAULT CURRENT_TIMESTAMP,
    actualizado_en DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Catálogo de tractores y remolques';

-- 2.5 lavaderos
CREATE TABLE IF NOT EXISTS lavaderos (
    id_lavadero INT AUTO_INCREMENT PRIMARY KEY,
    nombre VARCHAR(200) NOT NULL UNIQUE COMMENT 'Nombre del lavadero autorizado',
    activo BOOLEAN DEFAULT TRUE,
    creado_en DATETIME DEFAULT CURRENT_TIMESTAMP,
    actualizado_en DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Catálogo de lavaderos para pipas';

-- 2.6 facilitadores
CREATE TABLE IF NOT EXISTS facilitadores (
    id_facilitador INT AUTO_INCREMENT PRIMARY KEY,
    nombre VARCHAR(200) NOT NULL COMMENT 'Nombre del facilitador / agente',
    activo BOOLEAN DEFAULT TRUE,
    creado_en DATETIME DEFAULT CURRENT_TIMESTAMP,
    actualizado_en DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Catálogo de facilitadores';

-- ============================================================
-- 3. TABLA CENTRAL: embarques
-- ============================================================
CREATE TABLE IF NOT EXISTS embarques (
    id_embarque INT AUTO_INCREMENT PRIMARY KEY,
    fecha_embarque DATE NOT NULL COMMENT 'Fecha del embarque (no futura, no anterior a fecha de lote)',
    estatus ENUM('programado','en_planta','cargado','cancelado') NOT NULL DEFAULT 'cargado'
        COMMENT 'Estatus operativo del embarque',
    num_cita VARCHAR(30) NOT NULL UNIQUE COMMENT 'Número de cita. Llave conexión con Dynamics. Formato: 2101-CITA-000000',
    num_orden VARCHAR(30) NOT NULL COMMENT 'Número de orden (OT u OV). Formato: 2101-OT000000 o 2101-OV000000 o 1101-OV000000',
    ticket VARCHAR(30) NULL UNIQUE COMMENT 'Ticket de báscula. Llave conexión con Dynamics. Formato ALA0000000',
    packing VARCHAR(30) NULL UNIQUE COMMENT 'Packing List. Llave conexión con Dynamics. Formato 2101-000000',
    id_producto INT NOT NULL COMMENT 'Producto embarcado (FK a productos_embarque)',
    id_cliente INT NOT NULL COMMENT 'Cliente / destino del embarque',
    tipo_unidad ENUM('pipa_jumbo','pipa_chica','isotanque','flexitanque','caja_refrigerada','caja_seca','trailer','tambores') NOT NULL
        COMMENT 'Tipo de unidad que realiza el embarque. Determina el grupo de detalle.',
    id_transportista INT NULL,
    id_operador INT NULL,
    id_tractor INT NULL COMMENT 'Unidad de tipo tractor',
    id_remolque INT NULL COMMENT 'Unidad de tipo remolque',
    turno TINYINT NOT NULL COMMENT 'Turno de operación: 1, 2 o 3',
    temperatura_c DECIMAL(5,1) NULL COMMENT 'Temperatura de carga en grados Celsius (solo para grupo caja)',
    id_capturista INT NOT NULL COMMENT 'Usuario que capturó el embarque, asignado automáticamente con current_user',
    id_facilitador INT NULL,
    observaciones TEXT NULL COMMENT 'Observaciones libres del embarque',
    creado_en DATETIME DEFAULT CURRENT_TIMESTAMP,
    actualizado_en DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    actualizado_por INT NULL COMMENT 'Usuario que actualizó el registro por última vez',
    CONSTRAINT fk_embarques_producto FOREIGN KEY (id_producto) REFERENCES productos_embarque(id_producto),
    CONSTRAINT fk_embarques_cliente FOREIGN KEY (id_cliente) REFERENCES clientes(id_cliente),
    CONSTRAINT fk_embarques_transportista FOREIGN KEY (id_transportista) REFERENCES transportistas(id_transportista) ON DELETE SET NULL,
    CONSTRAINT fk_embarques_operador FOREIGN KEY (id_operador) REFERENCES operadores(id_operador) ON DELETE SET NULL,
    CONSTRAINT fk_embarques_tractor FOREIGN KEY (id_tractor) REFERENCES unidades_transporte(id_unidad) ON DELETE SET NULL,
    CONSTRAINT fk_embarques_remolque FOREIGN KEY (id_remolque) REFERENCES unidades_transporte(id_unidad) ON DELETE SET NULL,
    CONSTRAINT fk_embarques_capturista FOREIGN KEY (id_capturista) REFERENCES usuarios(id_usuario),
    CONSTRAINT fk_embarques_facilitador FOREIGN KEY (id_facilitador) REFERENCES facilitadores(id_facilitador) ON DELETE SET NULL,
    CONSTRAINT fk_embarques_actualizado_por FOREIGN KEY (actualizado_por) REFERENCES usuarios(id_usuario) ON DELETE SET NULL,
    CONSTRAINT chk_embarques_turno CHECK (turno IN (1, 2, 3))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Tabla central de embarques (captura SICSE, conexión futura con Dynamics)';

-- Índices para acelerar filtros comunes del listado
CREATE INDEX IF NOT EXISTS idx_embarques_fecha ON embarques(fecha_embarque);
CREATE INDEX IF NOT EXISTS idx_embarques_estatus ON embarques(estatus);
CREATE INDEX IF NOT EXISTS idx_embarques_producto ON embarques(id_producto);
CREATE INDEX IF NOT EXISTS idx_embarques_cliente ON embarques(id_cliente);
CREATE INDEX IF NOT EXISTS idx_embarques_tipo_unidad ON embarques(tipo_unidad);

-- ============================================================
-- 4. TABLAS HIJAS
-- ============================================================

-- 4.1 embarque_tiempos (1 a 1 con embarques)
-- Todos los campos son DATETIME y pueden ser NULL mientras el embarque no está completo.
CREATE TABLE IF NOT EXISTS embarque_tiempos (
    id_embarque INT PRIMARY KEY COMMENT 'Llave primaria y foránea a embarques (relación 1 a 1)',
    llegada DATETIME NULL COMMENT 'Fecha y hora de llegada a la planta',
    entrada DATETIME NULL COMMENT 'Fecha y hora de entrada oficial a planta',
    pesado_inicial DATETIME NULL COMMENT 'Fecha y hora de pesaje inicial (bascula)',
    pesaje_salida DATETIME NULL COMMENT 'Fecha y hora de pesaje de salida',
    documentacion DATETIME NULL COMMENT 'Fecha y hora de entrega / liberación de documentación',
    salida DATETIME NULL COMMENT 'Fecha y hora de salida de la planta',
    CONSTRAINT fk_embarque_tiempos_embarque FOREIGN KEY (id_embarque)
        REFERENCES embarques(id_embarque) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Registro de tiempos operativos por embarque (relación 1:1)';

-- 4.2 embarque_detalle (1 a 1 opcional con embarques)
-- Contiene campos específicos según tipo_unidad (grupos pipa, caja, tambor).
CREATE TABLE IF NOT EXISTS embarque_detalle (
    id_embarque INT PRIMARY KEY COMMENT 'Llave primaria y foránea a embarques (relación 1 a 1 opcional)',
    id_lavadero INT NULL COMMENT 'Lavadero (solo aplica para grupo pipa)',
    check_list BOOLEAN NULL COMMENT 'Check list aprobado (solo aplica para pulpa/tambores)',
    lote_tambor VARCHAR(100) NULL COMMENT 'Número de lote de tambor (solo aplica para tambores)',
    CONSTRAINT fk_embarque_detalle_embarque FOREIGN KEY (id_embarque)
        REFERENCES embarques(id_embarque) ON DELETE CASCADE,
    CONSTRAINT fk_embarque_detalle_lavadero FOREIGN KEY (id_lavadero)
        REFERENCES lavaderos(id_lavadero) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Detalle opcional por embarque, campos dependen del tipo_unidad';

-- 4.3 embarque_sellos (1 a N con embarques)
CREATE TABLE IF NOT EXISTS embarque_sellos (
    id_sello INT AUTO_INCREMENT PRIMARY KEY,
    id_embarque INT NOT NULL COMMENT 'Embarque al que pertenece el sello',
    tipo ENUM('lavado','valvula','escotilla','puerta_trasera') NOT NULL
        COMMENT 'Tipo de sello según el grupo de la unidad',
    numero VARCHAR(100) NOT NULL UNIQUE COMMENT 'Número de sello, único en toda la tabla',
    creado_en DATETIME DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_embarque_sellos_embarque FOREIGN KEY (id_embarque)
        REFERENCES embarques(id_embarque) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Sellos colocados en la unidad de transporte';
CREATE INDEX IF NOT EXISTS idx_embarque_sellos_embarque ON embarque_sellos(id_embarque);

-- 4.4 embarque_lotes (N a M entre embarques y lotes, con llave compuesta)
-- La cantidad embarcada del embarque es la SUM(cantidad) de esta tabla.
CREATE TABLE IF NOT EXISTS embarque_lotes (
    id_embarque INT NOT NULL,
    id_lote INT NOT NULL,
    cantidad DECIMAL(12,2) NOT NULL COMMENT 'Cantidad tomada de este lote en la unidad_medida del producto',
    id_movimiento INT NULL COMMENT 'Vínculo opcional con el flujo de salida existente en movimientos',
    PRIMARY KEY (id_embarque, id_lote),
    CONSTRAINT fk_embarque_lotes_embarque FOREIGN KEY (id_embarque)
        REFERENCES embarques(id_embarque) ON DELETE CASCADE,
    CONSTRAINT fk_embarque_lotes_lote FOREIGN KEY (id_lote)
        REFERENCES lotes(id_lote),
    CONSTRAINT fk_embarque_lotes_movimiento FOREIGN KEY (id_movimiento)
        REFERENCES movimientos(id_movimiento) ON DELETE SET NULL,
    CONSTRAINT chk_embarque_lotes_cantidad CHECK (cantidad > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Desglose por lote de la cantidad embarcada';

-- ============================================================
-- 5. PARÁMETROS CONFIGURABLES DEL SISTEMA
-- ============================================================
CREATE TABLE IF NOT EXISTS parametros_sistema (
    clave VARCHAR(100) PRIMARY KEY COMMENT 'Identificador del parámetro',
    valor TEXT NOT NULL COMMENT 'Valor del parámetro (puede ser JSON para rangos)',
    descripcion VARCHAR(255) NOT NULL COMMENT 'Descripción de qué configura este parámetro',
    creado_en DATETIME DEFAULT CURRENT_TIMESTAMP,
    actualizado_en DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Parámetros configurables sin tocar código (rangos de calidad, etc.)';

-- Fin de la migración
SELECT 'Migración módulo embarques aplicada correctamente (idempotente).' AS resultado;
