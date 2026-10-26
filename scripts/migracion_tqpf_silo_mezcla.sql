-- ============================================================
-- MIGRACIÓN: FLUJO TQPF -> SILO, LOTE DE MEZCLA (INVOCA)
-- SICSE - Sistema Integral de Control de Silos y Embarques
-- ------------------------------------------------------------
-- Objetivo:
--   1. Ampliar movimientos (nuevos tipos + id_tanque).
--   2. Asegurar el ENUM de usuarios.rol.
--   3. Marcar lotes de mezcla (es_mezcla / asignado_por).
--   4. Crear la tabla lote_componentes (origen de un lote de mezcla).
--   5. Unicidad en inventario_silos (id_silo,posicion) y (id_silo,id_lote).
--   6. Guardar el silo del embarque (embarques.id_silo).
--   7. Parámetros nuevos del sistema.
--
-- IDEMPOTENTE: se puede ejecutar varias veces sin error ni pérdida de datos.
-- NO borra datos: sólo consolida duplicados de inventario_silos cuando existen.
-- ============================================================

USE sistema_silos;

-- ============================================================
-- 1. movimientos: ampliar ENUM tipo_movimiento
-- ============================================================
-- Valores finales:
--   entrada, salida, ajuste, reproceso, cambio_estado,
--   entrada_tqpf, traspaso_tqpf_silo
SET @enum_ok = (
    SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'movimientos'
      AND COLUMN_NAME = 'tipo_movimiento'
      AND COLUMN_TYPE LIKE '%entrada_tqpf%'
);
SET @sql = IF(@enum_ok = 0,
    'ALTER TABLE movimientos MODIFY COLUMN tipo_movimiento ENUM(''entrada'',''salida'',''ajuste'',''reproceso'',''cambio_estado'',''entrada_tqpf'',''traspaso_tqpf_silo'') NULL COMMENT ''Tipo de movimiento de inventario''',
    'SELECT ''movimientos.tipo_movimiento ya incluye los tipos nuevos'' AS mensaje'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- ============================================================
-- 1b. movimientos: columna id_tanque (FK a tanques_tqpf)
-- ============================================================
SET @col_tanque = (
    SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'movimientos'
      AND COLUMN_NAME = 'id_tanque'
);
SET @sql = IF(@col_tanque = 0,
    'ALTER TABLE movimientos ADD COLUMN id_tanque INT NULL COMMENT ''Tanque TQPF afectado (movimientos de proceso)''',
    'SELECT ''movimientos.id_tanque ya existe'' AS mensaje'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- FK de id_tanque (sólo si la tabla tanques_tqpf existe y la FK no está creada)
SET @tqpf_exists = (
    SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'tanques_tqpf'
);
SET @fk_tanque = (
    SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'movimientos'
      AND CONSTRAINT_NAME = 'fk_movimientos_tanque'
);
SET @sql = IF(@tqpf_exists = 1 AND @fk_tanque = 0,
    'ALTER TABLE movimientos ADD CONSTRAINT fk_movimientos_tanque FOREIGN KEY (id_tanque) REFERENCES tanques_tqpf(id_tanque) ON DELETE SET NULL',
    'SELECT ''FK fk_movimientos_tanque no requerida'' AS mensaje'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @idx_tanque = (
    SELECT COUNT(*) FROM INFORMATION_SCHEMA.STATISTICS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'movimientos'
      AND INDEX_NAME = 'idx_movimientos_tanque'
);
SET @sql = IF(@idx_tanque = 0,
    'ALTER TABLE movimientos ADD INDEX idx_movimientos_tanque (id_tanque)',
    'SELECT ''índice idx_movimientos_tanque ya existe'' AS mensaje'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- ============================================================
-- 2. usuarios.rol: asegurar ENUM (administrador, capturista, invitado)
-- ============================================================
ALTER TABLE usuarios
    MODIFY COLUMN rol ENUM('administrador','capturista','invitado') NOT NULL;

-- ============================================================
-- 3. lotes: es_mezcla y asignado_por
-- ============================================================
SET @col_mezcla = (
    SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'lotes' AND COLUMN_NAME = 'es_mezcla'
);
SET @sql = IF(@col_mezcla = 0,
    'ALTER TABLE lotes ADD COLUMN es_mezcla TINYINT(1) NOT NULL DEFAULT 0 COMMENT ''1 si el lote es una mezcla generada en un embarque de pipa''',
    'SELECT ''lotes.es_mezcla ya existe'' AS mensaje'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @col_asignado = (
    SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'lotes' AND COLUMN_NAME = 'asignado_por'
);
SET @sql = IF(@col_asignado = 0,
    'ALTER TABLE lotes ADD COLUMN asignado_por VARCHAR(50) NULL COMMENT ''Área/sistema que asignó el código del lote (Ej: INVOCA)''',
    'SELECT ''lotes.asignado_por ya existe'' AS mensaje'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- 3b. lotes.cliente_manual: el modelo SQLAlchemy (app.py) usa este campo para
--     capturar el cliente como texto libre cuando no está en el catálogo.
--     Se agrega de forma defensiva por si la base real no lo tuviera.
SET @col_cli_manual = (
    SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'lotes' AND COLUMN_NAME = 'cliente_manual'
);
SET @sql = IF(@col_cli_manual = 0,
    'ALTER TABLE lotes ADD COLUMN cliente_manual VARCHAR(100) NULL COMMENT ''Cliente capturado como texto libre cuando no está en el catálogo''',
    'SELECT ''lotes.cliente_manual ya existe'' AS mensaje'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- ============================================================
-- 4. Nueva tabla: lote_componentes
--    Registra de qué lotes de origen (y cuántos galones) se armó
--    un lote de mezcla en un embarque de pipa.
-- ============================================================
CREATE TABLE IF NOT EXISTS lote_componentes (
    id_componente INT AUTO_INCREMENT PRIMARY KEY,
    id_lote_mezcla INT NOT NULL COMMENT 'Lote de mezcla (lotes.es_mezcla = 1)',
    id_lote_origen INT NOT NULL COMMENT 'Lote de origen que se consumió',
    id_embarque INT NULL COMMENT 'Embarque donde se generó la mezcla',
    galones DECIMAL(10,2) NOT NULL COMMENT 'Galones tomados de este lote de origen',
    creado_en DATETIME DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_lote_comp_mezcla FOREIGN KEY (id_lote_mezcla)
        REFERENCES lotes(id_lote) ON DELETE CASCADE,
    CONSTRAINT fk_lote_comp_origen FOREIGN KEY (id_lote_origen)
        REFERENCES lotes(id_lote) ON DELETE RESTRICT,
    CONSTRAINT fk_lote_comp_embarque FOREIGN KEY (id_embarque)
        REFERENCES embarques(id_embarque) ON DELETE CASCADE,
    CONSTRAINT uq_lote_componente UNIQUE (id_lote_mezcla, id_lote_origen, id_embarque),
    CONSTRAINT chk_lote_comp_galones CHECK (galones > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Lotes de origen que componen un lote de mezcla (embarques de pipa)';

-- ============================================================
-- 5. inventario_silos: consolidar duplicados ANTES de crear UNIQUE
-- ------------------------------------------------------------
-- Reporte: cuántos duplicados (id_silo,id_lote) existen hoy.
-- ============================================================
SELECT 'inventario_silos: duplicados por (id_silo,id_lote) consolidables' AS revision,
       COUNT(*) AS grupos_duplicados
FROM (
    SELECT id_silo, id_lote
    FROM inventario_silos
    GROUP BY id_silo, id_lote
    HAVING COUNT(*) > 1
) d;

-- 5.1 Sumar galones en la fila "conservada" (menor id_inventario) y conservar la menor posición.
UPDATE inventario_silos a
JOIN (
    SELECT id_silo, id_lote,
           MIN(id_inventario) AS keep_id,
           SUM(galones)       AS nuevos_galones,
           MIN(posicion)      AS nueva_posicion
    FROM inventario_silos
    GROUP BY id_silo, id_lote
    HAVING COUNT(*) > 1
) d ON a.id_inventario = d.keep_id
SET a.galones  = d.nuevos_galones,
    a.posicion = d.nueva_posicion;

-- 5.2 Eliminar las filas duplicadas (se conserva la de menor id_inventario).
DELETE a FROM inventario_silos a
JOIN (
    SELECT id_silo, id_lote, MIN(id_inventario) AS keep_id
    FROM inventario_silos
    GROUP BY id_silo, id_lote
    HAVING COUNT(*) > 1
) d ON a.id_silo = d.id_silo AND a.id_lote = d.id_lote AND a.id_inventario <> d.keep_id;

-- 5.3 Renumerar posiciones 1..n por silo (para que (id_silo,posicion) sea único).
UPDATE inventario_silos s
JOIN (
    SELECT id_inventario,
           ROW_NUMBER() OVER (PARTITION BY id_silo ORDER BY posicion ASC, id_inventario ASC) AS nueva_pos
    FROM inventario_silos
) r ON s.id_inventario = r.id_inventario
SET s.posicion = r.nueva_pos;

-- 5.4 Crear los índices UNIQUE (si no existen).
SET @uq_pos = (
    SELECT COUNT(*) FROM INFORMATION_SCHEMA.STATISTICS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'inventario_silos'
      AND INDEX_NAME = 'uq_inventario_silo_posicion'
);
SET @sql = IF(@uq_pos = 0,
    'ALTER TABLE inventario_silos ADD UNIQUE KEY uq_inventario_silo_posicion (id_silo, posicion)',
    'SELECT ''uq_inventario_silo_posicion ya existe'' AS mensaje'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @uq_lote = (
    SELECT COUNT(*) FROM INFORMATION_SCHEMA.STATISTICS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'inventario_silos'
      AND INDEX_NAME = 'uq_inventario_silo_lote'
);
SET @sql = IF(@uq_lote = 0,
    'ALTER TABLE inventario_silos ADD UNIQUE KEY uq_inventario_silo_lote (id_silo, id_lote)',
    'SELECT ''uq_inventario_silo_lote ya existe'' AS mensaje'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- ============================================================
-- 6. embarques.id_silo  (un silo por embarque)
-- ============================================================
SET @col_silo_emb = (
    SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'embarques' AND COLUMN_NAME = 'id_silo'
);
SET @sql = IF(@col_silo_emb = 0,
    'ALTER TABLE embarques ADD COLUMN id_silo INT NULL COMMENT ''Silo del que sale el producto del embarque''',
    'SELECT ''embarques.id_silo ya existe'' AS mensaje'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @fk_silo_emb = (
    SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'embarques'
      AND CONSTRAINT_NAME = 'fk_embarques_silo'
);
SET @sql = IF(@fk_silo_emb = 0,
    'ALTER TABLE embarques ADD CONSTRAINT fk_embarques_silo FOREIGN KEY (id_silo) REFERENCES silos(id_silo) ON DELETE SET NULL',
    'SELECT ''FK fk_embarques_silo ya existe'' AS mensaje'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @idx_silo_emb = (
    SELECT COUNT(*) FROM INFORMATION_SCHEMA.STATISTICS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'embarques'
      AND INDEX_NAME = 'idx_embarques_silo'
);
SET @sql = IF(@idx_silo_emb = 0,
    'ALTER TABLE embarques ADD INDEX idx_embarques_silo (id_silo)',
    'SELECT ''índice idx_embarques_silo ya existe'' AS mensaje'
);
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- ============================================================
-- 7. Parámetros nuevos del sistema
-- ============================================================
INSERT INTO parametros_sistema (clave, valor, descripcion)
SELECT 'permitir_entrada_directa_silo', '1',
       'Permite la captura directa a silo sin pasar por TQPF (1 = permitido, 0 = sólo traspaso desde TQPF)'
WHERE NOT EXISTS (SELECT 1 FROM parametros_sistema WHERE clave = 'permitir_entrada_directa_silo');

INSERT INTO parametros_sistema (clave, valor, descripcion)
SELECT 'tqpf_ocupacion_alerta_pct', '90',
       'Porcentaje de ocupación de un tanque TQPF a partir del cual se genera alerta'
WHERE NOT EXISTS (SELECT 1 FROM parametros_sistema WHERE clave = 'tqpf_ocupacion_alerta_pct');

-- Fin de la migración
SELECT 'Migración TQPF/Silo/Mezcla aplicada correctamente (idempotente).' AS resultado;
