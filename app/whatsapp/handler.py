from typing import Dict, Any, Optional
import logging
from langchain.callbacks import get_openai_callback
import requests
import os
from app.notifications.whatsapp import send_whatsapp_message

class WhatsAppHandler:
    def __init__(self, agent_executor):
        """
        Inicializa el manejador de WhatsApp.
        
        Args:
            agent_executor: El agente ya inicializado con la memoria.
        """
        self.agent_executor = agent_executor # RunnableWithMessageHistory
        self.whatsapp_token = os.getenv("WHATSAPP_TOKEN")
        if not self.whatsapp_token:
            logging.warning("No se encontró WHATSAPP_TOKEN en las variables de entorno")
        logging.info("WhatsAppHandler inicializado correctamente")

    async def process_message(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Procesa un mensaje entrante de WhatsApp.
        
        Args:
            payload: El payload del mensaje de WhatsApp
             
        Returns:
            Dict con la respuesta procesada 
        """
        try:
            # Extraer el mensaje del payload de WhatsApp
            detalles_mensaje  = self._extract_data_from_payload(payload)
            
            if detalles_mensaje is None:
                # logging.info("Payload ignorado: No es un mensaje de texto válido o falta información.")
                return {"status": "ignored", "message": "Payload no es un mensaje de texto procesable."}

            message = detalles_mensaje["text"]
            nombre_cliente = detalles_mensaje["name"]
            telefono_cliente = detalles_mensaje["phone"]
            message_id = detalles_mensaje["id"] 

            logging.info(f"Procesando mensaje de {telefono_cliente} - {nombre_cliente}: \n{message}")

            if not isinstance(message, str) or not message.strip():
                logging.error("El mensaje recibido para el agente es vacío o no es string.")
                return {"status": "error", "message": "Mensaje vacío o inválido."}
            
            logging.basicConfig(level=logging.DEBUG)

            # Procesar el mensaje con el agente
            response = await self.agent_executor.ainvoke(
                {"input": message}, 
                config={
                    "configurable": {
                        "session_id": telefono_cliente
                    }
                }
            )

            # Validar la respuesta del agente
            if response is None or not isinstance(response, dict):
                logging.error("El agente devolvió None o un tipo inesperado.")
                return {"status": "error", "message": "El agente no devolvió una respuesta válida."}
            if "output" not in response:
                logging.error(f"Respuesta del agente sin 'output': {response}")
                return {"status": "error", "message": "El agente no devolvió un output válido."}

            # Enviar la respuesta a WhatsApp
            try:
                whatsapp_response = self.enviar_respuesta_whatsapp(
                    telefono_cliente,
                    response['output']
                )
                logging.info(f"Respuesta enviada a WhatsApp: {whatsapp_response}")
            except Exception as e:
                logging.error(f"Error enviando respuesta a WhatsApp para msg ID {message_id}: {e}")
                # Aún así, el procesamiento del agente fue exitoso a nivel interno
                return {"status": "success_agent_failed_whatsapp", "message": "Agente procesó pero falló el envío a WhatsApp."}

            
            # Respuesta indica éxito completo
            return {
                "status": "success",
                "response": response['output'],
                "message_id": message_id, # Devolver el ID puede ser útil
                "intermediate_steps": response.get("intermediate_steps", [])
            }
            
        except Exception as e:
                # Este es un error durante la lógica de process_message (después de la extracción)
                logging.error(f"Error procesando mensaje de WhatsApp (Handler): {e}", exc_info=True)
                if hasattr(e, 'failed_generation'):
                    logging.error(f"Detalles de fallo en generación: {e.failed_generation}")
                return {"status": "error", "message": f"Error interno en handler: {str(e)}"}

    def _extract_data_from_payload(self, payload: Dict[str, Any]) -> Optional[str]:
        """
        Extrae los datos relevantes (mensaje, nombre, teléfono, ID) si es un mensaje de texto válido.

        Returns:
            Un diccionario con 'text', 'name', 'phone', 'id' si es válido, o None si no lo es.
        """
        try:
            entry = payload.get('entry', [{}])[0]
            changes = entry.get('changes', [{}])[0]
            value = changes.get('value', {})
            messaging_product = value.get('messaging_product')
            messages = value.get('messages', [{}])
            contacts = value.get('contacts', [{}])

            if not messaging_product or not messages or messages == [{}] or not contacts or contacts == [{}]:
                 # Si falta alguna estructura clave, no es un mensaje que buscamos
                 return None

            msg = messages[0] # Procesamos solo el primer mensaje del payload
            contact = contacts[0]

            msg_type = msg.get('type')
            msg_id = msg.get('id')
            phone_number = msg.get('from')
            profile_name = contact.get('profile', {}).get('name')
            text_body = msg.get('text', {}).get('body')

            # --- ¡NUEVO! Validación más estricta ---
            if (changes.get('field') == 'messages' and # Asegurar que es un cambio de mensaje
                msg_type == 'text' and              # Asegurar que es de tipo texto
                msg_id and                           # Debe tener ID
                phone_number and                     # Debe tener remitente
                profile_name and                     # Debe tener nombre de perfil
                text_body):                          # Debe tener cuerpo de texto

                print("Nuevo mensaje de texto extraído.") # Movido aquí para confirmar extracción válida
                return {
                    "text": text_body,
                    "name": profile_name,
                    "phone": phone_number,
                    "id": msg_id
                }
            else:
                # No es un mensaje de texto válido o falta algún campo esencial
                return None

        except (IndexError, KeyError, TypeError) as e:
            # Captura errores comunes al navegar diccionarios anidados
            logging.warning(f"Error leve extrayendo datos del payload (probablemente no es msg de texto): {e}")
            return None
        except Exception as e:
            # Captura cualquier otro error inesperado durante la extracción
            logging.error(f"Error inesperado extrayendo datos del payload: {e}", exc_info=True)
            return None
    

    def format_whatsapp_response(self, response: Dict[str, Any]) -> Dict[str, Any]:
        """
        Formatea la respuesta para enviarla a WhatsApp.
        
        Args:
            response: La respuesta del agente
            
        Returns:
            Dict con la respuesta formateada para WhatsApp
        """
        return {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": response.get("to", ""),
            "type": "text",
            "text": {
                "body": response.get("response", "Lo siento, no pude procesar tu mensaje.")
            }
        }

    def enviar_respuesta_whatsapp(self, numero_destino: str, mensaje_respuesta: str) -> Dict[str, Any]:
        """
        Envía una respuesta a WhatsApp usando la función centralizada.
        
        Args:
            numero_destino: Número de teléfono del destinatario
            mensaje_respuesta: Texto de la respuesta
            
        Returns:
            Dict con la respuesta de la API de WhatsApp
        """
        try:
            return send_whatsapp_message(numero_destino, mensaje_respuesta)
        except Exception as e:
            logging.error(f"Fallo al usar la función centralizada de envío de WhatsApp: {e}")
            raise