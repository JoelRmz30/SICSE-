from app import app, db, Usuario, EstadoProducto, Cliente, Silo, TanqueTQPF
import werkzeug.security # pyright: ignore[reportMissingImports]
import os
import secrets
import string
import dotenv # pyright: ignore[reportMissingImports]

dotenv.load_dotenv()

def _generar_password(longitud=16):
    """Genera una contraseña aleatoria segura."""
    alfabeto = string.ascii_letters + string.digits + "!@#$%^&*()-_=+"
    return ''.join(secrets.choice(alfabeto) for _ in range(longitud))

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

        # Catálogo de tanques de proceso (TQPF): 3 tanques de pared fría.
        print("Verificando catálogo de tanques TQPF...")
        tanques_tqpf = ['TQPF-1', 'TQPF-2', 'TQPF-3']
        for nombre in tanques_tqpf:
            if not TanqueTQPF.query.filter_by(nombre_tanque=nombre).first():
                db.session.add(TanqueTQPF(nombre_tanque=nombre))

        # Verificar si ya existe el administrador
        admin_user = Usuario.query.filter_by(usuario='admin').first()
        if not admin_user:
            admin_pw = _generar_password()
            print("Creando usuario administrador...")
            admin = Usuario(
                nombre='Administrador Sistema',
                usuario='admin',
                password=werkzeug.security.generate_password_hash(admin_pw),
                rol='administrador',
                activo=True,
                debe_cambiar_password=True,
            )
            db.session.add(admin)
            print("=" * 60)
            print(f"  Usuario administrador creado: admin")
            print(f"  Contraseña temporal: {admin_pw}")
            print("  (Deberá cambiarla en el primer inicio de sesión)")
            print("=" * 60)
        else:
            print("El usuario administrador ya existe.")

        # Crear un capturista de prueba (solo si no existe)
        capturista_user = Usuario.query.filter_by(usuario='capturista').first()
        if not capturista_user:
            cap_pw = _generar_password()
            print("Creando usuario capturista...")
            capturista = Usuario(
                nombre='Capturista',
                usuario='capturista',
                password=werkzeug.security.generate_password_hash(cap_pw),
                rol='capturista',
                activo=True,
                debe_cambiar_password=True,
            )
            db.session.add(capturista)
            print(f"  Usuario capturista creado: capturista  Contraseña temporal: {cap_pw}")

        invitado_user = Usuario.query.filter_by(usuario='invitado').first()
        if not invitado_user:
            inv_pw = _generar_password()
            print("Creando usuario invitado...")
            invitado = Usuario(
                nombre='Invitado',
                usuario='invitado',
                password=werkzeug.security.generate_password_hash(inv_pw),
                rol='invitado',
                activo=True,
                debe_cambiar_password=True,
            )
            db.session.add(invitado)
            print(f"  Usuario invitado creado: invitado  Contraseña temporal: {inv_pw}")

        db.session.commit()
        print("Base de datos inicializada correctamente.")

if __name__ == '__main__':
    init_db()
