import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import Movimiento, app, db


def main():
    with app.app_context():
        deleted = Movimiento.query.delete()
        db.session.commit()
        print(f"Historial borrado. Movimientos eliminados: {deleted}")


if __name__ == "__main__":
    main()
