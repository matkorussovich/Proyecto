from pydantic import BaseModel, Field, field_validator, ValidationError
from datetime import datetime
from app.database.crud import ALL_FACILITIES_CACHE
from typing import Optional

def create_check_availability_args():
    class CheckAvailabilityArgs(BaseModel):
        facility_name: str = Field(description=f"Nombre exacto de la instalación deportiva. Opciones válidas: {', '.join(ALL_FACILITIES_CACHE)}")
        date_str: str = Field(description="Fecha de consulta en formato AAAA-MM-DD. Ej: '2025-04-18'")
        time_str: str = Field(description="Hora de consulta en formato HH:MM (24h). Ej: '13:00'")

        @field_validator('facility_name')
        @classmethod
        def validate_facility_name_check(cls, v):
            from app.database.crud import ALL_FACILITIES_CACHE  # Importamos aquí para asegurar que tenemos la versión más reciente
            if not ALL_FACILITIES_CACHE:
                raise ValueError("La lista de instalaciones no está disponible. Por favor, intente nuevamente.")
            for facility in ALL_FACILITIES_CACHE:
                if v.lower() == facility.lower():
                    return facility
            raise ValueError(f"Instalación '{v}' no válida. Las opciones son: {', '.join(ALL_FACILITIES_CACHE)}")

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
    return CheckAvailabilityArgs

def create_make_reservation_args():
    class MakeReservationArgs(BaseModel):
        facility_name: str = Field(description=f"Nombre exacto de la instalación deportiva. Opciones válidas: {', '.join(ALL_FACILITIES_CACHE)}")
        date_str: str = Field(description="Fecha de reserva en formato AAAA-MM-DD. Ej: '2025-04-18'")
        time_str: str = Field(description="Hora de reserva en formato HH:MM (24h). Ej: '11:00'")
        user_name: str = Field(description="Nombre de la persona que reserva.'", max_length=100)

        @field_validator('facility_name')
        @classmethod
        def validate_facility_name(cls, v):
            from app.database.crud import ALL_FACILITIES_CACHE  # Importamos aquí para asegurar que tenemos la versión más reciente
            if not ALL_FACILITIES_CACHE:
                raise ValueError("La lista de instalaciones no está disponible. Por favor, intente nuevamente.")
            for facility in ALL_FACILITIES_CACHE:
                if v.lower() == facility.lower():
                    return facility
            raise ValueError(f"Instalación '{v}' no válida. Las opciones son: {', '.join(ALL_FACILITIES_CACHE)}")

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
    return MakeReservationArgs

def create_cancel_reservation_args():
    class CancelReservationArgs(BaseModel):
        dummy: Optional[str] = Field(default=None, description="Campo opcional dummy para evitar errores de parser en LangChain.")
    return CancelReservationArgs

def create_confirm_cancel_reservation_args():
    class ConfirmCancelReservationArgs(BaseModel):
        booking_id: Optional[str] = Field(default=None, description="ID de la reserva a cancelar")

        @field_validator('booking_id')
        @classmethod
        def validate_booking_id(cls, v):
            if v is None:
                raise ValueError("Debes especificar el ID de la reserva a cancelar.")
            try:
                int(v)  # Verificar que es un número
            except ValueError:
                raise ValueError("El ID de reserva debe ser un número")
            return v

    return ConfirmCancelReservationArgs

class BuscarInfoArgs(BaseModel):
    query: str = Field(description="La pregunta específica del usuario sobre el complejo deportivo (horarios, precios, reglas, servicios, etc.)")
    dummy: Optional[str] = Field(default=None, description="Campo opcional dummy para evitar errores de parser en LangChain.")

class ListarInstalacionesArgs(BaseModel):
    filtro_tipo: Optional[str] = Field(default=None, description="Opcional. Un tipo de instalación para filtrar la lista, ej: 'padel', 'tenis'.")
    dummy: Optional[str] = Field(default=None, description="Campo opcional dummy para evitar errores de parser en LangChain.")

class NoArgs(BaseModel):
    dummy: Optional[str] = Field(default=None, description="Campo opcional dummy para evitar errores de parser en LangChain.")