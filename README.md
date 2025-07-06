# Asistente Virtual para Complejo Deportivo

Este proyecto forma parte del **Trabajo Final de Máster en Ciencia de Datos** de la Universidad Europea de Madrid. Su objetivo es desarrollar un asistente virtual inteligente para la gestión de reservas y consultas en un complejo deportivo, integrando procesamiento de lenguaje natural, RAG (Retrieval-Augmented Generation), WhatsApp y una base de datos PostgreSQL.

## Contexto académico

El desarrollo de este asistente virtual responde a la necesidad de automatizar y optimizar la atención al cliente en instalaciones deportivas, aplicando técnicas avanzadas de inteligencia artificial, machine learning y procesamiento de lenguaje natural, en el marco del Máster en Ciencia de Datos.

## Arquitectura y funcionamiento

![Funcionamiento del sistema](imagenes/funcionamiento.png)

El núcleo del sistema es un agente conversacional inteligente basado en LangChain, que integra memoria de conversación, herramientas personalizadas y control adaptativo del diálogo. Este agente recibe mensajes de WhatsApp, interpreta la intención del usuario y, si es necesario, ejecuta funciones auxiliares (como consultar disponibilidad o gestionar reservas) de forma transparente. Gracias a la gestión del historial de conversación, el agente mantiene coherencia y personalización en cada interacción, ofreciendo respuestas precisas y naturales, y adaptándose dinámicamente a las necesidades del usuario.

## Características principales

- **Consulta de disponibilidad** de instalaciones deportivas.
- **Gestión de reservas** (alta, consulta, alternativas).
- **Recuperación de información** sobre el complejo (horarios, precios, servicios, etc.) usando RAG y Pinecone.
- **Interfaz conversacional** vía WhatsApp (integración con WhatsApp Business API).
- **API REST** construida con FastAPI.
- **Persistencia** de datos en PostgreSQL.
- **Scripts auxiliares** para indexar conocimiento y poblar la base de datos.

## Estructura del proyecto

```
/Proyecto/
├── /app/                # Código fuente principal
│   ├── /agente/         # Lógica del agente conversacional (LangChain)
│   ├── /database/       # Conexión y operaciones con la base de datos
│   ├── /rag/            # Recuperación aumentada de información (Pinecone)
│   ├── /tools/          # Herramientas y esquemas para el agente
│   ├── /whatsapp/       # Integración y manejo de mensajes WhatsApp
│   ├── /notifications/  # Notificaciones externas
│   ├── /memory/         # Gestión de memoria conversacional
│   └── main.py          # Punto de entrada principal (API FastAPI)
│
├── /scripts/            # Scripts auxiliares (indexación, carga de datos)
├── /ML/                 # Modelos y notebooks de Machine Learning
├── /sql/                # Scripts y datos SQL
├── /data/               # Base de conocimiento y datos
├── /pruebas/            # Scripts de pruebas y utilidades
├── requirements.txt     # Dependencias Python
├── .env                 # Variables de entorno (no incluido)
├── .gitignore           # Exclusiones de git
└── README.md            # Documentación del proyecto
```

## Instalación

1. **Clona el repositorio** y accede a la carpeta del proyecto:

   ```bash
   git clone <URL_DEL_REPO>
   cd <carpeta_del_proyecto>
   ```

2. **Crea y activa un entorno virtual** (opcional pero recomendado):

   ```bash
   python -m venv venv
   source venv/bin/activate  # En Windows: venv\Scripts\activate
   ```

3. **Instala las dependencias**:

   ```bash
   pip install -r requirements.txt
   ```

4. **Configura las variables de entorno**  
   Crea un archivo `.env` en la raíz del proyecto con las siguientes variables (ejemplo):

   ```
   DB_HOST
   DB_PORT
   DB_NAME
   DB_USER
   DB_PASSWORD
   GROQ_API_KEY=tu_clave_groq
   PINECONE_API_KEY=tu_clave_pinecone
   WHATSAPP_TOKEN=tu_token_whatsapp
   WHATSAPP_VERIFY_TOKEN=tu_token_verificacion
   ```

5. **Inicializa la base de datos**  
   Ejecuta los scripts SQL en `/sql/creacion_tablas.sql` y `/sql/datos_reservas.sql` en tu instancia de PostgreSQL.

6. **(Opcional) Indexa la base de conocimiento**  
   Ejecuta el script para cargar los datos en Pinecone:

   ```bash
   python scripts/index_knowledge.py
   ```

## Ejecución

Para iniciar la API (FastAPI):

```bash
python app/main.py
```

Esto levantará el servidor en `http://0.0.0.0:8000/`.

- El endpoint `/webhook` está preparado para recibir y responder mensajes de WhatsApp.
- Para las pruebas, recomiendo utilizar alguna herramienta como [ngrok](https://ngrok.com/) para exponer tu servidor local y conectar con el webhook de la API oficial de WhatsApp.

## Scripts útiles

- `scripts/index_knowledge.py`: Indexa la base de conocimiento en Pinecone.
- `ML/random-forest.ipynb`: Ejemplo de modelo de Machine Learning para predicción de cancelaciones.
- `pruebas/pruebas-pinecone.py`: Pruebas de búsqueda en Pinecone.

## Dependencias principales

- Python 3.10+
- FastAPI
- LangChain
- Pinecone
- HuggingFace Embeddings
- PostgreSQL
- WhatsApp Business API
- Uvicorn
- dotenv

Consulta el archivo `requirements.txt` para la lista completa.

## Notas

- El archivo `.env` **no** se incluye por seguridad.
- El sistema está preparado para ser desplegado en servidores locales o en la nube.

---

**Universidad Europea de Madrid**  
Máster en Ciencia de Datos  
Trabajo Final de Máster (TFM)

## Contacto

- Correo: [matkorussovich@gmail.com](mailto:matkorussovich@gmail.com)
- LinkedIn: [https://www.linkedin.com/in/matkorussovich/](https://www.linkedin.com/in/matkorussovich/) 