from app import app, db, Usuario
import werkzeug.security

with app.app_context():
    users_updated = 0
    for usuario in Usuario.query.all():
        rol_original = usuario.rol
        rol_limpio = (rol_original or '').strip().lower() if rol_original else ''
        if rol_limpio in ('administrador', 'capturista', 'invitado') and rol_original != rol_limpio:
            print(f"[CORREGIDO] Usuario '{usuario.usuario}': rol '{rol_original}' -> '{rol_limpio}'")
            usuario.rol = rol_limpio
            users_updated += 1
        elif not rol_original or rol_limpio not in ('administrador', 'capturista', 'invitado'):
            print(f"[CORREGIDO] Usuario '{usuario.usuario}': rol nulo/inválido -> 'invitado'")
            usuario.rol = 'invitado'
            users_updated += 1
        else:
            print(f"[OK] Usuario '{usuario.usuario}' con rol '{rol_original}'")

    invitado_user = Usuario.query.filter_by(usuario='invitado').first()
    if invitado_user:
        if invitado_user.rol != 'invitado':
            invitado_user.rol = 'invitado'
            print(f"[FORZADO] Usuario 'invitado' establecido a rol 'invitado'")
            users_updated += 1
        invitado_user.password = werkzeug.security.generate_password_hash('invitado123')
        invitado_user.activo = True
        print("[INFO] Contraseña de 'invitado' restablecida a: invitado123")
    else:
        print("[INFO] Creando usuario 'invitado' faltante...")
        nuevo = Usuario(
            nombre='Invitado',
            usuario='invitado',
            password=werkzeug.security.generate_password_hash('invitado123'),
            rol='invitado',
            activo=True
        )
        db.session.add(nuevo)
        users_updated += 1

    if users_updated > 0:
        db.session.commit()
        print(f"\nSe actualizaron {users_updated} registros de usuarios correctamente.")
    else:
        print("\nNo se requirieron cambios.")

print("\nListo. El usuario 'invitado' ahora solo podrá VISUALIZAR datos.")
