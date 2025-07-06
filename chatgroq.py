import os
import datetime
from dotenv import load_dotenv
from langchain_core.tools import Tool, StructuredTool
from langchain_groq import ChatGroq
from langchain.memory import ConversationBufferWindowMemory
from langchain.agents import AgentExecutor, create_openai_tools_agent
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder 
from pydantic import BaseModel, Field, field_validator, ValidationError
from datetime import datetime


# Importa las funciones y la lista de instalaciones
from database_functions import check_availability, make_reservation, get_available_facilities, buscar_info_complejo, get_db_connection

# Inicializar ALL_FACILITIES
try:
    conn = get_db_connection()
    ALL_FACILITIES = get_available_facilities(conn)
    print(f"Instalaciones disponibles: {ALL_FACILITIES}")
except Exception as e:
    print(f"Error al inicializar instalaciones: {e}")
    ALL_FACILITIES = []
finally:
    if 'conn' in locals() and conn is not None:
        try:
            conn.close()
        except Exception as e:
            print(f"Error al cerrar la conexión: {e}")

# Carga la clave API
load_dotenv()
groq_api_key = os.getenv("GROQ_API_KEY")
pinecone_api_key = os.getenv("PINECONE_API_KEY")
if not groq_api_key:
    raise ValueError("No se encontró la GROQ_API_KEY.")
if not pinecone_api_key:
    raise ValueError("No se encontró la PINECONE_API_KEY.")

# --- Modelos Pydantic con validadores ---
class CheckAvailabilityArgs(BaseModel):
    facility_name: str = Field(description=f"Nombre exacto de la instalación deportiva. Opciones válidas: {', '.join(ALL_FACILITIES)}")
    date_str: str = Field(description="Fecha de consulta en formato AAAA-MM-DD. Ej: '2025-04-18'")
    time_str: str = Field(description="Hora de consulta en formato HH:MM (24h). Ej: '13:00'")

    @field_validator('facility_name')
    @classmethod
    def validate_facility_name_check(cls, v):
        for facility in ALL_FACILITIES:
            if v.lower() == facility.lower():
                return facility
        raise ValueError(f"Instalación '{v}' no válida.", ALL_FACILITIES)

    @field_validator('date_str')
    @classmethod
    def validate_date(cls, v):
        try:
            datetime.strptime(v, '%Y-%m-%d')
        except ValueError:
            raise ValueError("Formato de fecha inválido, debe ser AAAA-MM-DD")
        return v

    @field_validator('time_str')
    @classmethod
    def validate_time(cls, v):
        try:
            datetime.strptime(v, '%H:%M')
        except ValueError:
            raise ValueError("Formato de hora inválido, debe ser HH:MM (24h)")
        return v

class MakeReservationArgs(BaseModel):
    facility_name: str = Field(description=f"Nombre exacto de la instalación deportiva. Opciones válidas: {', '.join(ALL_FACILITIES)}")
    date_str: str = Field(description="Fecha de reserva en formato AAAA-MM-DD. Ej: '2025-04-18'")
    time_str: str = Field(description="Hora de reserva en formato HH:MM (24h). Ej: '11:00'")
    user_name: str = Field(description="Nombre de la persona que reserva. Ej: 'Matko'", max_length=100)

    @field_validator('facility_name')
    @classmethod
    def validate_facility_name(cls, v):
        for facility in ALL_FACILITIES:
            if v.lower() == facility.lower():
                return facility
        raise ValueError(f"Instalación '{v}' no válida. Las opciones son: {', '.join(ALL_FACILITIES)}")

    @field_validator('date_str')
    @classmethod
    def validate_date(cls, v):
        try:
            datetime.strptime(v, '%Y-%m-%d')
        except ValueError:
            raise ValueError("Formato de fecha inválido, debe ser AAAA-MM-DD")
        return v

    @field_validator('time_str')
    @classmethod
    def validate_time(cls, v):
        try:
            datetime.strptime(v, '%H:%M')
        except ValueError:
            raise ValueError("Formato de hora inválido, debe ser HH:MM (24h)")
        return v

class BuscarInfoArgs(BaseModel):
    query: str = Field(description="La pregunta específica del usuario sobre el complejo deportivo (horarios, precios, reglas, servicios, etc.)")


# --- Lista de Herramientas (Usando Tool base para no-args) ---
tools = [
    StructuredTool.from_function(
        func=check_availability,
        name="ConsultarDisponibilidad",
        description=f"""Verifica disponibilidad. Args: facility_name (uno de: {', '.join(ALL_FACILITIES)}), date_str (AAAA-MM-DD), time_str (HH:MM).""",
        args_schema=CheckAvailabilityArgs
    ),
    StructuredTool.from_function(
        func=make_reservation,
        name="RealizarReserva",
        description=f"""Registra reserva. Args: facility_name (uno de: {', '.join(ALL_FACILITIES)}), date_str (AAAA-MM-DD), time_str (HH:MM), user_name. USAR SOLO TRAS CONSULTAR DISPONIBILIDAD.""",
        args_schema=MakeReservationArgs
    ),
    Tool( 
        name="ListarInstalaciones",
        func=lambda *args, **kwargs: ALL_FACILITIES, 
        description=f"Devuelve lista de nombres exactos de instalaciones disponibles ({', '.join(ALL_FACILITIES)}). Úsala si el usuario no especifica una o pregunta cuáles hay."
    ),
    Tool.from_function(
    name="BuscarInformacionComplejo",
    func=buscar_info_complejo,
    description="INDISPENSABLE para responder preguntas generales sobre el complejo deportivo: horarios de apertura/cierre, precios de abonos/clases, reglas, servicios disponibles (cafetería, parking, etc.), tipos de clases, dirección, contacto, FAQs y cualquier otra duda sobre el funcionamiento o las instalaciones del Club Deportivo Momentum. NO usar para verificar disponibilidad de una hora específica o para realizar reservas.",
    args_schema=BuscarInfoArgs
)
]

# --- Configura LLM ---
llm = ChatGroq(
    temperature=0.0,
    groq_api_key=groq_api_key,
    model_name="llama-3.3-70b-versatile" # O el modelo que prefieras
    #model_name="deepseek-r1-distill-llama-70b"
)

# --- Intenta Vincular Herramientas Explícitamente ---
llm_with_tools = llm.bind_tools(tools)

# --- Configura Memoria ---
memory = ConversationBufferWindowMemory(
    k=10,
    memory_key="chat_history",
    input_key="input",
    output_key="output",
    return_messages=True
)

# --- Crea el Prompt Personalizado ---
current_date_str = datetime.now().strftime('%Y-%m-%d')
tool_names = ", ".join([t.name for t in tools])
facilities_list_str = ', '.join(ALL_FACILITIES)

system_message = f"""Eres un asistente virtual muy amable para el Complejo Deportivo de Madrid (España).
Tu única función es ayudar a los usuarios con las siguientes tareas relacionadas EXCLUSIVAMENTE con ESTE complejo deportivo, usando las herramientas proporcionadas:
1. Consultar disponibilidad de instalaciones (`ConsultarDisponibilidad`).
2. Registrar reservas de instalaciones (`RealizarReserva`).
3. Listar las instalaciones disponibles DENTRO del complejo (`ListarInstalaciones`).
4. Responder preguntas generales sobre el complejo (horarios, precios, reglas, servicios, clases, contacto, etc.) (`BuscarInformacionComplejo`) conocimiento.

Contexto Clave:
- El complejo es Club Deportivo Rosario, en Madrid. No gestiones NADA para otros lugares.
- Hoy es {current_date_str}. Interpreta 'mañana', 'hoy', etc., basándote en esta fecha.

Instrucciones de Comportamiento Obligatorias:
- Usa la herramienta adecuada para cada tarea:
    - Para saber qué instalaciones hay -> `ListarInstalaciones`.
    - Para saber si una instalación está disponible para una fecha y hora determinada -> `ConsultarDisponibilidad`, 
    - Para registrar una reserva -> `RealizarReserva`.
    - Para **TODAS las demás preguntas** sobre el complejo (precios, horarios generales, reglas, servicios, clases, ¿hay cafetería?, ¿dónde está?, etc.) -> USA `BuscarInformacionComplejo`.
- Verificación de Nombre: Cuando el usuario mencione una instalación, COMPARA su input (ignorando mayúsculas/minúsculas) con la lista oficial ({facilities_list_str}). Si coincide, usa ese nombre oficial. Si no coincide o es ambiguo (ej: "la de pádel"), usa `ListarInstalaciones` para mostrar opciones O PREGUNTA al usuario cuál de las oficiales quiere. NO elijas una al azar.
- Datos Faltantes: Si para usar `ConsultarDisponibilidad` o `RealizarReserva` te falta el nombre exacto verificado, la fecha (AAAA-MM-DD), la hora (HH:MM), o el nombre de usuario (`user_name` para reservar), **pídele directamente al usuario** esa información específica que falta. No intentes adivinarla.
- Flujo Post-ListarInstalaciones: Si usaste `ListarInstalaciones`, tu SIGUIENTE respuesta **DEBE** incluir la lista de instalaciones que te devolvió la herramienta y luego puedes preguntar al usuario qué desea hacer.
- Flujo de Reserva: Antes de usar `RealizarReserva`, SIEMPRE verifica que ese turno este disponible con `ConsultarDisponibilidad`.
- Interacción: Responde amablemente y enfocado en la tarea. NO hables de tu naturaleza como IA. NO des consejos externos. SOLO gestiona este complejo.
- Historial: Utiliza el historial de conversación para mantener el contexto.
- Respuesta Conversacional: SIEMPRE! responde al usuario. Si la entrada es un saludo o no requiere acción/herramienta, **simplemente responde directamente al usuario** de forma conversacional.
- **Manejo Resultado ConsultarDisponibilidad:** Después de llamar a `ConsultarDisponibilidad` y recibir la Observation:
    - Si la Observation es `"ESTADO: Disponible"`: **El siguiente paso es llamar a `RealizarReserva`** si ya tienes `facility_name`, `date_str`, `time_str`, y `user_name`. Si te falta `user_name`, pídelo primero. **NO vuelvas a llamar a `ConsultarDisponibilidad`**.
    - Si la Observation es `"ESTADO: Ocupado | Alternativas: ..."`: Informa al usuario que está ocupado y presenta claramente las alternativas.
    - Si la Observation es `"ESTADO: Ocupado | Sin Alternativas"`: Informa al usuario que no hay disponibilidad ese día/hora.
    - Si la Observation empieza con `"ERROR: ..."`: Informa al usuario del problema.
- **Formato de Confirmación Final IMPERATIVO:** Una vez que hayas ejecutado `RealizarReserva` y esta haya sido exitosa, tu **única y exclusiva salida** debe ser el mensaje final de confirmación para el usuario. Este mensaje debe ser conciso, amable y contener solo los detalles esenciales (Instalación, Fecha, Hora). **Está PROHIBIDO describir los pasos internos que seguiste, mencionar los nombres `ConsultarDisponibilidad` o `RealizarReserva`, o narrar el proceso de verificación/reserva en tu respuesta final.**
    * **EJEMPLO DE ÚNICA RESPUESTA FINAL VÁLIDA TRAS RESERVA EXITOSA:** '¡Perfecto, [Nombre Usuario]! Tu reserva para [Instalación] el [Fecha] a las [Hora] está confirmada. ¡Que lo disfrutes!'
    * *(Cualquier otra descripción del proceso en la respuesta final será incorrecta)*.
- En NINGUNA respuesta al usuario debes describir las herramientas internas que estás usando o los pasos que estás siguiendo. Limítate a pedir la información necesaria o a dar el resultado final.
- **Formato de Respuesta para Consultas de Disponibilidad:**
    * Si la instalación está disponible: "¡Perfecto! La [Instalación] está disponible el [Fecha] a las [Hora]. ¿Te gustaría hacer la reserva?"
    * Si la instalación está ocupada: "Lo siento, la [Instalación] está ocupada el [Fecha] a las [Hora]. Sin embargo, para ese día está disponible en estos horarios: [horarios disponibles]. ¿Te gustaría reservar en alguno de estos horarios?"
    * Si no hay horarios disponibles: "Lo siento, la [Instalación] está ocupada el [Fecha] a las [Hora] y no hay otros horarios disponibles para ese día. ¿Te gustaría consultar otro día u otra instalación?"
"""

prompt = ChatPromptTemplate.from_messages(
    [
        ("system", system_message),
        MessagesPlaceholder(variable_name="chat_history"),
        ("human", "{input}"),
        MessagesPlaceholder(variable_name="agent_scratchpad"),
    ]
)

# --- Crea el Agente ---
# Pasamos el LLM CON HERRAMIENTAS VINCULADAS y la lista de tools vacía
# (Probando este enfoque para ver si resuelve el ToolException)
agent = create_openai_tools_agent(
    llm=llm, # <--- LLM con herramientas
    tools=tools,           # <--- Lista vacía aquí
    prompt=prompt
)

# --- Crea el Executor ---
agent_executor = AgentExecutor(
    agent=agent,
    tools=tools, # <--- Executor siempre necesita las tools para ejecutarlas
    memory=memory,
    verbose=True,
    handle_parsing_errors=True, # Intentar manejar errores de parsing
    max_iterations=8,
    return_intermediate_steps=True
)

# --- Bucle principal ---
print("\n" + "="*50)
print(" Asistente Virtual del Complejo Deportivo de Madrid")
print("="*50)
print(f"Fecha y hora actual: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("Puedes preguntar por disponibilidad, hacer reservas o listar instalaciones.")
print("Escribe 'salir' para terminar.")
print("="*50 + "\n")

simple_greetings = ["hola", "buenas", "buenos dias", "buenas tardes", "buenas noches", "que tal", "hola que tal", "hola, como estas?", "hola todo bien?", "holaa", "holaa todo bien?"]

while True:
    try:
        user_input = input("Tú: ")
        if not user_input:
             continue
        cleaned_input = user_input.lower().strip("!¿?., ")
        if cleaned_input in ["salir", "adios", "exit", "terminar"]:
            print("Asistente: ¡Ha sido un placer ayudarte! ¡Hasta pronto!")
            break

        if cleaned_input in simple_greetings:
             response_text = "¡Hola! Soy el asistente virtual del Complejo Deportivo de Madrid. ¿En qué puedo ayudarte hoy?"
             print(f"Asistente: {response_text}")
             memory.save_context({"input": user_input}, {"output": response_text})
             continue

        response = agent_executor.invoke({"input": user_input})
        print(f"Asistente: {response['output']}")

        if response.get("intermediate_steps"):
             print("\n--- Pasos Intermedios ---")
             for step in response["intermediate_steps"]:
                 print(step)
             print("-------------------------\n")

    except ValidationError as e:
         print(f"Asistente: Hubo un problema validando los datos para la herramienta.")
         print(f"(Detalle del error de validación: {e})")
    except Exception as e:
        print(f"Asistente: Lo siento, ocurrió un error inesperado durante el procesamiento.")
        import traceback
        print(f"(Detalle: {traceback.format_exc()})")