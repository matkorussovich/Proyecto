from langchain_core.chat_history import BaseChatMessageHistory
from langchain_core.messages import BaseMessage, messages_from_dict, messages_to_dict
import boto3 # Para S3
import psycopg2 # Para PostgreSQL
import json
import os 
import asyncio
from typing import List


class S3PostgresChatMessageHistory(BaseChatMessageHistory):
    def __init__(self, session_id: str):
        self.session_id = session_id # número de telefono
        self.pg_conn_params = { 
            "host": os.getenv("DB_HOST"),
            "port": os.getenv("DB_PORT"),
            "dbname": os.getenv("DB_NAME"),
            "user": os.getenv("DB_USER"),
            "password": os.getenv("DB_PASSWORD"),
        }
        self.s3_bucket_name = os.getenv("BUCKET_NAME")
        self.s3_client = boto3.client('s3')
        self.s3_object_key_prefix = "historial/" # Carpeta dentro del bucket
        self._messages = None  # Cache para mensajes

    def _get_s3_object_key(self) -> str:
        return f"{self.s3_object_key_prefix}{self.session_id}.json"

    @property
    def messages(self) -> List[BaseMessage]:
        """Obtiene los mensajes del historial."""
        if self._messages is None:
            self._messages = self._get_messages_sync()
        return self._messages

    def _get_messages_sync(self) -> List[BaseMessage]:
        """Obtiene los mensajes de forma síncrona."""
        try:
            conn = psycopg2.connect(**self.pg_conn_params)
            cur = conn.cursor()
            
            cur.execute(
                "SELECT s3_chat_history_key FROM historial_chats WHERE ds_telefono = %s",
                (self.session_id,)
            )
            result = cur.fetchone()
            
            if not result or not result[0]:
                return []
                
            s3_key = result[0]
                
            try:
                # Intentar descargar el objeto de S3 usando la clave almacenada
                response = self.s3_client.get_object(
                    Bucket=self.s3_bucket_name,
                    Key=s3_key
                )
                
                # Leer y deserializar el contenido JSON
                content = response['Body'].read().decode('utf-8')
                messages_dict = json.loads(content)
                
                # Convertir el diccionario a objetos BaseMessage
                return messages_from_dict(messages_dict)
                
            except self.s3_client.exceptions.NoSuchKey:
                return []
                
        except Exception as e:
            print(f"Error al recuperar mensajes: {str(e)}")
            return []
            
        finally:
            if 'cur' in locals():
                cur.close()
            if 'conn' in locals():
                conn.close()

    def add_message(self, message: BaseMessage) -> None:
        """Añade un mensaje al historial."""
        self.add_messages([message])

    def add_messages(self, messages: List[BaseMessage]) -> None:
        """Añade múltiples mensajes al historial."""
        try:
            # 1. Cargar mensajes actuales
            current_messages = self.messages
            
            # 2. Añadir nuevos mensajes
            all_messages = current_messages + messages
            
            # 3. Serializar a JSON
            messages_json = json.dumps(messages_to_dict(all_messages))
            
            # 4. Subir a S3
            s3_key = self._get_s3_object_key()
            self.s3_client.put_object(
                Bucket=self.s3_bucket_name,
                Key=s3_key,
                Body=messages_json
            )
            
            # 5. Actualizar PostgreSQL
            conn = psycopg2.connect(**self.pg_conn_params)
            cur = conn.cursor()
            
            cur.execute("""
                INSERT INTO historial_chats (ds_telefono, s3_chat_history_key, last_updated)
                VALUES (%s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (ds_telefono) 
                DO UPDATE SET 
                    s3_chat_history_key = EXCLUDED.s3_chat_history_key,
                    last_updated = CURRENT_TIMESTAMP
            """, (self.session_id, s3_key))
            
            conn.commit()
            
            if self._messages is not None:
                self._messages.extend(messages)
            
        except Exception as e:
            print(f"Error al añadir mensajes: {str(e)}")
            raise
            
        finally:
            if 'cur' in locals():
                cur.close()
            if 'conn' in locals():
                conn.close()

    def clear(self) -> None:
        """Limpia el historial de mensajes."""
        try:
            # 1. Borrar de S3
            try:
                self.s3_client.delete_object(
                    Bucket=self.s3_bucket_name,
                    Key=self._get_s3_object_key()
                )
            except self.s3_client.exceptions.NoSuchKey:
                pass
                
            # 2. Borrar de PostgreSQL
            conn = psycopg2.connect(**self.pg_conn_params)
            cur = conn.cursor()
            
            cur.execute(
                "DELETE FROM historial_chats WHERE ds_telefono = %s",
                (self.session_id,)
            )
            
            conn.commit()
            self._messages = []
            
        except Exception as e:
            print(f"Error al limpiar historial: {str(e)}")
            raise
            
        finally:
            if 'cur' in locals():
                cur.close()
            if 'conn' in locals():
                conn.close()

    async def aget_messages(self) -> List[BaseMessage]:
        """Versión asíncrona de get_messages."""
        if self._messages is None:
            loop = asyncio.get_event_loop()
            self._messages = await loop.run_in_executor(None, self._get_messages_sync)
        return self._messages

    async def aadd_messages(self, messages: List[BaseMessage]) -> None:
        """Versión asíncrona de add_messages."""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self.add_messages, messages)

    async def aclear(self) -> None:
        """Versión asíncrona de clear."""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self.clear)