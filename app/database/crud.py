import logging
import psycopg2
from psycopg2 import sql
from datetime import datetime, timedelta, time, timezone
import pytz
from .connection import get_db_connection
import pickle
import requests
import json
import os
from pathlib import Path
from app.notifications.whatsapp import send_whatsapp_message

# Lista global para caché simple de instalaciones (opcional pero útil)
# Se recomienda poblarla al inicio de la aplicación llamando a get_available_facilities_db
ALL_FACILITIES_CACHE = []

# Configuración básica de logging (puedes tener una configuración centralizada)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Lista de feriados de Madrid
FERIADOS_MADRID = [
    "2024-12-25",
    "2025-01-01",
    "2025-01-06",
    "2025-04-17",
    "2025-04-18",
    "2025-05-01",
    "2025-05-02",
    "2025-05-15",
    "2025-07-25",
    "2025-08-15",
    "2025-11-01",
    "2025-11-10",
    "2025-12-06",
    "2025-12-08",
    "2025-12-25",
]

def _get_rain_probability(date_str: str) -> int:
    """Obtiene la probabilidad de lluvia para una fecha específica usando OpenMeteo API."""
    try:
        # Coordenadas de Madrid
        lat = 40.4168
        lon = -3.7038
        
        # Construir URL para la API
        url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&daily=precipitation_probability_max&timezone=Europe%2FMadrid&start_date={date_str}&end_date={date_str}"
        
        response = requests.get(url)
        data = response.json()
        
        # Obtener la probabilidad máxima de precipitación para el día
        rain_prob = data['daily']['precipitation_probability_max'][0]
        
        # Convertir a binario (1 si hay probabilidad de lluvia > 30%, 0 en caso contrario)
        return 1 if rain_prob > 30 else 0
    except Exception as e:
        logging.error(f"Error al obtener probabilidad de lluvia: {e}")
        return 0

def _get_user_booking_history(conn, session_id: str) -> tuple:
    """Obtiene el historial de reservas y cancelaciones de un usuario."""
    try:
        with conn.cursor() as cur:
            # Obtener total de reservas previas
            cur.execute("""
                SELECT COUNT(*) FROM public.reservas 
                WHERE ds_telefono = %s AND ds_estado = 'Confirmada'
            """, (session_id,))
            reservas_previas = cur.fetchone()[0]
            
            # Obtener total de cancelaciones previas
            cur.execute("""
                SELECT COUNT(*) FROM public.reservas 
                WHERE ds_telefono = %s AND ds_estado = 'Cancelada'
            """, (session_id,))
            cancelaciones_previas = cur.fetchone()[0]
            
            return reservas_previas, cancelaciones_previas
    except Exception as e:
        logging.error(f"Error al obtener historial de usuario: {e}")
        return 0, 0

def _calculate_features(conn, id_instalacion: int, date_str: str, time_str: str, session_id: str) -> dict:
    """Calcula todos los features necesarios para el modelo."""
    try:
        # Calcular antelación en días
        fecha_reserva = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        antelacion_dias = (fecha_reserva - datetime.now()).days
        
        # Obtener historial de usuario
        reservas_previas, cancelaciones_previas = _get_user_booking_history(conn, session_id)
        
        # Calcular si es fin de semana
        es_finde = 1 if fecha_reserva.weekday() >= 5 else 0
        
        # Calcular si es horario pico
        hora = fecha_reserva.hour
        es_horario_pico = 1 if 18 <= hora <= 22 else 0
        
        # Calcular si es feriado
        es_feriado = 1 if date_str in FERIADOS_MADRID else 0
        
        # Obtener probabilidad de lluvia
        lluvia = _get_rain_probability(date_str)
        
        return {
            'id_instalacion': id_instalacion,
            'antelacion_dias': antelacion_dias,
            'reservas_previas': reservas_previas,
            'cancelaciones_previas': cancelaciones_previas,
            'es_finde': es_finde,
            'es_horario_pico': es_horario_pico,
            'es_feriado': es_feriado,
            'lluvia': lluvia
        }
    except Exception as e:
        logging.error(f"Error al calcular features: {e}")
        raise

def _predict_cancellation_probability(features: dict) -> float:
    """Realiza la predicción de probabilidad de cancelación usando el modelo."""
    try:
        # Cargar el modelo
        model_path = Path(__file__).parent.parent.parent / 'ML' / 'rf_cancelaciones.pkl'
        with open(model_path, 'rb') as f:
            model = pickle.load(f)
        
        # Preparar los datos en el orden correcto según columnas_modelo.json
        feature_order = ["id_instalacion", "lluvia", "antelacion_dias", "reservas_previas", 
                        "cancelaciones_previas", "es_finde", "es_horario_pico", "es_feriado"]
        X = [[features[feature] for feature in feature_order]]
        
        # Realizar la predicción
        proba = model.predict_proba(X)[0][1]  # Probabilidad de clase 1 (cancelación)
        return float(proba)
    except Exception as e:
        logging.error(f"Error al predecir probabilidad de cancelación: {e}")
        return 0.0

# --- Funciones Auxiliares ---

def _get_facility_id(conn, facility_name: str) -> int | None:
    """Obtiene el ID de una instalación por su nombre. Asume conexión abierta."""
    global ALL_FACILITIES_CACHE
    # Primero verifica caché local para evitar DB hit si ya la tenemos
    if not ALL_FACILITIES_CACHE:
         # Si la caché está vacía, intenta llenarla (esto podría ser redundante si se llama al inicio)
         logging.warning("Caché ALL_FACILITIES vacía, intentando poblar desde _get_facility_id...")
         try:
             with conn.cursor() as cur_cache:
                cur_cache.execute("SELECT ds_nombre FROM public.instalaciones ORDER BY ds_nombre")
                ALL_FACILITIES_CACHE = [row[0] for row in cur_cache.fetchall()]
         except psycopg2.Error as e:
             logging.error(f"Error al intentar poblar caché de instalaciones: {e}")
             # No podemos continuar sin saber las instalaciones válidas
             return None

    # Validación con la caché (case-insensitive)
    found_name = None
    for fac_name in ALL_FACILITIES_CACHE:
        if facility_name.lower() == fac_name.lower():
            found_name = fac_name # Guardamos el nombre con las mayúsculas correctas de la DB
            break

    if not found_name:
         logging.warning(f"Intento de obtener ID para instalación no listada/cacheada: {facility_name}")
         return None

    # Si el nombre es válido, obtenemos su ID
    with conn.cursor() as cur:
        query = sql.SQL("SELECT id_instalacion FROM public.instalaciones WHERE ds_nombre = %s")
        cur.execute(query, (found_name,)) # Usamos el nombre encontrado con mayúsculas correctas
        result = cur.fetchone()
        return result[0] if result else None

# --- Funciones Principales CRUD (para las Tools) ---

def get_available_facilities_db(filtro_tipo: str = None, **kwargs) -> str:
    """
    Obtiene la lista de nombres de instalaciones desde la DB,
    actualiza la caché global y devuelve un string formateado.
    Si se pasa filtro_tipo, filtra por ese tipo (ej: 'padel', 'tenis').
    """
    global ALL_FACILITIES_CACHE
    logging.info(f"get_available_facilities_db recibió: filtro_tipo={filtro_tipo}, kwargs={kwargs}")
    conn = None
    facilities = [] # Lista local para esta ejecución
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT ds_nombre FROM public.instalaciones ORDER BY ds_nombre")
            facilities = [row[0] for row in cur.fetchall()]

        # Aplica el filtro si corresponde
        if filtro_tipo:
            facilities = [f for f in facilities if filtro_tipo.lower() in f.lower()]

        # Actualiza la caché global
        ALL_FACILITIES_CACHE = facilities.copy()  # Usamos copy() para asegurar que no se pierda la referencia
        logging.info(f"Caché ALL_FACILITIES actualizada. Resultado (DB): {', '.join(facilities)}")

        if not facilities:
            return "No hay instalaciones configuradas en la base de datos."
        # Devuelve solo la lista, el LLM la formateará
        return ', '.join(facilities)

    except psycopg2.Error as e:
        logging.error(f"Error al obtener instalaciones: {e}")
        ALL_FACILITIES_CACHE = [] # Limpiar caché en caso de error
        return "ERROR: Problema tecnico DB al listar instalaciones"
    except Exception as e:
        logging.error(f"Error inesperado en get_available_facilities_db: {e}")
        ALL_FACILITIES_CACHE = []
        return "ERROR: Inesperado al listar instalaciones"
    finally:
        if conn:
            conn.close()
            logging.debug("Conexión cerrada en get_available_facilities_db")


def check_availability_db(facility_name: str, date_str: str, time_str: str) -> str:
    """
    Verifica disponibilidad en DB. Devuelve strings estructurados:
    - "ESTADO: Disponible"
    - "ESTADO: Ocupado | Alternativas: HH:MM, HH:MM..."
    - "ESTADO: Ocupado | Sin Alternativas"
    - "ESTADO: Ocupado | Overbooking Posible: {probabilidad}% | Alternativas: HH:MM, HH:MM..."
    - "ERROR: [Mensaje específico]"
    """
    logging.info(f"--- Ejecutando check_availability_db ---")
    logging.info(f"Recibido: Instalación='{facility_name}', Fecha='{date_str}', Hora='{time_str}'")

    # === Variables Configurables ===
    HORA_INICIO_OPERACION = 8
    HORA_FIN_OPERACION = 22
    DURACION_SLOT_MINUTOS = 60
    UMBRAL_OVERBOOKING = 0.65  # 65% de probabilidad de cancelación
    try:
        MADRID_TZ = pytz.timezone('Europe/Madrid')
    except pytz.exceptions.UnknownTimeZoneError:
        logging.error("No se pudo encontrar la zona horaria 'Europe/Madrid'. Usando UTC.")
        MADRID_TZ = pytz.utc
    # ==============================

    conn = None
    try:
        conn = get_db_connection()

        # --- Obtener ID Instalación (usa la caché actualizada) ---
        id_instalacion = _get_facility_id(conn, facility_name)
        if id_instalacion is None:
             opciones_validas = ', '.join(ALL_FACILITIES_CACHE) if ALL_FACILITIES_CACHE else 'ninguna encontrada'
             return f"ERROR: Instalacion no valida | Opciones: {opciones_validas}"

        # --- Procesar Fecha/Hora Solicitada y Validar ---
        try:
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
        booking_id = None
        prob_cancelacion = 0.0
        
        with conn.cursor() as cur:
            query_check = sql.SQL("""
                SELECT r.id_reserva, r.probabilidad_cancelacion
                FROM public.reservas r
                WHERE r.id_instalacion = %s 
                AND r.ds_estado = 'Confirmada'
                AND (r.dt_fechahora_inicio, r.dt_fechahora_fin) OVERLAPS (%s::timestamptz, %s::timestamptz)
            """)
            cur.execute(query_check, (id_instalacion, requested_start_dt, requested_end_dt))
            result = cur.fetchone()
            if result:
                is_requested_slot_booked = True
                booking_id, prob_cancelacion = result

        # --- Generar Respuesta ---
        if not is_requested_slot_booked:
            logging.info(f"Slot solicitado ({time_str}) está DISPONIBLE.")
            return "ESTADO: Disponible"
        else:
            logging.info(f"Slot solicitado ({time_str}) está OCUPADO. Buscando alternativas...")
            # --- Buscar Alternativas ---
            booked_slots = []
            available_slots_str = []
            requested_date = requested_start_dt.date()

            with conn.cursor() as cur:
                query_all = sql.SQL("""
                    SELECT dt_fechahora_inicio, dt_fechahora_fin
                    FROM public.reservas
                    WHERE id_instalacion = %s
                    AND DATE(dt_fechahora_inicio AT TIME ZONE %s) = %s
                    AND ds_estado = 'Confirmada'
                    ORDER BY dt_fechahora_inicio;
                """)
                cur.execute(query_all, (id_instalacion, MADRID_TZ.zone, requested_date))
                booked_slots = cur.fetchall()

            day_start_dt = datetime.combine(requested_date, time(HORA_INICIO_OPERACION, 0))
            day_start_aware = MADRID_TZ.localize(day_start_dt)
            day_end_dt = datetime.combine(requested_date, time(HORA_FIN_OPERACION, 0))
            day_end_aware = MADRID_TZ.localize(day_end_dt)

            current_slot_start = day_start_aware
            while current_slot_start < day_end_aware:
                current_slot_end = current_slot_start + timedelta(minutes=DURACION_SLOT_MINUTOS)
                if current_slot_end > day_end_aware: break
                if current_slot_start < now_madrid:
                    current_slot_start += timedelta(minutes=DURACION_SLOT_MINUTOS); continue

                is_potential_slot_booked = False
                for booked_start, booked_end in booked_slots:
                     if (current_slot_start < booked_end) and (current_slot_end > booked_start):
                        is_potential_slot_booked = True; break
                if not is_potential_slot_booked:
                    available_slots_str.append(current_slot_start.strftime('%H:%M'))
                current_slot_start += timedelta(minutes=DURACION_SLOT_MINUTOS)

            # Formatear respuesta según si hay overbooking posible
            if prob_cancelacion >= UMBRAL_OVERBOOKING:
                if available_slots_str:
                    horas_disponibles = ", ".join(available_slots_str)
                    return f"ESTADO: Ocupado | Overbooking Posible: {int(prob_cancelacion*100)}% | Alternativas: {horas_disponibles}"
                else:
                    return f"ESTADO: Ocupado | Overbooking Posible: {int(prob_cancelacion*100)}% | Sin Alternativas"
            else:
                if available_slots_str:
                    horas_disponibles = ", ".join(available_slots_str)
                    return f"ESTADO: Ocupado | Alternativas: {horas_disponibles}"
                else:
                    return "ESTADO: Ocupado | Sin Alternativas"

    except psycopg2.Error as e:
        logging.error(f"Error de base de datos en check_availability: {e}")
        if conn: conn.rollback()
        return "ERROR: Problema tecnico DB"
    except Exception as e:
        logging.error(f"Error inesperado en check_availability: {e}")
        import traceback; logging.error(traceback.format_exc())
        return "ERROR: Inesperado"
    finally:
        if conn:
            conn.close()
            logging.debug("Conexión cerrada en check_availability_db")


def make_reservation_db(facility_name: str, date_str: str, time_str: str, user_name: str, session_id: str = None) -> str:
    """Realiza una reserva en la DB tras verificar disponibilidad."""
    logging.info(f"--- Ejecutando make_reservation_db ---")
    logging.info(f"Recibido: Inst: '{facility_name}', Fecha: '{date_str}', Hora: '{time_str}', Usr: '{user_name}', Session: '{session_id}'")

    # Validar que tenemos un teléfono válido
    if not session_id:
        logging.error("Error: No se proporcionó número de teléfono (session_id)")
        return "ERROR: Reserva Fallida - Se requiere un número de teléfono válido para realizar la reserva."

    # === Variables Configurables (podrían compartirse o venir de DB) ===
    DURACION_SLOT_MINUTOS = 60
    try:
        MADRID_TZ = pytz.timezone('Europe/Madrid')
    except pytz.exceptions.UnknownTimeZoneError:
        logging.error("No se pudo encontrar la zona horaria 'Europe/Madrid'. Usando UTC.")
        MADRID_TZ = pytz.utc
    # ====================================================================

    conn = None
    try:
        # PASO 1: Verificar Disponibilidad PRIMERO usando la función actualizada
        availability_status = check_availability_db(facility_name, date_str, time_str)

        # Determinar si es overbooking basado en la respuesta
        is_overbooking = availability_status.startswith("ESTADO: Ocupado | Overbooking Posible")
        
        if not is_overbooking and availability_status != "ESTADO: Disponible":
            logging.warning(f"Intento de reserva fallido por no disponibilidad/error: {availability_status}")
            return f"ERROR: Reserva Fallida - {availability_status}"

        # PASO 2: Si está disponible o es overbooking válido, proceder a insertar
        conn = get_db_connection()
        id_instalacion = _get_facility_id(conn, facility_name)

        if id_instalacion is None:
             return f"ERROR: Reserva Fallida - No se encontró ID para '{facility_name}' (esto no debería pasar)."

        # PASO 3: Preparar datos para INSERT
        try:
            naive_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
            start_dt = MADRID_TZ.localize(naive_dt)
            end_dt = start_dt + timedelta(minutes=DURACION_SLOT_MINUTOS)
            now = datetime.now(MADRID_TZ)
        except ValueError:
            logging.error(f"Error de formato al parsear fecha/hora para INSERT: {date_str} {time_str}")
            return "ERROR: Reserva Fallida - Formato de fecha/hora inválido para guardar."

        # PASO 4: Calcular features y probabilidad de cancelación
        try:
            features = _calculate_features(conn, id_instalacion, date_str, time_str, session_id)
            prob_cancelacion = _predict_cancellation_probability(features)
            logging.info(f"Probabilidad de cancelación calculada: {prob_cancelacion:.2%}")
        except Exception as e:
            logging.error(f"Error al calcular probabilidad de cancelación: {e}")
            prob_cancelacion = 0.0
            features = {
                'antelacion_dias': 0,
                'reservas_previas': 0,
                'cancelaciones_previas': 0,
                'es_finde': 0,
                'es_horario_pico': 0,
                'es_feriado': 0,
                'lluvia': 0
            }

        # PASO 5: Ejecutar INSERT
        with conn.cursor() as cur:
            # Si es overbooking, necesitamos obtener el ID de la reserva original
            original_booking_id = None
            if is_overbooking:
                query_original = sql.SQL("""
                    SELECT id_reserva
                    FROM public.reservas
                    WHERE id_instalacion = %s 
                    AND ds_estado = 'Confirmada'
                    AND (dt_fechahora_inicio, dt_fechahora_fin) OVERLAPS (%s::timestamptz, %s::timestamptz)
                """)
                cur.execute(query_original, (id_instalacion, start_dt, end_dt))
                result = cur.fetchone()
                if result:
                    original_booking_id = result[0]

            query = sql.SQL("""
                INSERT INTO public.reservas (
                    id_instalacion, 
                    ds_nombre_cliente, 
                    ds_telefono, 
                    dt_fechahora_inicio, 
                    dt_fechahora_fin, 
                    dt_fechahora_creacion,
                    ds_estado, 
                    ds_comentarios,
                    es_simulado,
                    probabilidad_cancelacion,
                    lluvia,
                    antelacion_dias,
                    reservas_previas,
                    cancelaciones_previas,
                    es_finde,
                    es_horario_pico,
                    es_feriado,
                    es_overbooking,
                    id_reserva_original
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                RETURNING id_reserva
            """)
            cur.execute(query, (
                id_instalacion,
                user_name,
                session_id,
                start_dt,
                end_dt,
                now,  # dt_fechahora_creacion
                'Pendiente' if is_overbooking else 'Confirmada',  # Estado especial para overbooking
                None,  # ds_comentarios
                False,  # es_simulado
                prob_cancelacion,
                bool(features['lluvia']),  # Convertir a boolean para la columna lluvia
                features['antelacion_dias'],
                features['reservas_previas'],
                features['cancelaciones_previas'],
                features['es_finde'],
                features['es_horario_pico'],
                features['es_feriado'],
                is_overbooking,  # es_overbooking
                original_booking_id  # id_reserva_original
            ))
            booking_id = cur.fetchone()[0]
            conn.commit() 
            
            if is_overbooking:
                logging.info(f"Resultado (DB): Overbooking {booking_id} creado para {user_name}")
                return f"OVERBOOKING_OK: Overbooking {booking_id} creado para {user_name}. Se confirmará si la reserva original se cancela."
            else:
                logging.info(f"Resultado (DB): Reserva {booking_id} exitosa para {user_name}")
                return f"RESERVA_OK: Reserva {booking_id} confirmada para {user_name}."

    except psycopg2.Error as e:
        logging.error(f"Error de base de datos al realizar reserva: {e}")
        if conn: conn.rollback() # Deshacer si falla la inserción
        return "ERROR: Problema tecnico DB al reservar"
    except Exception as e:
        logging.error(f"Error inesperado en make_reservation_db: {e}")
        if conn: conn.rollback()
        import traceback; logging.error(traceback.format_exc())
        return "ERROR: Inesperado al reservar"
    finally:
        if conn:
            conn.close()
            logging.debug("Conexión cerrada en make_reservation_db")


def cancel_reservation_db(session_id: str = None, **kwargs) -> str:
    """
    Cancela una reserva existente. Busca reservas futuras asociadas al número de teléfono
    y solicita confirmación o elección según corresponda.
    """
    logging.info(f"--- Ejecutando cancel_reservation_db ---")
    logging.info(f"Usando teléfono: {session_id}")

    if not session_id:
            logging.error("Error en cancel_reservation_db: No se proporcionó session_id.")
            return "ERROR_CANCELACION: No se pudo buscar las reservas. Falta el identificador de sesión."


    try:
        MADRID_TZ = pytz.timezone('Europe/Madrid')
    except pytz.exceptions.UnknownTimeZoneError:
        logging.error("No se pudo encontrar la zona horaria 'Europe/Madrid'. Usando UTC.")
        MADRID_TZ = pytz.utc

    conn = None
    try:
        conn = get_db_connection()
        now = datetime.now(MADRID_TZ)

        # Buscar reservas futuras
        with conn.cursor() as cur:
            query = sql.SQL("""
                SELECT r.id_reserva, i.ds_nombre, r.dt_fechahora_inicio
                FROM public.reservas r
                JOIN public.instalaciones i ON r.id_instalacion = i.id_instalacion
                WHERE r.ds_telefono = %s
                AND r.ds_estado = 'Confirmada'
                AND r.dt_fechahora_inicio > %s
                ORDER BY r.dt_fechahora_inicio
            """)
            cur.execute(query, (session_id, now))
            future_bookings = cur.fetchall()

            if not future_bookings:
                return "SIN_RESERVAS_ACTIVAS: No encontré reservas futuras activas asociadas a tu número de teléfono."

            if len(future_bookings) == 1:
                # Solo una reserva encontrada
                booking_id, facility_name, start_dt = future_bookings[0]
                # Corrección: asegurar zona horaria Madrid
                if start_dt.tzinfo is None:
                    start_dt = MADRID_TZ.localize(start_dt)
                else:
                    start_dt = start_dt.astimezone(MADRID_TZ)
                return f"CONFIRMACION_NECESARIA: Se encontró una reserva para {facility_name} el {start_dt.strftime('%Y-%m-%d')} a las {start_dt.strftime('%H:%M')} (ID: {booking_id}) asociada a tu número. ¿Confirmas que deseas cancelarla (responde con 'Sí, cancelar reserva {booking_id}' o 'No')?"

            # Múltiples reservas encontradas
            bookings_list = []
            for idx, (bid, facility, start) in enumerate(future_bookings, 1):
                # Corrección: asegurar zona horaria Madrid
                if start.tzinfo is None:
                    start = MADRID_TZ.localize(start)
                else:
                    start = start.astimezone(MADRID_TZ)
                bookings_list.append(f"{idx}. ID {bid} para {facility} el {start.strftime('%Y-%m-%d')} a las {start.strftime('%H:%M')}")
            
            return f"MULTIPLES_RESERVAS: Encontré estas reservas asociadas a ti: {' '.join(bookings_list)} Por favor, dime el ID de la reserva que quieres cancelar."

    except psycopg2.Error as e:
        logging.error(f"Error de base de datos al buscar reservas: {e}")
        if conn: conn.rollback()
        return "ERROR_CANCELACION: No se pudo buscar las reservas. Motivo: Error técnico en la base de datos."
    except Exception as e:
        logging.error(f"Error inesperado en cancel_reservation_db: {e}")
        if conn: conn.rollback()
        import traceback
        logging.error(traceback.format_exc())
        return "ERROR_CANCELACION: No se pudo buscar las reservas. Motivo: Error inesperado."
    finally:
        if conn:
            conn.close()
            logging.debug("Conexión cerrada en cancel_reservation_db")

def confirm_cancel_reservation(booking_id: str, session_id: str = None, **kwargs) -> str:
    """
    Confirma y ejecuta la cancelación de una reserva específica.
    Si la reserva cancelada tiene overbookings pendientes, los confirma automáticamente y envía una notificación por WhatsApp.
    """
    logging.info(f"--- Ejecutando confirm_cancel_reservation ---")
    logging.info(f"Recibido: Booking ID='{booking_id}', Teléfono='{session_id}'")

    try:
        MADRID_TZ = pytz.timezone('Europe/Madrid')
    except pytz.exceptions.UnknownTimeZoneError:
        logging.error("No se pudo encontrar la zona horaria 'Europe/Madrid'. Usando UTC.")
        MADRID_TZ = pytz.utc

    conn = None
    try:
        conn = get_db_connection()
        now = datetime.now(MADRID_TZ)

        # Verificar que la reserva existe y cumple las condiciones
        with conn.cursor() as cur:
            query_check = sql.SQL("""
                SELECT r.id_reserva, i.ds_nombre, r.dt_fechahora_inicio
                FROM public.reservas r
                JOIN public.instalaciones i ON r.id_instalacion = i.id_instalacion
                WHERE r.id_reserva = %s
                AND r.ds_telefono = %s
                AND r.ds_estado = 'Confirmada'
                AND r.dt_fechahora_inicio > %s
            """)
            cur.execute(query_check, (booking_id, session_id, now))
            booking = cur.fetchone()

            if not booking:
                return "ERROR_CANCELACION: No se pudo cancelar la reserva. Motivo: La reserva no existe, no pertenece a tu número, ya ha pasado o ya está cancelada."

            # Buscar overbookings pendientes para notificar
            query_overbookings = sql.SQL("""
                SELECT r.id_reserva, r.ds_nombre_cliente, r.ds_telefono, i.ds_nombre, r.dt_fechahora_inicio
                FROM public.reservas r
                JOIN public.instalaciones i ON r.id_instalacion = i.id_instalacion
                WHERE r.id_reserva_original = %s
                AND r.ds_estado = 'Pendiente'
                AND r.es_overbooking = true
            """)
            cur.execute(query_overbookings, (booking_id,))
            overbookings = cur.fetchall()

            # Si todo está bien, proceder con la cancelación
            query_cancel = sql.SQL("""
                UPDATE public.reservas
                SET ds_estado = 'Cancelada'
                WHERE id_reserva = %s
            """)
            cur.execute(query_cancel, (booking_id,))

            # Confirmar overbookings pendientes y enviar notificaciones
            if overbookings:
                overbooking_ids = [o[0] for o in overbookings]
                query_confirm_overbookings = sql.SQL("""
                    UPDATE public.reservas
                    SET ds_estado = 'Confirmada'
                    WHERE id_reserva = ANY(%s)
                """)
                cur.execute(query_confirm_overbookings, (overbooking_ids,))
                
                # Enviar notificaciones
                for ov_id, ov_user, ov_phone, ov_facility, ov_start_dt in overbookings:
                    try:
                        # Corrección: asegurar zona horaria Madrid
                        if ov_start_dt.tzinfo is None:
                            ov_start_dt = MADRID_TZ.localize(ov_start_dt)
                        else:
                            ov_start_dt = ov_start_dt.astimezone(MADRID_TZ)
                        message_text = f"¡Buenas noticias, {ov_user}! Tu reserva pendiente para la instalación '{ov_facility}' el día {ov_start_dt.strftime('%Y-%m-%d')} a las {ov_start_dt.strftime('%H:%M')} ha sido confirmada. ¡Te esperamos!"
                        send_whatsapp_message(ov_phone, message_text)
                    except Exception as e:
                        logging.error(f"No se pudo enviar la notificación de overbooking confirmado para la reserva {ov_id}: {e}")
                        # No detener el proceso, solo loguear el error

            conn.commit()

            # Formatear mensaje de éxito
            facility_name = booking[1]
            start_dt = booking[2]
            # Corrección: asegurar zona horaria Madrid
            if start_dt.tzinfo is None:
                start_dt = MADRID_TZ.localize(start_dt)
            else:
                start_dt = start_dt.astimezone(MADRID_TZ)
            return f"RESERVA_CANCELADA: La reserva con ID {booking_id} para {facility_name} el {start_dt.strftime('%Y-%m-%d')} a las {start_dt.strftime('%H:%M')} ha sido cancelada exitosamente."

    except psycopg2.Error as e:
        logging.error(f"Error de base de datos al cancelar reserva: {e}")
        if conn: conn.rollback()
        return "ERROR_CANCELACION: No se pudo cancelar la reserva. Motivo: Error técnico en la base de datos."
    except Exception as e:
        logging.error(f"Error inesperado en confirm_cancel_reservation: {e}")
        if conn: conn.rollback()
        import traceback
        logging.error(traceback.format_exc())
        return "ERROR_CANCELACION: No se pudo cancelar la reserva. Motivo: Error inesperado."
    finally:
        if conn:
            conn.close()
            logging.debug("Conexión cerrada en confirm_cancel_reservation")