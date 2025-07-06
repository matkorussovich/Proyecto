import os
import psycopg2
import logging
from dotenv import load_dotenv

load_dotenv()

# Configuro un logging básico
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Lee los detalles de conexión desde las variables de entorno ---
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT") 
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")

# Verifica que las credenciales de DB estén presentes
if not all([DB_HOST, DB_NAME, DB_USER, DB_PASSWORD]):
    logging.error("¡Error Crítico! Faltan variables de entorno para la conexión a la base de datos (DB_HOST, DB_NAME, DB_USER, DB_PASSWORD) en el archivo .env")
    raise ValueError("Faltan credenciales de base de datos en el archivo .env (DB_HOST, DB_NAME, DB_USER, DB_PASSWORD)")
else:
    # Crea un diccionario con los parámetros para psycopg2.connect
    db_connection_params = {
        "host": DB_HOST,
        "port": DB_PORT,
        "dbname": DB_NAME,
        "user": DB_USER,
        "password": DB_PASSWORD,
    }
    logging.info(f"Parámetros de conexión a BD cargados (Host: {DB_HOST}, Puerto: {DB_PORT}, DB: {DB_NAME}, User: {DB_USER})")


def get_db_connection():
    """
    Establece y devuelve una nueva conexión a la base de datos PostgreSQL.
    Es responsabilidad de quien llama a esta función cerrar la conexión
    cuando ya no se necesite (usando conn.close()).

    Returns:
        psycopg2.connection: Objeto de conexión activa.
                             Devuelve None o lanza excepción si la conexión falla o faltan parámetros.

    Raises:
        ValueError: Si faltan parámetros de conexión en el entorno.
        psycopg2.Error: Si ocurre un error al intentar conectar a la base de datos.
    """
    if db_connection_params is None:
        logging.error("Intento de obtener conexión a BD sin parámetros configurados.")
        raise ValueError("La configuración de la base de datos no está completa. Revisa las variables de entorno.")

    try:
        logging.debug(f"Intentando conectar a PostgreSQL en {DB_HOST}:{DB_PORT}...")
        conn = psycopg2.connect(**db_connection_params)
        logging.debug("Conexión a PostgreSQL establecida con éxito.")
        return conn
    except psycopg2.OperationalError as e:
        logging.error(f"Error Operacional al conectar a PostgreSQL: {e}")
        raise  
    except psycopg2.Error as e:
        logging.error(f"Error general de Psycopg2 al conectar: {e}")
        raise 

