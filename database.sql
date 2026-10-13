-- Crear base de datos
CREATE DATABASE IF NOT EXISTS sistema_silos;
USE sistema_silos;

-- Tabla: usuarios
CREATE TABLE IF NOT EXISTS usuarios ( 
    id_usuario INT AUTO_INCREMENT PRIMARY KEY, 
    nombre VARCHAR(100), 
    usuario VARCHAR(50) UNIQUE, 
    password VARCHAR(255), 
    rol ENUM('administrador','capturista','invitado'), 
    activo BOOLEAN DEFAULT TRUE 
); 

-- Tabla: silos
CREATE TABLE IF NOT EXISTS silos ( 
    id_silo INT AUTO_INCREMENT PRIMARY KEY, 
    nombre_silo VARCHAR(20), 
    capacidad_gal DECIMAL(10,2), 
    capacidad_barriles DECIMAL(10,2), 
    tipo_producto VARCHAR(30), 
    tipo_permitido VARCHAR(30), 
    estado ENUM('activo','inactivo') DEFAULT 'activo' 
); 

-- Tabla: estados_producto
CREATE TABLE IF NOT EXISTS estados_producto ( 
    id_estado INT AUTO_INCREMENT PRIMARY KEY, 
    nombre_estado VARCHAR(50) 
); 

-- Tabla: clientes
CREATE TABLE IF NOT EXISTS clientes ( 
    id_cliente INT AUTO_INCREMENT PRIMARY KEY, 
    nombre_cliente VARCHAR(100),
    codigo VARCHAR(20) NULL UNIQUE COMMENT 'Código corto de cliente (Ej: CP002, CP003)'
); 

-- Tabla: lotes
CREATE TABLE IF NOT EXISTS lotes ( 
    id_lote INT AUTO_INCREMENT PRIMARY KEY, 
    codigo_lote VARCHAR(50) UNIQUE, 
    fecha_lote DATE, 
    brix DECIMAL(5,2), 
    relacion DECIMAL(5,2), 
    pulpa DECIMAL(5,2), 
    id_estado INT, 
    id_cliente INT, 
    FOREIGN KEY (id_estado) REFERENCES estados_producto(id_estado), 
    FOREIGN KEY (id_cliente) REFERENCES clientes(id_cliente) 
); 

-- Tabla: inventario_silos
CREATE TABLE IF NOT EXISTS inventario_silos ( 
    id_inventario INT AUTO_INCREMENT PRIMARY KEY, 
    id_silo INT, 
    id_lote INT, 
    posicion INT, 
    galones DECIMAL(10,2), 
    fecha_registro DATETIME, 
    FOREIGN KEY (id_silo) REFERENCES silos(id_silo), 
    FOREIGN KEY (id_lote) REFERENCES lotes(id_lote) 
); 

-- Tabla: movimientos
CREATE TABLE IF NOT EXISTS movimientos ( 
    id_movimiento INT AUTO_INCREMENT PRIMARY KEY, 
    tipo_movimiento ENUM('entrada','salida','ajuste','reproceso','cambio_estado'), 
    id_silo INT, 
    id_lote INT, 
    galones DECIMAL(10,2), 
    fecha_movimiento DATETIME, 
    id_usuario INT, 
    observaciones TEXT, 
    FOREIGN KEY (id_silo) REFERENCES silos(id_silo), 
    FOREIGN KEY (id_lote) REFERENCES lotes(id_lote), 
    FOREIGN KEY (id_usuario) REFERENCES usuarios(id_usuario) 
); 

-- Insertar valores iniciales para estados_producto
INSERT IGNORE INTO estados_producto (nombre_estado) VALUES 
('Liberado'), 
('Pendiente Micro'), 
('Reproceso'), 
('No apto'), 
('N Temprana Liberado');

-- Insertar clientes de ejemplo
-- INSERT IGNORE INTO clientes (nombre_cliente) VALUES 
-- ('Peace River'), 
-- ('Paso Largo');

-- Insertar usuario administrador por defecto (password: admin123)
-- Nota: En producción el password debe estar hasheado.
INSERT IGNORE INTO usuarios (nombre, usuario, password, rol) VALUES 
('Administrador Sistema', 'admin', 'scrypt:32768:8:1$uH3kK8k7uH3kK8k7$5f7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e', 'administrador');

-- ============================================================
-- MÓDULO EMBARQUES: CATÁLOGOS
-- ============================================================

-- Catálogo: productos_embarque
CREATE TABLE IF NOT EXISTS productos_embarque (
    id_producto INT AUTO_INCREMENT PRIMARY KEY,
    item VARCHAR(50) NOT NULL UNIQUE,
    descripcion VARCHAR(255) NOT NULL,
    variedad VARCHAR(100) NULL,
    tipo ENUM('concentrado','pulpa','colateral') NOT NULL,
    unidad_medida ENUM('KG','TAZ') NOT NULL,
    activo BOOLEAN DEFAULT TRUE,
    creado_en DATETIME DEFAULT CURRENT_TIMESTAMP,
    actualizado_en DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Catálogo: transportistas
CREATE TABLE IF NOT EXISTS transportistas (
    id_transportista INT AUTO_INCREMENT PRIMARY KEY,
    nombre VARCHAR(200) NOT NULL UNIQUE,
    activo BOOLEAN DEFAULT TRUE,
    creado_en DATETIME DEFAULT CURRENT_TIMESTAMP,
    actualizado_en DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Catálogo: operadores
CREATE TABLE IF NOT EXISTS operadores (
    id_operador INT AUTO_INCREMENT PRIMARY KEY,
    nombre VARCHAR(200) NOT NULL,
    id_transportista INT NULL,
    activo BOOLEAN DEFAULT TRUE,
    creado_en DATETIME DEFAULT CURRENT_TIMESTAMP,
    actualizado_en DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_operadores_transportista FOREIGN KEY (id_transportista)
        REFERENCES transportistas(id_transportista) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Catálogo: unidades_transporte
CREATE TABLE IF NOT EXISTS unidades_transporte (
    id_unidad INT AUTO_INCREMENT PRIMARY KEY,
    placa VARCHAR(30) NOT NULL UNIQUE,
    tipo ENUM('tractor','remolque') NOT NULL,
    activo BOOLEAN DEFAULT TRUE,
    creado_en DATETIME DEFAULT CURRENT_TIMESTAMP,
    actualizado_en DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Catálogo: lavaderos
CREATE TABLE IF NOT EXISTS lavaderos (
    id_lavadero INT AUTO_INCREMENT PRIMARY KEY,
    nombre VARCHAR(200) NOT NULL UNIQUE,
    activo BOOLEAN DEFAULT TRUE,
    creado_en DATETIME DEFAULT CURRENT_TIMESTAMP,
    actualizado_en DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Catálogo: facilitadores
CREATE TABLE IF NOT EXISTS facilitadores (
    id_facilitador INT AUTO_INCREMENT PRIMARY KEY,
    nombre VARCHAR(200) NOT NULL,
    activo BOOLEAN DEFAULT TRUE,
    creado_en DATETIME DEFAULT CURRENT_TIMESTAMP,
    actualizado_en DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ============================================================
-- MÓDULO EMBARQUES: TABLA CENTRAL
-- ============================================================
CREATE TABLE IF NOT EXISTS embarques (
    id_embarque INT AUTO_INCREMENT PRIMARY KEY,
    fecha_embarque DATE NOT NULL,
    estatus ENUM('programado','en_planta','cargado','cancelado') NOT NULL DEFAULT 'cargado',
    num_cita VARCHAR(30) NOT NULL UNIQUE,
    num_orden VARCHAR(30) NOT NULL,
    ticket VARCHAR(30) NULL UNIQUE,
    packing VARCHAR(30) NULL UNIQUE,
    id_producto INT NULL,
    id_cliente INT NULL,
    producto_texto VARCHAR(200) NULL,
    cliente_texto VARCHAR(200) NULL,
    tipo_unidad ENUM('pipa_jumbo','pipa_chica','isotanque','flexitanque','caja_refrigerada','caja_seca','trailer','tambores') NOT NULL,
    id_transportista INT NULL,
    id_operador INT NULL,
    id_tractor INT NULL,
    id_remolque INT NULL,
    turno TINYINT NOT NULL,
    temperatura_c DECIMAL(5,1) NULL,
    id_capturista INT NOT NULL,
    id_facilitador INT NULL,
    observaciones TEXT NULL,
    creado_en DATETIME DEFAULT CURRENT_TIMESTAMP,
    actualizado_en DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    actualizado_por INT NULL,
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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE INDEX IF NOT EXISTS idx_embarques_fecha ON embarques(fecha_embarque);
CREATE INDEX IF NOT EXISTS idx_embarques_estatus ON embarques(estatus);
CREATE INDEX IF NOT EXISTS idx_embarques_producto ON embarques(id_producto);
CREATE INDEX IF NOT EXISTS idx_embarques_cliente ON embarques(id_cliente);
CREATE INDEX IF NOT EXISTS idx_embarques_tipo_unidad ON embarques(tipo_unidad);

-- ============================================================
-- MÓDULO EMBARQUES: TABLAS HIJAS
-- ============================================================

-- embarque_tiempos (1 a 1)
CREATE TABLE IF NOT EXISTS embarque_tiempos (
    id_embarque INT PRIMARY KEY,
    llegada DATETIME NULL,
    entrada DATETIME NULL,
    pesado_inicial DATETIME NULL,
    pesaje_salida DATETIME NULL,
    documentacion DATETIME NULL,
    salida DATETIME NULL,
    CONSTRAINT fk_embarque_tiempos_embarque FOREIGN KEY (id_embarque)
        REFERENCES embarques(id_embarque) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- embarque_detalle (1 a 1 opcional)
CREATE TABLE IF NOT EXISTS embarque_detalle (
    id_embarque INT PRIMARY KEY,
    id_lavadero INT NULL,
    check_list BOOLEAN NULL,
    lote_tambor VARCHAR(100) NULL,
    CONSTRAINT fk_embarque_detalle_embarque FOREIGN KEY (id_embarque)
        REFERENCES embarques(id_embarque) ON DELETE CASCADE,
    CONSTRAINT fk_embarque_detalle_lavadero FOREIGN KEY (id_lavadero)
        REFERENCES lavaderos(id_lavadero) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- embarque_sellos (1 a N)
CREATE TABLE IF NOT EXISTS embarque_sellos (
    id_sello INT AUTO_INCREMENT PRIMARY KEY,
    id_embarque INT NOT NULL,
    tipo ENUM('lavado','valvula','escotilla','puerta_trasera') NOT NULL,
    numero VARCHAR(100) NOT NULL UNIQUE,
    creado_en DATETIME DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_embarque_sellos_embarque FOREIGN KEY (id_embarque)
        REFERENCES embarques(id_embarque) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE INDEX IF NOT EXISTS idx_embarque_sellos_embarque ON embarque_sellos(id_embarque);

-- embarque_lotes (llave compuesta N:M)
CREATE TABLE IF NOT EXISTS embarque_lotes (
    id_embarque INT NOT NULL,
    id_lote INT NOT NULL,
    cantidad DECIMAL(12,2) NOT NULL,
    id_movimiento INT NULL,
    PRIMARY KEY (id_embarque, id_lote),
    CONSTRAINT fk_embarque_lotes_embarque FOREIGN KEY (id_embarque)
        REFERENCES embarques(id_embarque) ON DELETE CASCADE,
    CONSTRAINT fk_embarque_lotes_lote FOREIGN KEY (id_lote)
        REFERENCES lotes(id_lote),
    CONSTRAINT fk_embarque_lotes_movimiento FOREIGN KEY (id_movimiento)
        REFERENCES movimientos(id_movimiento) ON DELETE SET NULL,
    CONSTRAINT chk_embarque_lotes_cantidad CHECK (cantidad > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ============================================================
-- MÓDULO EMBARQUES: PARÁMETROS CONFIGURABLES
-- ============================================================
CREATE TABLE IF NOT EXISTS parametros_sistema (
    clave VARCHAR(100) PRIMARY KEY,
    valor TEXT NOT NULL,
    descripcion VARCHAR(255) NOT NULL,
    creado_en DATETIME DEFAULT CURRENT_TIMESTAMP,
    actualizado_en DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ============================================================
-- MÓDULO EMPAQUE - CATÁLOGOS ADMINISTRABLES
-- ============================================================
-- Arrancan vacíos; el administrador los llena desde la UI.

CREATE TABLE IF NOT EXISTS empaque_categorias (
    id_categoria INT AUTO_INCREMENT PRIMARY KEY,
    nombre VARCHAR(100) NOT NULL UNIQUE,
    activo BOOLEAN DEFAULT TRUE,
    creado_en DATETIME DEFAULT CURRENT_TIMESTAMP,
    actualizado_en DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS empaque_areas (
    id_area INT AUTO_INCREMENT PRIMARY KEY,
    nombre VARCHAR(100) NOT NULL UNIQUE,
    activo BOOLEAN DEFAULT TRUE,
    creado_en DATETIME DEFAULT CURRENT_TIMESTAMP,
    actualizado_en DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS empaque_proveedores (
    id_proveedor INT AUTO_INCREMENT PRIMARY KEY,
    nombre VARCHAR(200) NOT NULL UNIQUE,
    activo BOOLEAN DEFAULT TRUE,
    creado_en DATETIME DEFAULT CURRENT_TIMESTAMP,
    actualizado_en DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ============================================================
-- MÓDULO EMPAQUE - ARTÍCULO MAESTRO
-- ============================================================
CREATE TABLE IF NOT EXISTS empaque_articulos (
    codigo VARCHAR(20) PRIMARY KEY,
    nombre VARCHAR(255) NOT NULL UNIQUE,
    id_categoria INT NULL,
    um ENUM('Pz', 'Kg') NOT NULL,
    almacen VARCHAR(20) NOT NULL DEFAULT 'CP005',
    stock_minimo DECIMAL(14,3) NULL,
    fisico_dynamics DECIMAL(14,3) NULL,
    activo BOOLEAN DEFAULT TRUE,
    creado_en DATETIME DEFAULT CURRENT_TIMESTAMP,
    actualizado_en DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_empaque_articulos_categoria FOREIGN KEY (id_categoria)
        REFERENCES empaque_categorias(id_categoria) ON DELETE SET NULL,
    CONSTRAINT chk_empaque_articulos_um CHECK (um IN ('Pz', 'Kg'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE INDEX IF NOT EXISTS idx_empaque_articulos_categoria ON empaque_articulos(id_categoria);
CREATE INDEX IF NOT EXISTS idx_empaque_articulos_activo ON empaque_articulos(activo);

-- ============================================================
-- MÓDULO EMPAQUE - MOVIMIENTOS
-- ============================================================
CREATE TABLE IF NOT EXISTS empaque_entradas (
    id_entrada INT AUTO_INCREMENT PRIMARY KEY,
    codigo VARCHAR(20) NOT NULL,
    cantidad DECIMAL(14,3) NOT NULL,
    fecha DATE NOT NULL,
    id_proveedor INT NOT NULL,
    rechazos DECIMAL(14,3) NOT NULL DEFAULT 0,
    comentario TEXT NULL,
    creado_por INT NOT NULL,
    creado_en DATETIME DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_empaque_entradas_articulo FOREIGN KEY (codigo)
        REFERENCES empaque_articulos(codigo),
    CONSTRAINT fk_empaque_entradas_proveedor FOREIGN KEY (id_proveedor)
        REFERENCES empaque_proveedores(id_proveedor),
    CONSTRAINT fk_empaque_entradas_usuario FOREIGN KEY (creado_por)
        REFERENCES usuarios(id_usuario),
    CONSTRAINT chk_empaque_entradas_cantidad CHECK (cantidad > 0),
    CONSTRAINT chk_empaque_entradas_rechazos CHECK (rechazos >= 0 AND rechazos <= cantidad)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE INDEX IF NOT EXISTS idx_empaque_entradas_codigo ON empaque_entradas(codigo);
CREATE INDEX IF NOT EXISTS idx_empaque_entradas_fecha ON empaque_entradas(fecha);
CREATE INDEX IF NOT EXISTS idx_empaque_entradas_proveedor ON empaque_entradas(id_proveedor);

CREATE TABLE IF NOT EXISTS empaque_salidas (
    id_salida INT AUTO_INCREMENT PRIMARY KEY,
    codigo VARCHAR(20) NOT NULL,
    cantidad DECIMAL(14,3) NOT NULL,
    fecha DATE NOT NULL,
    id_area INT NOT NULL,
    id_lote INT NULL,
    comentario TEXT NULL,
    creado_por INT NOT NULL,
    creado_en DATETIME DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_empaque_salidas_articulo FOREIGN KEY (codigo)
        REFERENCES empaque_articulos(codigo),
    CONSTRAINT fk_empaque_salidas_area FOREIGN KEY (id_area)
        REFERENCES empaque_areas(id_area),
    CONSTRAINT fk_empaque_salidas_lote FOREIGN KEY (id_lote)
        REFERENCES lotes(id_lote) ON DELETE SET NULL,
    CONSTRAINT fk_empaque_salidas_usuario FOREIGN KEY (creado_por)
        REFERENCES usuarios(id_usuario),
    CONSTRAINT chk_empaque_salidas_cantidad CHECK (cantidad > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE INDEX IF NOT EXISTS idx_empaque_salidas_codigo ON empaque_salidas(codigo);
CREATE INDEX IF NOT EXISTS idx_empaque_salidas_fecha ON empaque_salidas(fecha);
CREATE INDEX IF NOT EXISTS idx_empaque_salidas_area ON empaque_salidas(id_area);
CREATE INDEX IF NOT EXISTS idx_empaque_salidas_lote ON empaque_salidas(id_lote);

CREATE TABLE IF NOT EXISTS empaque_ajustes (
    id_ajuste INT AUTO_INCREMENT PRIMARY KEY,
    codigo VARCHAR(20) NOT NULL,
    cantidad DECIMAL(14,3) NOT NULL,
    fecha DATE NOT NULL,
    motivo VARCHAR(255) NOT NULL,
    creado_por INT NOT NULL,
    creado_en DATETIME DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_empaque_ajustes_articulo FOREIGN KEY (codigo)
        REFERENCES empaque_articulos(codigo),
    CONSTRAINT fk_empaque_ajustes_usuario FOREIGN KEY (creado_por)
        REFERENCES usuarios(id_usuario)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE INDEX IF NOT EXISTS idx_empaque_ajustes_codigo ON empaque_ajustes(codigo);
CREATE INDEX IF NOT EXISTS idx_empaque_ajustes_fecha ON empaque_ajustes(fecha);

-- ============================================================
-- MÓDULO EMPAQUE - KIT POR ÁREA
-- ============================================================
CREATE TABLE IF NOT EXISTS empaque_kits (
    id_kit INT AUTO_INCREMENT PRIMARY KEY,
    id_area INT NOT NULL,
    codigo VARCHAR(20) NOT NULL,
    cantidad_sugerida DECIMAL(14,3) NOT NULL,
    creado_en DATETIME DEFAULT CURRENT_TIMESTAMP,
    actualizado_en DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT uq_empaque_kits_area_codigo UNIQUE (id_area, codigo),
    CONSTRAINT fk_empaque_kits_area FOREIGN KEY (id_area)
        REFERENCES empaque_areas(id_area),
    CONSTRAINT fk_empaque_kits_articulo FOREIGN KEY (codigo)
        REFERENCES empaque_articulos(codigo),
    CONSTRAINT chk_empaque_kits_cantidad CHECK (cantidad_sugerida > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
