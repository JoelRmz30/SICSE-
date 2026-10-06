import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

print("db_check: starting")

from app import app, InventarioSilo, Movimiento, Silo


def main():
    with app.app_context():
        print("DB:", app.config.get("SQLALCHEMY_DATABASE_URI"))
        print("silos:", Silo.query.count())
        print("inventario_silos:", InventarioSilo.query.count())
        print("movimientos:", Movimiento.query.count())


if __name__ == "__main__":
    main()
