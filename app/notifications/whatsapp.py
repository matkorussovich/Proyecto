import logging
import requests
import os

def send_whatsapp_message(numero_destino: str, mensaje_respuesta: str) -> dict:
    """
    Envía un mensaje a WhatsApp usando la API de WhatsApp Business.
    
    Args:
        numero_destino: Número de teléfono del destinatario.
        mensaje_respuesta: Texto del mensaje a enviar.
        
    Returns:
        Dict con la respuesta de la API de WhatsApp.
        
    Raises:
        ValueError: Si las variables de entorno no están configuradas.
        requests.exceptions.RequestException: Si la petición a la API falla.
    """
    access_token = os.getenv("WHATSAPP_TOKEN")
    phone_number_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID")

    if not access_token or not phone_number_id:
        logging.error("WHATSAPP_TOKEN o WHATSAPP_PHONE_NUMBER_ID no están configurados.")
        raise ValueError("Las credenciales de WhatsApp no están configuradas en las variables de entorno.")

    url = f"https://graph.facebook.com/v20.0/{phone_number_id}/messages"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {access_token}"
    }
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": numero_destino,
        "type": "text",
        "text": {
            "preview_url": False,
            "body": mensaje_respuesta
        }
    }
    
    try:
        logging.info(f"Enviando mensaje a {numero_destino}...")
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logging.error(f"Error en la petición a WhatsApp API para notificar a {numero_destino}: {e}")
        if hasattr(e.response, 'text'):
            logging.error(f"Respuesta de error de WhatsApp API: {e.response.text}")
        raise 