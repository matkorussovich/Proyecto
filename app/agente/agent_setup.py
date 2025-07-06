import os
from langchain_groq import ChatGroq
from langchain_openai import ChatOpenAI
from langchain_core.chat_history import BaseChatMessageHistory
from app.memory.s3_postgres_history import S3PostgresChatMessageHistory
from langchain.agents import create_openai_tools_agent
from .prompt import create_custom_prompt
from app.tools.definitions import get_tools_list
from app.database.crud import (
    get_available_facilities_db,
    ALL_FACILITIES_CACHE 
)


def get_session_history(session_id: str) -> BaseChatMessageHistory:
    """
    Obtiene el historial de chat para una sesión específica.
    
    Args:
        session_id: El ID de la sesión (número de teléfono)
        
    Returns:
        BaseChatMessageHistory: El historial de chat para la sesión
    """
    return S3PostgresChatMessageHistory(session_id=session_id)


def inicializar_componentes_base_agente():
    """
    Configura y devuelve los componentes base del agente: lógica del agente y herramientas.
    NO debe crear memoria específica de sesión.
    """
    provider = os.getenv("LLM_PROVIDER", "groq")
    # Si no se especifica modelo, usa uno por defecto según el proveedor
    model_name = os.getenv("LLM_MODEL_NAME", "llama-3.3-70b-versatile" if provider == "groq" else "gpt-4o")

    # 1. Poblar la lista de instalaciones (CRUCIAL que se haga antes de crear tools y prompt)
    if not ALL_FACILITIES_CACHE: # Si no se llamó al inicio de la app principal
        print("Poblando ALL_FACILITIES_CACHE desde agent_setup...")
        get_available_facilities_db() # Esta función actualiza ALL_FACILITIES_CACHE

    # 2. Crear la lista de herramientas
    tools = get_tools_list(ALL_FACILITIES_CACHE)
    facilities_list_str = ', '.join(ALL_FACILITIES_CACHE) if ALL_FACILITIES_CACHE else "ninguna especificada"

    # 3. Crear el Prompt Personalizado
    prompt = create_custom_prompt(facilities_list_str)

    # 4. Configurar LLM según proveedor
    if provider == "groq":
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise ValueError("No se encontró la GROQ_API_KEY en agent_setup.")
        llm = ChatGroq(
            temperature=0.0,
            groq_api_key=api_key,
            model_name=model_name
        )
    elif provider == "openai":
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("No se encontró la OPENAI_API_KEY en agent_setup.")
        llm = ChatOpenAI(
            temperature=0.0,
            openai_api_key=api_key,
            model_name=model_name
        )
    else:
        raise ValueError(f"Proveedor de LLM no soportado: {provider}")

    # 5. Crear el Agente
    agent_logic  = create_openai_tools_agent(
        llm=llm,
        tools=tools,
        prompt=prompt
    )

    return agent_logic , tools, ALL_FACILITIES_CACHE # Devuelve también la lista para el mensaje inicial