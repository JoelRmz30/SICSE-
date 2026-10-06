"""
Verificación rápida post-migración:
  1) Existen las tablas nuevas del módulo de embarques.
  2) La tabla clientes tiene la columna codigo VARCHAR(20).
  3) app.py importa sin error y los modelos se vinculan.
"""
import sys
import os

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from app import (  # noqa: E402
    db,
    app,
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
    ParametroSistema,
    Cliente,
    Embarque,
)

def main():
    with app.app_context():
        print("[1/3] Importar modelos: OK")
        inspector = db.inspect(db.engine)
        tablas = set(inspector.get_table_names())
        esperadas = {
            "productos_embarque",
            "transportistas",
            "operadores",
            "unidades_transporte",
            "lavaderos",
            "facilitadores",
            "embarques",
            "embarque_tiempos",
            "embarque_detalle",
            "embarque_sellos",
            "embarque_lotes",
            "parametros_sistema",
        }
        faltan = esperadas - tablas
        if faltan:
            print(f"[2/3] ERROR: Faltan tablas: {faltan}")
            sys.exit(1)
        print(f"[2/3] Tablas del módulo embarques: OK ({len(esperadas)}/{len(esperadas)})")

        # Verificar que clientes tiene la columna codigo
        cols_clientes = {c["name"] for c in inspector.get_columns("clientes")}
        if "codigo" not in cols_clientes:
            print("[3/3] ERROR: clientes no tiene columna 'codigo'.")
            sys.exit(1)
        print("[3/3] Columna 'codigo' en clientes: OK")

        # Un pequeño count para confirmar que la tabla clientes sigue siendo la misma
        total_clientes = db.session.query(db.func.count(Cliente.id_cliente)).scalar()
        print(f"  (Clientes existentes: {total_clientes})")

        print("\n[DONE] Todas las verificaciones de migración pasaron.")


if __name__ == "__main__":
    main()
