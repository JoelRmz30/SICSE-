import sys
sys.path.insert(0, '.')
out = []
from app import app, db, Cliente, ProductoEmbarque, Transportista, Embarque
with app.app_context():
    insp = db.inspect(db.engine)
    t = set(insp.get_table_names())
    esperadas = ['productos_embarque','transportistas','operadores','unidades_transporte','lavaderos','facilitadores','embarques','embarque_tiempos','embarque_detalle','embarque_sellos','embarque_lotes','parametros_sistema']
    ok = 0
    for e in esperadas:
        if e in t:
            ok += 1
            out.append(f'OK {e}')
        else:
            out.append(f'MISSING {e}')
    cols = [c['name'] for c in insp.get_columns('clientes')]
    if 'codigo' in cols:
        out.append('OK clientes.codigo existe.')
    else:
        out.append('ERROR clientes.codigo FALTA.')
    out.append(f'Tablas nuevas: {ok}/12')
with open('c:/xampp/htdocs/DUAL/sistema_gestor de silos/_check_result.txt', 'w', encoding='utf-8') as f:
    f.write('\n'.join(out))
