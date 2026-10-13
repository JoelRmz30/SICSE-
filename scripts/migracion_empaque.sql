-- =====================================================================
-- MÓDULO EMPAQUE - MIGRACIÓN IDEMPOTENTE
-- Script para creación de tablas del módulo Material de Empaque.
--
-- Convenciones:
--   - Todas las tablas usan prefijo empaque_.
--   - Todo CREATE TABLE con IF NOT EXISTS.
--   - FK con ON DELETE SET NULL donde aplique (catálogos desactivables).
--   - Engine=InnoDB, CHARSET=utf8mb4.
--
-- NO INSERTA DATOS. El usuario carga catálogos y movimientos desde UI
-- o desde plantillas de Excel.
-- =====================================================================

-- Asegurar que la base de datos existe.
CREATE DATABASE IF NOT EXISTS sistema_silos;
USE sistema_silos;

-- =====================================================================
-- 1. CATÁLOGOS ADMINISTRABLES (vacíos)
-- =====================================================================

CREATE TABLE IF NOT EXISTS empaque_categorias (
    id_categoria INT AUTO_INCREMENT PRIMARY KEY,
    nombre VARCHAR(100) NOT NULL UNIQUE,
    activo BOOLEAN DEFAULT TRUE,
    creado_en DATETIME DEFAULT CURRENT_TIMESTAMP,
    actualizado_en DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Catálogo editable de categorías de artículos de empaque.';

CREATE TABLE IF NOT EXISTS empaque_areas (
    id_area INT AUTO_INCREMENT PRIMARY KEY,
    nombre VARCHAR(100) NOT NULL UNIQUE,
    activo BOOLEAN DEFAULT TRUE,
    creado_en DATETIME DEFAULT CURRENT_TIMESTAMP,
    actualizado_en DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Catálogo editable de áreas solicitantes de empaque. Pulpa = requiere lote.';

CREATE TABLE IF NOT EXISTS empaque_proveedores (
    id_proveedor INT AUTO_INCREMENT PRIMARY KEY,
    nombre VARCHAR(200) NOT NULL UNIQUE,
    activo BOOLEAN DEFAULT TRUE,
    creado_en DATETIME DEFAULT CURRENT_TIMESTAMP,
    actualizado_en DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Catálogo editable de proveedores de empaque.';

-- =====================================================================
-- 2. ARTÍCULO (catálogo maestro)
-- =====================================================================
-- Regla: nombre y um viven SÓLO aquí. Los movimientos guardan FK.
-- codigo es PK natural del negocio (ej. IN00120071).

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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Catálogo maestro de artículos de empaque.';

CREATE INDEX IF NOT EXISTS idx_empaque_articulos_categoria ON empaque_articulos(id_categoria);
CREATE INDEX IF NOT EXISTS idx_empaque_articulos_activo ON empaque_articulos(activo);

-- =====================================================================
-- 3. MOVIMIENTOS (entradas, salidas, ajustes)
-- =====================================================================
-- Invariante: los movimientos NUNCA se editan ni borran.
--   Las correcciones se hacen vía empaque_ajustes con motivo.

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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Entradas de empaque. Stock neto = cantidad - rechazos.';

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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Salidas de empaque. Si área=Pulpa entonces id_lote es NOT NULL (lógica en app).';

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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Ajustes de inventario. Única vía de corrección. Motivo obligatorio.';

CREATE INDEX IF NOT EXISTS idx_empaque_ajustes_codigo ON empaque_ajustes(codigo);
CREATE INDEX IF NOT EXISTS idx_empaque_ajustes_fecha ON empaque_ajustes(fecha);

-- =====================================================================
-- 4. KIT POR ÁREA (generalmente Pulpa)
-- =====================================================================

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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Kit sugerido por área. Un combo único por (area, articulo).';
