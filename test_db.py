print("Testing Python...")
try:
    from app import app, db, Silo
    print("✅ Import successful!")
    
    with app.app_context():
        silos = Silo.query.all()
        print(f"✅ Found {len(silos)} silos in database")
        
        for silo in silos[:5]:  # Show first 5
            print(f"  - {silo.nombre_silo}: tipo={silo.tipo_producto}")
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()