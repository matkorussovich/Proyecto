import logging 
import os
import psycopg2
from psycopg2 import sql
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_pinecone import PineconeVectorStore
from datetime import datetime, timedelta, time
import pytz

# --- Configuración Conexión Base de Datos ---
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT") 
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")

# Verifica que las credenciales de DB estén presentes
if not all([DB_HOST, DB_NAME, DB_USER, DB_PASSWORD]):
    raise ValueError("Faltan credenciales de base de datos en el archivo .env (DB_HOST, DB_NAME, DB_USER, DB_PASSWORD)")

# Configura un logger básico (opcional, pero buena práctica)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Constantes para RAG ---
PINECONE_INDEX_NAME = "kb-tfm" 
EMBEDDING_MODEL_NAME = "intfloat/multilingual-e5-large"

# Inicializar ALL_FACILITIES al importar el módulo
ALL_FACILITIES = []

def get_facility_id(conn, facility_name: str) -> int | None:
    """Obtiene el ID de una instalación por su nombre."""
    # Asegurarse de que ALL_FACILITIES esté poblada si aún no lo está
    if not ALL_FACILITIES:
        get_available_facilities(conn)  # Pasar la conexión existente

    # Comprobación adicional (aunque Pydantic ya valida)
    if facility_name not in ALL_FACILITIES:
        logging.warning(f"Intento de obtener ID para instalación no listada: {facility_name}")
        return None

    with conn.cursor() as cur:
        query = sql.SQL("SELECT id_instalacion FROM public.instalaciones WHERE ds_nombre = %s")
        cur.execute(query, (facility_name,))
        result = cur.fetchone()
        return result[0] if result else None

def check_availability(facility_name: str, date_str: str, time_str: str) -> str:
    """
    Verifica disponibilidad en DB. Devuelve strings estructurados:
    - "ESTADO: Disponible"
    - "ESTADO: Ocupado | Alternativas: HH:MM, HH:MM..."
    - "ESTADO: Ocupado | Sin Alternativas"
    - "ERROR: [Mensaje específico]"
    """
    logging.info(f"--- Ejecutando check_availability v2 (DB+Alternativas) ---")
    logging.info(f"Recibido: Instalación='{facility_name}', Fecha='{date_str}', Hora='{time_str}'")

    # === Variables Configurables ===
    # (Puedes moverlas fuera de la función si prefieres definirlas globalmente)
    HORA_INICIO_OPERACION = 8  # 8 AM (Formato 24h)
    HORA_FIN_OPERACION = 22  # 10 PM (Los slots deben TERMINAR antes de esta hora)
    DURACION_SLOT_MINUTOS = 60 # Duración estándar de una reserva en minutos
    MADRID_TZ = pytz.timezone('Europe/Madrid') # Zona horaria para las operaciones
    # ==============================

    try:
        conn = get_db_connection()
        id_instalacion = get_facility_id(conn, facility_name)

        if id_instalacion is None:
            # Si get_facility_id devuelve None (porque no está en ALL_FACILITIES actualizada)
            return f"ERROR: Instalacion no valida | Opciones: {', '.join(ALL_FACILITIES) if ALL_FACILITIES else ' (no disponibles)'}"

        # --- Procesar Fecha/Hora Solicitada y Validar ---
        try:
            # Combinar fecha/hora y hacerla consciente de la zona horaria
            naive_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
            requested_start_dt = MADRID_TZ.localize(naive_dt)
            requested_end_dt = requested_start_dt + timedelta(minutes=DURACION_SLOT_MINUTOS)
            now_madrid = datetime.now(MADRID_TZ)
        except ValueError:
            logging.error(f"Error de formato al parsear fecha/hora: {date_str} {time_str}")
            return "ERROR: Formato invalido"

        if requested_start_dt < now_madrid:
            logging.warning("Intento de consulta en el pasado.")
            return f"ERROR: Fecha pasada"

        # --- Comprobar el Slot Específico Solicitado ---
        is_requested_slot_booked = False
        with conn.cursor() as cur:
            query_check = sql.SQL("""
                SELECT EXISTS (
                    SELECT 1
                    FROM public.reservas
                    WHERE id_instalacion = %s
                    AND ds_estado = 'Confirmada'
                    AND dt_fechahora_fin > %s 
                    AND dt_fechahora_inicio < %s
                )
            """)
            # Pasamos datetimes conscientes de zona horaria
            cur.execute(query_check, (id_instalacion, requested_start_dt, requested_end_dt))
            is_requested_slot_booked = cur.fetchone()[0] # EXISTS devuelve True o False: TRUE si esta ocupado.

        # --- Generar Respuesta ---
        if not is_requested_slot_booked:
            logging.info(f"Slot solicitado ({time_str}) está DISPONIBLE.")
            return "ESTADO: Disponible"
        else:
            logging.info(f"Slot solicitado ({time_str}) está OCUPADO. Buscando alternativas...")

            # --- Buscar Alternativas (si el slot solicitado está ocupado) ---
            booked_slots = []
            available_slots_str = []
            requested_date = requested_start_dt.date() # Solo la fecha

            with conn.cursor() as cur:
                # Obtenemos todas las reservas confirmadas para ese día y esa instalación
                query_all = sql.SQL("""
                    SELECT dt_fechahora_inicio, dt_fechahora_fin
                    FROM public.reservas
                    WHERE id_instalacion = %s
                    AND DATE(dt_fechahora_inicio AT TIME ZONE %s) = %s -- Compara fechas en la zona horaria correcta
                    AND ds_estado = 'Confirmada'
                    ORDER BY dt_fechahora_inicio;
                """)
                cur.execute(query_all, (id_instalacion, MADRID_TZ.zone, requested_date))
                booked_slots = cur.fetchall() # Lista de tuplas (inicio, fin)

            # Definir inicio y fin del día operativo en la zona horaria correcta
            day_start_time = datetime.combine(requested_date, time(HORA_INICIO_OPERACION, 0), tzinfo=MADRID_TZ)
            day_end_time = datetime.combine(requested_date, time(HORA_FIN_OPERACION, 0), tzinfo=MADRID_TZ)

            # Iterar por todos los posibles slots del día
            current_slot_start = day_start_time
            while current_slot_start < day_end_time:
                current_slot_end = current_slot_start + timedelta(minutes=DURACION_SLOT_MINUTOS)
                # El slot debe terminar ANTES de la hora de cierre
                if current_slot_end > day_end_time:
                    break

                # Comprobar si este slot potencial está en el pasado (respecto a AHORA)
                if current_slot_start < now_madrid:
                    current_slot_start += timedelta(minutes=DURACION_SLOT_MINUTOS) # Avanza al siguiente slot
                    continue # Saltar slots pasados

                # Comprobar si este slot potencial se solapa con alguna reserva existente
                is_potential_slot_booked = False
                for booked_start, booked_end in booked_slots:
                    # Asegurarse de que las horas de la BD son conscientes de la zona horaria (Postgres con TIMESTAMPTZ lo hace)
                    # Hacemos la comprobación de solapamiento
                    if (current_slot_start < booked_end) and (current_slot_end > booked_start):
                        is_potential_slot_booked = True
                        break # Ya sabemos que está ocupado, no hace falta comprobar más reservas

                if not is_potential_slot_booked:
                    # Si no está ocupado, lo añadimos a la lista de disponibles
                    available_slots_str.append(current_slot_start.strftime('%H:%M'))

                # Avanzar al siguiente slot potencial
                # (Podríamos hacerlo más eficiente saltando hasta el final del slot ocupado,
                # pero esto es más simple de empezar)
                current_slot_start += timedelta(minutes=DURACION_SLOT_MINUTOS)

            # Formatear la respuesta final con alternativas
            if available_slots_str:
                horas_disponibles = ", ".join(available_slots_str)
                logging.info(f"Alternativas encontradas: {horas_disponibles}")
                return f"ESTADO: Ocupado | Alternativas: {horas_disponibles}"

            else:
                logging.info("No se encontraron alternativas para ese día.")
                return "ESTADO: Ocupado | Sin Alternativas"


    except psycopg2.Error as e:
        logging.error(f"Error de base de datos en check_availability: {e}")
        # Intentar deshacer transacción si algo falló, aunque aquí solo leemos
        if conn: conn.rollback()
        return "ERROR: Problema tecnico DB"
    except Exception as e:
        # Captura otros errores (ej: pytz, configuración)
        logging.error(f"Error inesperado en check_availability: {e}")
        import traceback
        logging.error(traceback.format_exc())
        return "ERROR: Inesperado"
    finally:
        if conn:
            conn.close()
            logging.debug("Conexión a BD cerrada.")


def make_reservation(facility_name: str, date_str: str, time_str: str, user_name: str) -> str:
    """
    Registra una nueva reserva para una instalación, fecha, hora y usuario específicos.
    Primero verifica si está libre. Si lo está, la registra.
    Los argumentos ya han sido validados por Pydantic antes de llamar a esta función.
    """
    logging.info(f"--- Ejecutando make_reservation ---")
    logging.info(f"Recibido: Instalación='{facility_name}', Fecha='{date_str}', Hora='{time_str}', Usuario='{user_name}'")

    # === Variables Configurables (deben coincidir con check_availability) ===
    DURACION_SLOT_MINUTOS = 60  # Duración estándar de una reserva en minutos
    MADRID_TZ = pytz.timezone('Europe/Madrid')  # Zona horaria para las operaciones
    # ======================================================================

    conn = None  # Inicializar conn a None

    if facility_name not in ALL_FACILITIES:
        logging.warning(f"Intento de reservar instalación no existente: {facility_name}")
        return f"Lo siento, la instalación '{facility_name}' no existe en nuestro complejo. No se puede reservar."

    try:
        conn = get_db_connection()
        requested_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        current_dt = datetime.now()
        if requested_dt < current_dt:
            logging.warning(f"Intento de reserva en el pasado: {date_str} {time_str}")
            return f"Lo siento, no puedes reservar para una fecha u hora que ya ha pasado ({date_str} {time_str})."
    except ValueError:
        logging.error("Error inesperado de formato de fecha/hora DENTRO de make_reservation.")
        return "Error interno al procesar la fecha/hora."

    # Verificar disponibilidad
    resultado = check_availability(facility_name, date_str, time_str)
    if resultado == 1:
        logging.info(f"Resultado: Falló - Ese turno ya estaba ocupado!")
        return f"Error al reservar: La instalación '{facility_name}' ya estaba ocupada el {date_str} a las {time_str}."

    logging.info("Verificación de disponibilidad exitosa, procediendo a insertar en BD...")

    try:
        with conn.cursor() as cur:
            # Consulta SQL para insertar la reserva
            query_insert = sql.SQL("""
                INSERT INTO public.reservas (
                    id_instalacion, ds_nombre_cliente, dt_fechahora_inicio,
                    dt_fechahora_fin, dt_fechahora_creacion, ds_estado, ds_comentarios
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id_reserva;
            """)

            id_instalacion = get_facility_id(conn, facility_name)  # Ahora pasamos conn como primer argumento
            requested_start_dt = MADRID_TZ.localize(requested_dt)
            requested_end_dt = requested_start_dt + timedelta(minutes=DURACION_SLOT_MINUTOS)
            created_at = datetime.now(MADRID_TZ)

            cur.execute(query_insert, (
                id_instalacion,
                user_name,
                requested_start_dt,
                requested_end_dt,
                created_at,
                'Confirmada',
                ''
            ))

            # new_reservation_id = cur.fetchone()[0]
            conn.commit()

        logging.info(f"Reserva exitosa registrada en BD para {user_name}")
        return f"¡Reserva confirmada! La instalación '{facility_name}' ha sido reservada a nombre de '{user_name}' para el {date_str} a las {time_str}."

    except psycopg2.Error as e:
        logging.error(f"Error de base de datos al intentar insertar la reserva: {e}")
        if conn:
            conn.rollback()
        return "Lo siento, hubo un problema técnico al intentar registrar la reserva en la base de datos."

    except Exception as e:
        logging.error(f"Error inesperado durante la inserción de la reserva: {e}")
        import traceback
        logging.error(traceback.format_exc())
        return "Lo siento, ocurrió un error inesperado al procesar la reserva."

    finally:
        if conn:
            conn.close()
            logging.debug("Conexión a BD cerrada.")



def get_db_connection():
    """Establece y devuelve una conexión a la base de datos."""
    try:
        conn = psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD
        )
        return conn
    except psycopg2.Error as e:
        logging.error(f"Error al conectar a la base de datos PostgreSQL: {e}")
        raise


def get_available_facilities(conn=None) -> list:
    """Obtiene la lista de instalaciones desde la base de datos."""
    logging.info("--- Ejecutando get_available_facilities (DB) ---")
    try:
        if conn is None:
            conn = get_db_connection()
        
        with conn.cursor() as cur:
            cur.execute("SELECT ds_nombre FROM public.instalaciones ORDER BY ds_nombre")
            facilities = [row[0] for row in cur.fetchall()]
            
            # Actualizar ALL_FACILITIES global
            global ALL_FACILITIES
            ALL_FACILITIES = facilities
            
            if not facilities:
                return []
            return facilities
    except psycopg2.Error as e:
        logging.error(f"Error al obtener instalaciones: {e}")
        return []
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception as e:
                logging.error(f"Error al cerrar la conexión: {e}")


# === Función para RAG ===
# (Nota: Inicializar embeddings y vectorstore aquí CADA VEZ es ineficiente, idealmente se haría una vez fuera. Pero para empezar, funciona.)
def buscar_info_complejo(query: str) -> str:
    """Busca información relevante en la base de conocimiento del complejo deportivo para responder la pregunta del usuario."""
    print(f"\n--- Ejecutando RAG Tool: Buscando info para '{query}' ---")
    try:
        # Inicializar embeddings (debe coincidir con la carga)
        print("Inicializando embeddings para búsqueda...")
        embeddings = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL_NAME)

        # Conectar al índice existente
        print(f"Conectando a Pinecone (Índice: {PINECONE_INDEX_NAME})...")
        vectorstore = PineconeVectorStore.from_existing_index(
            index_name=PINECONE_INDEX_NAME,
            embedding=embeddings
        )

        # Crear retriever y buscar
        retriever = vectorstore.as_retriever(search_kwargs={'k': 3}) # Obtener los 3 fragmentos más relevantes
        print("Recuperando fragmentos relevantes...")
        results = retriever.invoke(query)

        if not results:
            print("RAG: No se encontraron fragmentos relevantes.")
            return "No encontré información específica sobre eso en la base de conocimiento del complejo."
        else:
            # Formatear los resultados para el LLM
            context = "\n\n---\n\n".join([doc.page_content for doc in results])
            print(f"RAG: Contexto encontrado:\n{context[:500]}...") # Imprime parte del contexto para debug
            return f"Aquí tienes información relevante encontrada en la base de conocimiento del complejo:\n{context}"

    except Exception as e:
        print(f"ERROR en la herramienta RAG 'buscar_info_complejo': {e}")
        return "Lo siento, tuve un problema al buscar información en la base de conocimiento."