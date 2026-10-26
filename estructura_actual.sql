-- Volcado de estructura (CREATE TABLE) - SICSE
-- Generado desde los modelos SQLAlchemy (app.py), dialecto MySQL.
-- Base: sistema_silos. Fecha: 2026-10-23
USE sistema_silos;

CREATE TABLE alerta_destinatarios (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	tipo_alerta VARCHAR(80) NOT NULL, 
	area ENUM('operacion','calidad','embarques','almacen','ti') NOT NULL, 
	PRIMARY KEY (id)
);
CREATE INDEX ix_alerta_destinatarios_tipo_alerta ON alerta_destinatarios (tipo_alerta);
CREATE TABLE clientes (
	id_cliente INTEGER NOT NULL AUTO_INCREMENT, 
	nombre_cliente VARCHAR(100), 
	codigo VARCHAR(20), 
	PRIMARY KEY (id_cliente), 
	UNIQUE (codigo)
);
CREATE TABLE empaque_areas (
	id_area INTEGER NOT NULL AUTO_INCREMENT, 
	nombre VARCHAR(100) NOT NULL, 
	activo BOOL, 
	creado_en DATETIME, 
	actualizado_en DATETIME, 
	PRIMARY KEY (id_area), 
	UNIQUE (nombre)
);
CREATE TABLE empaque_categorias (
	id_categoria INTEGER NOT NULL AUTO_INCREMENT, 
	nombre VARCHAR(100) NOT NULL, 
	activo BOOL, 
	creado_en DATETIME, 
	actualizado_en DATETIME, 
	PRIMARY KEY (id_categoria), 
	UNIQUE (nombre)
);
CREATE TABLE empaque_proveedores (
	id_proveedor INTEGER NOT NULL AUTO_INCREMENT, 
	nombre VARCHAR(200) NOT NULL, 
	activo BOOL, 
	creado_en DATETIME, 
	actualizado_en DATETIME, 
	PRIMARY KEY (id_proveedor), 
	UNIQUE (nombre)
);
CREATE TABLE estados_producto (
	id_estado INTEGER NOT NULL AUTO_INCREMENT, 
	nombre_estado VARCHAR(50), 
	PRIMARY KEY (id_estado)
);
CREATE TABLE facilitadores (
	id_facilitador INTEGER NOT NULL AUTO_INCREMENT, 
	nombre VARCHAR(200) NOT NULL, 
	activo BOOL, 
	creado_en DATETIME, 
	actualizado_en DATETIME, 
	PRIMARY KEY (id_facilitador)
);
CREATE TABLE lavaderos (
	id_lavadero INTEGER NOT NULL AUTO_INCREMENT, 
	nombre VARCHAR(200) NOT NULL, 
	activo BOOL, 
	creado_en DATETIME, 
	actualizado_en DATETIME, 
	PRIMARY KEY (id_lavadero), 
	UNIQUE (nombre)
);
CREATE TABLE parametros_sistema (
	clave VARCHAR(100) NOT NULL, 
	valor TEXT NOT NULL, 
	descripcion VARCHAR(255) NOT NULL, 
	creado_en DATETIME, 
	actualizado_en DATETIME, 
	PRIMARY KEY (clave)
);
CREATE TABLE productos_embarque (
	id_producto INTEGER NOT NULL AUTO_INCREMENT, 
	item VARCHAR(50) NOT NULL, 
	descripcion VARCHAR(255) NOT NULL, 
	variedad VARCHAR(100), 
	tipo ENUM('concentrado','pulpa','colateral') NOT NULL, 
	unidad_medida ENUM('KG','TAZ') NOT NULL, 
	activo BOOL, 
	creado_en DATETIME, 
	actualizado_en DATETIME, 
	PRIMARY KEY (id_producto), 
	UNIQUE (item)
);
CREATE TABLE silos (
	id_silo INTEGER NOT NULL AUTO_INCREMENT, 
	nombre_silo VARCHAR(20), 
	capacidad_gal NUMERIC(10, 2), 
	capacidad_barriles NUMERIC(10, 2), 
	tipo_producto VARCHAR(30), 
	tipo_permitido VARCHAR(30), 
	estado ENUM('activo','inactivo'), 
	PRIMARY KEY (id_silo)
);
CREATE TABLE tanques_tqpf (
	id_tanque INTEGER NOT NULL AUTO_INCREMENT, 
	nombre_tanque VARCHAR(30), 
	capacidad_gal NUMERIC(10, 2), 
	tipo_producto VARCHAR(30), 
	estado ENUM('activo','inactivo'), 
	PRIMARY KEY (id_tanque), 
	UNIQUE (nombre_tanque)
);
CREATE TABLE transportistas (
	id_transportista INTEGER NOT NULL AUTO_INCREMENT, 
	nombre VARCHAR(200) NOT NULL, 
	activo BOOL, 
	creado_en DATETIME, 
	actualizado_en DATETIME, 
	PRIMARY KEY (id_transportista), 
	UNIQUE (nombre)
);
CREATE TABLE unidades_transporte (
	id_unidad INTEGER NOT NULL AUTO_INCREMENT, 
	placa VARCHAR(30) NOT NULL, 
	tipo ENUM('tractor','remolque') NOT NULL, 
	activo BOOL, 
	creado_en DATETIME, 
	actualizado_en DATETIME, 
	PRIMARY KEY (id_unidad), 
	UNIQUE (placa)
);
CREATE TABLE usuarios (
	id_usuario INTEGER NOT NULL AUTO_INCREMENT, 
	nombre VARCHAR(100), 
	usuario VARCHAR(50) NOT NULL, 
	password VARCHAR(255) NOT NULL, 
	rol ENUM('administrador','capturista','invitado') NOT NULL, 
	activo BOOL, 
	debe_cambiar_password BOOL NOT NULL, 
	area ENUM('operacion','calidad','embarques','almacen','ti'), 
	PRIMARY KEY (id_usuario), 
	UNIQUE (usuario)
);
CREATE TABLE alertas (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	tipo VARCHAR(80) NOT NULL, 
	severidad ENUM('info','warning','danger') NOT NULL, 
	clave_unica VARCHAR(200) NOT NULL, 
	mensaje TEXT NOT NULL, 
	url VARCHAR(500), 
	estado ENUM('activa','atendida','cerrada') NOT NULL, 
	creada_en DATETIME, 
	actualizada_en DATETIME, 
	atendida_por INTEGER, 
	atendida_en DATETIME, 
	PRIMARY KEY (id), 
	UNIQUE (clave_unica), 
	FOREIGN KEY(atendida_por) REFERENCES usuarios (id_usuario)
);
CREATE TABLE densidad_brix (
	id_densidad INTEGER NOT NULL AUTO_INCREMENT, 
	id_producto INTEGER NOT NULL, 
	brix NUMERIC(6, 2) NOT NULL, 
	densidad_kg_l NUMERIC(8, 5) NOT NULL, 
	PRIMARY KEY (id_densidad), 
	FOREIGN KEY(id_producto) REFERENCES productos_embarque (id_producto)
);
CREATE TABLE empaque_articulos (
	codigo VARCHAR(20) NOT NULL, 
	nombre VARCHAR(255) NOT NULL, 
	id_categoria INTEGER, 
	um ENUM('Pz','Kg') NOT NULL, 
	almacen VARCHAR(20) NOT NULL, 
	stock_minimo NUMERIC(14, 3), 
	fisico_dynamics NUMERIC(14, 3), 
	activo BOOL, 
	creado_en DATETIME, 
	actualizado_en DATETIME, 
	PRIMARY KEY (codigo), 
	UNIQUE (nombre), 
	FOREIGN KEY(id_categoria) REFERENCES empaque_categorias (id_categoria)
);
CREATE TABLE lotes (
	id_lote INTEGER NOT NULL AUTO_INCREMENT, 
	codigo_lote VARCHAR(50), 
	fecha_lote DATE, 
	brix NUMERIC(5, 2), 
	relacion NUMERIC(5, 2), 
	pulpa NUMERIC(5, 2), 
	id_estado INTEGER, 
	id_cliente INTEGER, 
	cliente_manual VARCHAR(100), 
	es_mezcla BOOL NOT NULL, 
	asignado_por VARCHAR(50), 
	PRIMARY KEY (id_lote), 
	UNIQUE (codigo_lote), 
	FOREIGN KEY(id_estado) REFERENCES estados_producto (id_estado), 
	FOREIGN KEY(id_cliente) REFERENCES clientes (id_cliente)
);
CREATE TABLE operadores (
	id_operador INTEGER NOT NULL AUTO_INCREMENT, 
	nombre VARCHAR(200) NOT NULL, 
	id_transportista INTEGER, 
	activo BOOL, 
	creado_en DATETIME, 
	actualizado_en DATETIME, 
	PRIMARY KEY (id_operador), 
	FOREIGN KEY(id_transportista) REFERENCES transportistas (id_transportista)
);
CREATE TABLE embarques (
	id_embarque INTEGER NOT NULL AUTO_INCREMENT, 
	fecha_embarque DATE NOT NULL, 
	estatus ENUM('programado','en_planta','cargado','cancelado') NOT NULL, 
	num_cita VARCHAR(30) NOT NULL, 
	num_orden VARCHAR(30) NOT NULL, 
	ticket VARCHAR(30), 
	packing VARCHAR(30), 
	id_producto INTEGER, 
	id_cliente INTEGER, 
	producto_texto VARCHAR(200), 
	cliente_texto VARCHAR(200), 
	tipo_unidad ENUM('pipa_jumbo','pipa_chica','isotanque','flexitanque','caja_refrigerada','caja_seca','trailer','tambores') NOT NULL, 
	id_transportista INTEGER, 
	id_operador INTEGER, 
	id_tractor INTEGER, 
	id_remolque INTEGER, 
	id_silo INTEGER, 
	turno SMALLINT NOT NULL, 
	temperatura_c NUMERIC(5, 1), 
	id_capturista INTEGER NOT NULL, 
	id_facilitador INTEGER, 
	observaciones TEXT, 
	creado_en DATETIME, 
	actualizado_en DATETIME, 
	actualizado_por INTEGER, 
	PRIMARY KEY (id_embarque), 
	UNIQUE (num_cita), 
	UNIQUE (ticket), 
	UNIQUE (packing), 
	FOREIGN KEY(id_producto) REFERENCES productos_embarque (id_producto), 
	FOREIGN KEY(id_cliente) REFERENCES clientes (id_cliente), 
	FOREIGN KEY(id_transportista) REFERENCES transportistas (id_transportista), 
	FOREIGN KEY(id_operador) REFERENCES operadores (id_operador), 
	FOREIGN KEY(id_tractor) REFERENCES unidades_transporte (id_unidad), 
	FOREIGN KEY(id_remolque) REFERENCES unidades_transporte (id_unidad), 
	FOREIGN KEY(id_silo) REFERENCES silos (id_silo), 
	FOREIGN KEY(id_capturista) REFERENCES usuarios (id_usuario), 
	FOREIGN KEY(id_facilitador) REFERENCES facilitadores (id_facilitador), 
	FOREIGN KEY(actualizado_por) REFERENCES usuarios (id_usuario)
);
CREATE TABLE empaque_ajustes (
	id_ajuste INTEGER NOT NULL AUTO_INCREMENT, 
	codigo VARCHAR(20) NOT NULL, 
	cantidad NUMERIC(14, 3) NOT NULL, 
	fecha DATE NOT NULL, 
	motivo VARCHAR(255) NOT NULL, 
	creado_por INTEGER NOT NULL, 
	creado_en DATETIME, 
	PRIMARY KEY (id_ajuste), 
	FOREIGN KEY(codigo) REFERENCES empaque_articulos (codigo), 
	FOREIGN KEY(creado_por) REFERENCES usuarios (id_usuario)
);
CREATE TABLE empaque_entradas (
	id_entrada INTEGER NOT NULL AUTO_INCREMENT, 
	codigo VARCHAR(20) NOT NULL, 
	cantidad NUMERIC(14, 3) NOT NULL, 
	fecha DATE NOT NULL, 
	id_proveedor INTEGER NOT NULL, 
	rechazos NUMERIC(14, 3) NOT NULL, 
	comentario TEXT, 
	creado_por INTEGER NOT NULL, 
	creado_en DATETIME, 
	PRIMARY KEY (id_entrada), 
	FOREIGN KEY(codigo) REFERENCES empaque_articulos (codigo), 
	FOREIGN KEY(id_proveedor) REFERENCES empaque_proveedores (id_proveedor), 
	FOREIGN KEY(creado_por) REFERENCES usuarios (id_usuario)
);
CREATE TABLE empaque_kits (
	id_kit INTEGER NOT NULL AUTO_INCREMENT, 
	id_area INTEGER NOT NULL, 
	codigo VARCHAR(20) NOT NULL, 
	cantidad_sugerida NUMERIC(14, 3) NOT NULL, 
	creado_en DATETIME, 
	actualizado_en DATETIME, 
	PRIMARY KEY (id_kit), 
	CONSTRAINT uq_empaque_kit_area_codigo UNIQUE (id_area, codigo), 
	FOREIGN KEY(id_area) REFERENCES empaque_areas (id_area), 
	FOREIGN KEY(codigo) REFERENCES empaque_articulos (codigo)
);
CREATE TABLE empaque_salidas (
	id_salida INTEGER NOT NULL AUTO_INCREMENT, 
	codigo VARCHAR(20) NOT NULL, 
	cantidad NUMERIC(14, 3) NOT NULL, 
	fecha DATE NOT NULL, 
	id_area INTEGER NOT NULL, 
	id_lote INTEGER, 
	comentario TEXT, 
	creado_por INTEGER NOT NULL, 
	creado_en DATETIME, 
	PRIMARY KEY (id_salida), 
	FOREIGN KEY(codigo) REFERENCES empaque_articulos (codigo), 
	FOREIGN KEY(id_area) REFERENCES empaque_areas (id_area), 
	FOREIGN KEY(id_lote) REFERENCES lotes (id_lote), 
	FOREIGN KEY(creado_por) REFERENCES usuarios (id_usuario)
);
CREATE TABLE inventario_silos (
	id_inventario INTEGER NOT NULL AUTO_INCREMENT, 
	id_silo INTEGER, 
	id_lote INTEGER, 
	posicion INTEGER, 
	galones NUMERIC(10, 2), 
	fecha_registro DATETIME, 
	PRIMARY KEY (id_inventario), 
	CONSTRAINT uq_inventario_silo_posicion UNIQUE (id_silo, posicion), 
	CONSTRAINT uq_inventario_silo_lote UNIQUE (id_silo, id_lote), 
	FOREIGN KEY(id_silo) REFERENCES silos (id_silo), 
	FOREIGN KEY(id_lote) REFERENCES lotes (id_lote)
);
CREATE TABLE inventario_tqpf (
	id_inventario_tqpf INTEGER NOT NULL AUTO_INCREMENT, 
	id_tanque INTEGER, 
	id_lote INTEGER, 
	posicion INTEGER, 
	galones NUMERIC(10, 2), 
	fecha_registro DATETIME, 
	PRIMARY KEY (id_inventario_tqpf), 
	FOREIGN KEY(id_tanque) REFERENCES tanques_tqpf (id_tanque), 
	FOREIGN KEY(id_lote) REFERENCES lotes (id_lote)
);
CREATE TABLE movimientos (
	id_movimiento INTEGER NOT NULL AUTO_INCREMENT, 
	tipo_movimiento ENUM('entrada','salida','ajuste','reproceso','cambio_estado','entrada_tqpf','traspaso_tqpf_silo'), 
	id_silo INTEGER, 
	id_lote INTEGER, 
	id_tanque INTEGER, 
	galones NUMERIC(10, 2), 
	fecha_movimiento DATETIME, 
	id_usuario INTEGER, 
	observaciones TEXT, 
	PRIMARY KEY (id_movimiento), 
	FOREIGN KEY(id_silo) REFERENCES silos (id_silo), 
	FOREIGN KEY(id_lote) REFERENCES lotes (id_lote), 
	FOREIGN KEY(id_tanque) REFERENCES tanques_tqpf (id_tanque), 
	FOREIGN KEY(id_usuario) REFERENCES usuarios (id_usuario)
);
CREATE TABLE notificaciones (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	id_usuario INTEGER NOT NULL, 
	id_alerta INTEGER NOT NULL, 
	titulo VARCHAR(200) NOT NULL, 
	mensaje TEXT NOT NULL, 
	url VARCHAR(500), 
	leida BOOL NOT NULL, 
	creada_en DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(id_usuario) REFERENCES usuarios (id_usuario), 
	FOREIGN KEY(id_alerta) REFERENCES alertas (id)
);
CREATE INDEX ix_notificaciones_id_usuario ON notificaciones (id_usuario);
CREATE TABLE embarque_detalle (
	id_embarque INTEGER NOT NULL, 
	id_lavadero INTEGER, 
	check_list BOOL, 
	lote_tambor VARCHAR(100), 
	PRIMARY KEY (id_embarque), 
	FOREIGN KEY(id_embarque) REFERENCES embarques (id_embarque), 
	FOREIGN KEY(id_lavadero) REFERENCES lavaderos (id_lavadero)
);
CREATE TABLE embarque_lotes (
	id_embarque INTEGER NOT NULL, 
	id_lote INTEGER NOT NULL, 
	cantidad NUMERIC(12, 2) NOT NULL, 
	id_movimiento INTEGER, 
	PRIMARY KEY (id_embarque, id_lote), 
	FOREIGN KEY(id_embarque) REFERENCES embarques (id_embarque), 
	FOREIGN KEY(id_lote) REFERENCES lotes (id_lote), 
	FOREIGN KEY(id_movimiento) REFERENCES movimientos (id_movimiento)
);
CREATE TABLE embarque_pesos (
	id_embarque INTEGER NOT NULL, 
	peso_bruto_kg NUMERIC(12, 2), 
	tara_kg NUMERIC(12, 2), 
	peso_neto_kg NUMERIC(12, 2), 
	actualizado_por INTEGER, 
	actualizado_en DATETIME, 
	PRIMARY KEY (id_embarque), 
	FOREIGN KEY(id_embarque) REFERENCES embarques (id_embarque), 
	FOREIGN KEY(actualizado_por) REFERENCES usuarios (id_usuario)
);
CREATE TABLE embarque_sellos (
	id_sello INTEGER NOT NULL AUTO_INCREMENT, 
	id_embarque INTEGER NOT NULL, 
	tipo ENUM('lavado','valvula','escotilla','puerta_trasera') NOT NULL, 
	numero VARCHAR(100) NOT NULL, 
	creado_en DATETIME, 
	PRIMARY KEY (id_sello), 
	FOREIGN KEY(id_embarque) REFERENCES embarques (id_embarque), 
	UNIQUE (numero)
);
CREATE TABLE embarque_tiempos (
	id_embarque INTEGER NOT NULL, 
	llegada DATETIME, 
	entrada DATETIME, 
	pesado_inicial DATETIME, 
	pesaje_salida DATETIME, 
	documentacion DATETIME, 
	salida DATETIME, 
	PRIMARY KEY (id_embarque), 
	FOREIGN KEY(id_embarque) REFERENCES embarques (id_embarque)
);
CREATE TABLE lote_componentes (
	id_componente INTEGER NOT NULL AUTO_INCREMENT, 
	id_lote_mezcla INTEGER NOT NULL, 
	id_lote_origen INTEGER NOT NULL, 
	id_embarque INTEGER, 
	galones NUMERIC(10, 2) NOT NULL, 
	creado_en DATETIME, 
	PRIMARY KEY (id_componente), 
	CONSTRAINT uq_lote_componente UNIQUE (id_lote_mezcla, id_lote_origen, id_embarque), 
	FOREIGN KEY(id_lote_mezcla) REFERENCES lotes (id_lote), 
	FOREIGN KEY(id_lote_origen) REFERENCES lotes (id_lote), 
	FOREIGN KEY(id_embarque) REFERENCES embarques (id_embarque)
);