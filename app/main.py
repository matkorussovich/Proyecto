from dotenv import load_dotenv
import logging
from fastapi import FastAPI, BackgroundTasks, Request, Response
from langchain.agents import AgentExecutor
from langchain_core.runnables.history import RunnableWithMessageHistory
from contextlib import asynccontextmanager
from app.agente.agent_setup import inicializar_componentes_base_agente, get_session_history
from app.whatsapp.handler import WhatsAppHandler
from app.rag.retriever import initialize_embeddings
import os
import asyncio 

# ---  Caché  de IDs de mensajes procesados ---
processed_message_ids = set()
# Un Lock para evitar condiciones de carrera al modificar el set desde múltiples tareas async
processed_ids_lock = asyncio.Lock()
# Límite de tamaño
MAX_CACHE_SIZE = 10000
# -----------------------------------------------------------

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
load_dotenv()

main_agent_handler = None
whatsapp_handler_global  = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global main_agent_handler, whatsapp_handler_global
    try:
        # 1. Cargar modelos pesados (como embeddings) primero
        logging.info("Inicializando modelo de embeddings...")
        initialize_embeddings()
        logging.info("Modelo de embeddings listo.")

        # 2. Inicializar los componentes del agente
        agent_logic, tools_list, _ = inicializar_componentes_base_agente()
        
        agent_executor_base = AgentExecutor(
            agent=agent_logic,
            tools=tools_list,
            verbose=True,
            handle_parsing_errors=True,
            max_iterations=8,
            return_intermediate_steps=True,
            callbacks=None,  # Asegurarnos de que no hay callbacks que interfieran
            configurable={"session_id": None},  # Agregar configuración base
            run_manager_config={"configurable": {"session_id": None}}  # Agregar configuración para run_manager
        )

        main_agent_handler = RunnableWithMessageHistory(
            runnable=agent_executor_base,
            get_session_history=get_session_history,
            input_messages_key="input",
            history_messages_key="chat_history",
            output_messages_key="output"
        )

        whatsapp_handler_global = WhatsAppHandler(main_agent_handler)
        logging.info("Agente con historial y WhatsAppHandler inicializados correctamente.")

        yield
    except Exception as e:
        logging.error(f"Error al inicializar el agente, la memoria o WhatsAppHandler: {e}")
        raise e

app = FastAPI(lifespan=lifespan)

async def process_message_async(payload: dict):
    """
    Procesa el mensaje de WhatsApp de forma asíncrona.
    Esta función se ejecuta en segundo plano para no bloquear la respuesta al webhook.
    """
    try:
        response = await whatsapp_handler_global.process_message(payload)
        
        # Loguear basado en el status devuelto por process_message
        if response["status"] == "success":
            logging.info(f"Respuesta procesada y enviada exitosamente para msg ID: {response.get('message_id', 'N/A')}")
        #elif response["status"] == "ignored":
             #logging.info(f"Evento ignorado: {response['message']}")
        elif response["status"] == "success_agent_failed_whatsapp":
            logging.warning(f"Agente procesó msg ID {response.get('message_id', 'N/A')} pero falló envío a WhatsApp.")
        else: # 'error' u otros estados
            logging.error(f"Error procesando mensaje: {response.get('message', 'Error desconocido')}")

    except Exception as e:
        logging.error(f"Error crítico en process_message_async: {e}", exc_info=True)


@app.get("/webhook")
async def verify_webhook(request: Request):
    """
    Endpoint para verificar el webhook de WhatsApp.
    WhatsApp envía una solicitud GET para verificar la URL del webhook.
    """
    verify_token = os.getenv("WHATSAPP_VERIFY_TOKEN")
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    if mode and token:
        if mode == "subscribe" and token == verify_token:
            logging.info("Webhook de WhatsApp verificado correctamente")
            return Response(content=challenge, media_type="text/plain")
        else:
            logging.warning("Verificación del webhook fallida")
            return Response(content="Forbidden", status_code=403)
    
    return Response(content="Bad Request", status_code=400)

@app.post("/webhook")
async def webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Endpoint para recibir mensajes de WhatsApp. Verifica duplicados ANTES de procesar.
    """
    try:
        payload = await request.json()
        #logging.info(f"POST webhook recibido.")

        if not isinstance(payload, dict) or not payload.get("object") == "whatsapp_business_account":
            #logging.warning("Payload no parece ser de WhatsApp Business Account. Ignorando.")
            return Response(content="Invalid Payload", status_code=400)

        # --- INICIO DE LÓGICA DE ANTIDUPLICADOS ---
        message_id = None
        try:
            # Intenta extraer el message_id 
            message_id = payload['entry'][0]['changes'][0]['value']['messages'][0]['id']
            msg_type = payload['entry'][0]['changes'][0]['value']['messages'][0]['type']
            # Solo aplicamos filtro duplicados a mensajes de texto
            if msg_type != 'text':
                 message_id = None # No bloqueamos otros tipos de eventos (status, etc.) aquí
                 logging.debug("Evento no es tipo 'text', no se aplicará chequeo de ID duplicado aquí.")

        except (KeyError, IndexError, TypeError):
            # Esto es normal si el payload no es un mensaje de texto (ej. status update)
            logging.debug("No se pudo extraer message_id/type (probablemente no es un mensaje de texto). Se pasará a procesar.")
            pass # Dejamos que process_message_async determine si debe ignorarlo

        if message_id:
            async with processed_ids_lock: # Bloquea el acceso al set
                if message_id in processed_message_ids:
                    logging.info(f"Mensaje duplicado recibido (ID: {message_id}). Ignorando.")
                    return Response(content="OK (Duplicate)", status_code=200)

                # Añadir a la caché si no está
                processed_message_ids.add(message_id)

                # Opcional: Limpiar caché si excede el tamaño
                if len(processed_message_ids) > MAX_CACHE_SIZE:
                    processed_message_ids.pop() # Elimina uno arbitrario (FIFO con set no garantizado)


        # --- FIN DE LÓGICA DE ANTIDUPLICADOS ---


        # Verificar que el handler está listo ANTES de añadir la tarea
        if not whatsapp_handler_global:
            logging.error("WhatsAppHandler no está inicializado, no se puede añadir tarea.")
            return Response(content="Internal Server Error (Handler not ready)", status_code=500)

        # Procesar el mensaje de forma asíncrona
        background_tasks.add_task(process_message_async, payload)
        
        # Responder inmediatamente a WhatsApp para evitar timeouts
        return Response(content="OK", status_code=200)

    except Exception as e:
        logging.error(f"Error procesando webhook de WhatsApp: {e}")
        return Response(content="Internal Server Error", status_code=500)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)