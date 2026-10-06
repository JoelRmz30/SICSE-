ALTER TABLE silos
  MODIFY tipo_producto VARCHAR(30) NULL,
  ADD COLUMN tipo_permitido VARCHAR(30) NULL;
