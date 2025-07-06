from langchain_core.tools import Tool, StructuredTool
from langchain_core.runnables.config import var_child_runnable_config
from app.database.crud import (
    check_availability_db,
    make_reservation_db,
    get_available_facilities_db,
    cancel_reservation_db, 
    confirm_cancel_reservation
)
from app.rag.retriever import buscar_info_complejo
from .schemas import (
    create_check_availability_args,
    create_make_reservation_args,
    create_cancel_reservation_args,
    create_confirm_cancel_reservation_args,
    BuscarInfoArgs,
    ListarInstalacionesArgs
)

def get_tools_list(all_facilities_list: list) -> list[Tool]:
    """
    Crea y devuelve la lista de objetos Tool para el agente.
    """
    facilities_str = ', '.join(all_facilities_list) if all_facilities_list else "ninguna especificada"
  
    # Crear los modelos Pydantic dinámicamente
    CheckAvailabilityArgs = create_check_availability_args()
    MakeReservationArgs = create_make_reservation_args()
    CancelReservationArgs = create_cancel_reservation_args()
    ConfirmCancelReservationArgs = create_confirm_cancel_reservation_args()

    
  
    tools = [
        StructuredTool.from_function(
            func=check_availability_db, 
            name="ConsultarDisponibilidad",
            description=f"""Verifica disponibilidad. Args: facility_name (uno de: {facilities_str}), date_str (AAAA-MM-DD), time_str (HH:MM).""",
            args_schema=CheckAvailabilityArgs
        ),
        StructuredTool.from_function(
            func=lambda facility_name, date_str, time_str, user_name: make_reservation_db(
                facility_name=facility_name,
                date_str=date_str,
                time_str=time_str,
                user_name=user_name,
                session_id=var_child_runnable_config.get().get("configurable", {}).get("session_id") if var_child_runnable_config.get() else None
            ),
            name="RealizarReserva",
            description=f"""Registra la reserva. Args: facility_name (uno de: {facilities_str}), date_str (AAAA-MM-DD), time_str (HH:MM), user_name.""",
            args_schema=MakeReservationArgs
        ),
        StructuredTool.from_function(
            func=lambda **kwargs: (
                print(f"Llamada a CancelarReserva con kwargs: {kwargs}"),
                cancel_reservation_db(
                    session_id=var_child_runnable_config.get().get("configurable", {}).get("session_id") if var_child_runnable_config.get() else None,
                    **kwargs
                )
            )[-1],
            name="CancelarReserva",
            description="""Busca las reservas futuras activas del cliente y solicita confirmación o elección según corresponda.""",
            args_schema=CancelReservationArgs
        ),
        StructuredTool.from_function(
            func=lambda booking_id=None, **kwargs: confirm_cancel_reservation(
                booking_id=booking_id,
                session_id=var_child_runnable_config.get().get("configurable", {}).get("session_id") if var_child_runnable_config.get() else None
            ),
            name="ConfirmarCancelacionReserva",
            description="""Confirma y ejecuta la cancelación de una reserva específica. Args: booking_id (ID de la reserva a cancelar).""",
            args_schema=ConfirmCancelReservationArgs
        ),
        StructuredTool.from_function(
            name="ListarInstalaciones",
            func=get_available_facilities_db, 
            description=f"Devuelve lista de nombres exactos de instalaciones disponibles ({facilities_str}). Úsala si el usuario no especifica una o pregunta cuáles hay.",
            args_schema=ListarInstalacionesArgs
        ),
        Tool.from_function(
            func=buscar_info_complejo, 
            name="BuscarInformacionComplejo",
            description="INDISPENSABLE para responder preguntas generales sobre el complejo deportivo: horarios de apertura/cierre, precios de abonos/clases, reglas, servicios disponibles (cafetería, parking, etc.), tipos de clases, dirección, contacto, FAQs y cualquier otra duda sobre el funcionamiento o las instalaciones del Club Deportivo Rosario. NO usar para verificar disponibilidad de una hora específica o para realizar reservas.",
            args_schema=BuscarInfoArgs
        ),
        Tool.from_function(
            func=lambda **kwargs: "Ha ocurrido un error interno al procesar tu solicitud. Por favor, intenta nuevamente o contacta soporte.",
            name="ToolDummy",
            description="Captura llamadas malformadas a tools y devuelve un mensaje de error amigable."
        )
    ]
    return tools 

