import sys
sys.path.insert(0, 'c:/xampp/htdocs/DUAL/sistema_gestor de silos')
sys.path.insert(0, '.')
from app import app, db, Cliente, ProductoEmbarque, Transportista, Embarque
with app.app_context():
    insp = db.inspect(db.engine)
    t = set(insp.get_table_names())
    esperadas = ['productos_embarque','transportistas','operadores','unidades_transporte','lavaderos','facilitadores','embarques','embarque_tiempos','embarque_detalle','embarque_sellos','embarque_lotes','parametros_sistema']
    ok = 0
    for e in esperadas:
        if e in t:
            ok += 1
            sys.stdout.write(f'  OK {e}\n')
        else:
            sys.stdout.write(f'  MISSING {e}\n')
    cols = [c['name'] for c in insp.get_columns('clientes')]
    if 'codigo' in cols:
        sys.stdout.write('  OK clientes.codigo existe.\n')
    else:
        sys.stdout.write('  ERROR clientes.codigo FALTA.\n')
    sys.stdout.write(f'Tablas nuevas: {ok}/12\n')
    sys.stdout.flush()
