# Sistema Gestor de Silos para Productos Cítricos



##Requisitos Previos

- **Python 3.10+**
- **XAMPP** (o cualquier servidor con MySQL)
- **Pip** (gestor de paquetes de Python)

## Instalación y Configuración

### 1. Preparar la Base de Datos (XAMPP)

1. Abre el **Panel de Control de XAMPP** e inicia los módulos **Apache** y **MySQL**.
2. Ve a [http://localhost/phpmyadmin](http://localhost/phpmyadmin).
3. Crea una nueva base de datos llamada `sistema_silos`.
4. (Opcional) Puedes importar el archivo `database.sql` si prefieres hacerlo manualmente, aunque el sistema lo hará automáticamente al iniciar por primera vez con `init_db.py`.

### 2. Configurar el Entorno Python

1. Clona o descarga este repositorio en tu carpeta de preferencia.
2. Abre una terminal en la carpeta del proyecto.
3. (Recomendado) Crea un entorno virtual:
   ```bash
   python -m venv venv
   venv\Scripts\activate
   ```
4. Instala las dependencias:
   ```bash
   pip install -r requirements.txt
   ```

### 3. Configurar Variables de Entorno

Edita el archivo `.env` en la raíz del proyecto para que coincida con tu configuración de XAMPP:

```env
DB_USER=root
DB_PASSWORD=
DB_HOST=localhost
DB_NAME=sistema_silos
SECRET_KEY=dev_key_for_session_management
PORT=5000
DEBUG=True
```

### 4. Inicializar la Base de Datos

Ejecuta el script de inicialización para crear las tablas y los usuarios por defecto:

```bash
python init_db.py
```

### 5. Ejecutar la Aplicación

Inicia el servidor de desarrollo:

```bash
python app.py
```

Accede a la aplicación en: [http://localhost:5000](http://localhost:5000)

## Usuarios

Al ejecutar `init_db.py` por primera vez se crean los usuarios `admin`, `capturista` e `invitado` con contraseñas aleatorias que se muestran en consola. Cada usuario deberá cambiar su contraseña en el primer inicio de sesión.

> **Importante:** No existen contraseñas por defecto. La contraseña temporal se genera al crear el usuario y debe cambiarse inmediatamente.

## Funcionalidades Principales

- **Dashboard:** Visualización de ocupación de silos en tiempo real.
- **Entradas:** Registro de producto con parámetros de calidad (Brix, Relación, Pulpa).
- **Salidas (LIFO):** El sistema descuenta automáticamente los lotes más recientes.
- **Historial:** Registro completo de movimientos exportable a Excel.
- **Gestión de Usuarios:** Panel de administración para crear y editar accesos.

##Estructura del Proyecto

- `app.py`: Aplicación principal (Flask).
- `models.py`: Definición de la base de datos (SQLAlchemy).
- `templates/`: Archivos HTML (Jinja2).
- `static/`: Archivos CSS y JavaScript.
- `init_db.py`: Script de configuración inicial.
- `database.sql`: Respaldo del esquema SQL.

---
py -3.11 app.py
© 2026 Sistema Gestor de Silos
