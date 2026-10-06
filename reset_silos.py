from app import app, db, Silo, InventarioSilo

with app.app_context():
    # Resetear tipo_producto a NULL para todos los silos
    silos = Silo.query.all()
    for silo in silos:
        silo.tipo_producto = None
    
    db.session.commit()
    print(f"✅ Se reseteó el tipo de producto para {len(silos)} silos!")
    
    # Verificar
    print("\nEstado de silos:")
    for silo in silos:
        inventario = InventarioSilo.query.filter_by(id_silo=silo.id_silo).all()
        galones = sum(item.galones for item in inventario)
        print(f"  - {silo.nombre_silo}: Tipo={silo.tipo_producto}, Inventario={galones} gal")