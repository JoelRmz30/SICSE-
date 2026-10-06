from app import app, db, Usuario, EstadoProducto, Cliente, Silo
import werkzeug.security # pyright: ignore[reportMissingImports]
import os
import dotenv # pyright: ignore[reportMissingImports]

dotenv.load_dotenv()

def init_db():
    print("Iniciando inicialización de base de datos...")
    with app.app_context():
        # Crear todas las tablas si no existen
        print("Creando tablas...")
        db.create_all()
        
        # Verificar si ya existen estados de producto
        count_estados = EstadoProducto.query.count()
        print(f"Estados encontrados: {count_estados}")
        if count_estados == 0:
            print("Insertando estados de producto...")
            estados = [
                'Liberado', 
                'Pendiente Micro', 
                'Reproceso', 
                'No apto', 
                'N Temprana Liberado'
            ]
            for nombre in estados:
                estado = EstadoProducto(nombre_estado=nombre)
                db.session.add(estado)
        
        # Verificar si ya existen clientes (solo si se solicita explícitamente)
        if Cliente.query.count() == 0 and os.getenv('SEED_CLIENTES', '0') == '1':
            print("Insertando clientes de ejemplo...")
            clientes = ['Peace River', 'Paso Largo']
            for nombre in clientes:
                cliente = Cliente(nombre_cliente=nombre)
                db.session.add(cliente)
        
        print("Verificando catálogo de silos...")
        silos_data = [
            ('Silo 1', 6213.00, 119.48, None, None),
            ('Silo 2', 6213.00, 119.48, None, None),
            ('Silo 3', 6213.00, 119.48, None, None),
            ('Silo 4', 6213.00, 119.48, None, None),
            ('Silo 5', 8548.00, 164.38, None, None),
            ('Silo 6', 8548.00, 164.38, None, None),
            ('Silo 7', 8548.00, 164.38, None, None),
            ('Silo 8', 8112.00, 156.00, 'aceite', 'aceite'),
            ('Silo 9', 8112.00, 156.00, 'aceite', 'aceite'),
            ('Silo 10', 8112.00, 156.00, 'aceite', 'aceite'),
            ('Silo 11', 8112.00, 156.00, 'aceite', 'aceite'),
            ('Silo 12', 9093.00, 174.86, None, None),
            ('Silo 13', 9093.00, 174.86, None, None),
            ('Silo 14', 9093.00, 174.86, None, None),
            ('Silo 15', 9093.00, 174.86, None, None),
            ('Silo 16', 9093.00, 174.86, None, None),
            ('Silo 17', 9093.00, 174.86, None, None),
            ('Silo 18', 19200.00, 369.23, 'nfc', 'nfc'),
            ('Silo 19', 19200.00, 369.23, 'nfc', 'nfc'),
            ('Silo 20', 19200.00, 369.23, 'nfc', 'nfc')
        ]
        for nombre, cap_g, cap_b, tipo, permitido in silos_data:
            existing = Silo.query.filter_by(nombre_silo=nombre).first()
            if existing:
                existing.capacidad_gal = cap_g
                existing.capacidad_barriles = cap_b
                existing.tipo_permitido = permitido
                if permitido:
                    existing.tipo_producto = permitido
            else:
                silo = Silo(
                    nombre_silo=nombre,
                    capacidad_gal=cap_g,
                    capacidad_barriles=cap_b,
                    tipo_producto=tipo,
                    tipo_permitido=permitido
                )
                db.session.add(silo)

        # Verificar si ya existe el administrador
        admin_user = Usuario.query.filter_by(usuario='admin').first()
        hashed_admin_pw = werkzeug.security.generate_password_hash('admin123')
        if not admin_user:
            print("Creando usuario administrador...")
            admin = Usuario(
                nombre='Administrador Sistema',
                usuario='admin',
                password=hashed_admin_pw,
                rol='administrador',
                activo=True
            )
            db.session.add(admin)
        else:
            print("Actualizando contraseña de administrador por defecto...")
            admin_user.password = hashed_admin_pw

        # Crear un capturista de prueba
        capturista_user = Usuario.query.filter_by(usuario='capturista').first()
        hashed_cap_pw = werkzeug.security.generate_password_hash('cap123')
        if not capturista_user:
            print("Creando usuario capturista...")
            capturista = Usuario(
                nombre='Capturista',
                usuario='capturista',
                password=hashed_cap_pw,
                rol='capturista',
                activo=True
            )
            db.session.add(capturista)
        else:
            print("Actualizando contraseña de capturista por defecto...")
            capturista_user.password = hashed_cap_pw

        invitado_user = Usuario.query.filter_by(usuario='invitado').first()
        hashed_invitado_pw = werkzeug.security.generate_password_hash('invitado123')
        if not invitado_user:
            print("Creando usuario invitado...")
            invitado = Usuario(
                nombre='Invitado',
                usuario='invitado',
                password=hashed_invitado_pw,
                rol='invitado',
                activo=True
            )
            db.session.add(invitado)
        else:
            print("Actualizando contraseña de invitado por defecto...")
            invitado_user.password = hashed_invitado_pw

        db.session.commit()
        print("Base de datos inicializada correctamente.")

if __name__ == '__main__':
    init_db()
