
from app import app, db, Silo

with app.app_context():
    # Eliminar silos existentes (si hay)
    Silo.query.delete()
    db.session.commit()
    
    # Insertar los 13 silos (sin tipo de producto preasignado)
    silos_data = [
        ('Silo 1', 6213.00, 119.48, None),
        ('Silo 2', 6213.00, 119.48, None),
        ('Silo 3', 6213.00, 119.48, None),
        ('Silo 4', 6213.00, 119.48, None),
        ('Silo 5', 8548.00, 164.38, None),
        ('Silo 6', 8548.00, 164.38, None),
        ('Silo 7', 8548.00, 164.38, None),
        ('Silo 12', 9093.00, 174.86, None),
        ('Silo 13', 9093.00, 174.86, None),
        ('Silo 14', 9093.00, 174.86, None),
        ('Silo 15', 9093.00, 174.86, None),
        ('Silo 16', 9093.00, 174.86, None),
        ('Silo 17', 9093.00, 174.86, None)
    ]
    
    for nombre, cap_g, cap_b, tipo in silos_data:
        silo = Silo(
            nombre_silo=nombre, 
            capacidad_gal=cap_g, 
            capacidad_barriles=cap_b, 
            tipo_producto=tipo,
            estado='activo'
        )
        db.session.add(silo)
    
    db.session.commit()
    print(f"✅ Se insertaron {len(silos_data)} silos correctamente!")
    
    # Verificar
    silos = Silo.query.filter_by(estado='activo').order_by(Silo.nombre_silo).all()
    print("\nListado de silos:")
    for silo in silos:
        print(f"  - {silo.nombre_silo} ({silo.tipo_producto})")
