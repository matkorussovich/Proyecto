-- Crear la tabla para las instalaciones
CREATE TABLE public.instalaciones (
    id_instalacion SERIAL PRIMARY KEY, -- ID numérico autoincremental 
    ds_nombre VARCHAR(150) UNIQUE NOT NULL, -- Nombre único, ej: "Pista Padel 1"
    ds_tipo VARCHAR(50), -- Tipo, ej: "Padel", "Tenis", "Piscina"
    ds_descripcion TEXT, -- Descripción opcional
    created_at TIMESTAMPTZ DEFAULT now() -- Fecha de creación del registro
);


-- Crear la tabla para las reservas
CREATE TABLE public.reservas (
    id_reserva SERIAL PRIMARY KEY, -- ID numérico autoincremental
    id_instalacion INTEGER NOT NULL REFERENCES  public.instalaciones(id_instalacion), -- Enlace a la tabla facilities
    ds_nombre_cliente VARCHAR(200) NOT NULL, -- Nombre del usuario que reserva
    ds_telefono VARCHAR(20) NOT NULL DEFAULT '11111', -- Número de teléfono del cliente
    dt_fechahora_inicio TIMESTAMPTZ NOT NULL, -- Fecha y hora de INICIO de la reserva 
    dt_fechahora_fin TIMESTAMPTZ NOT NULL, -- Fecha y hora de FIN de la reserva
    dt_fechahora_creacion TIMESTAMPTZ DEFAULT now(), -- Fecha en que se hizo la reserva
    ds_estado VARCHAR(50) DEFAULT 'Confirmada', -- Estado: "Confirmada", "Cancelada", etc.
    ds_comentarios TEXT -- Notas opcionales
);

CREATE TABLE historial_chats (
    id SERIAL PRIMARY KEY,
    ds_telefono VARCHAR(20) UNIQUE NOT NULL,
    s3_chat_history_key VARCHAR(1024) NOT NULL,
    last_updated TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_telefono ON historial_chats (ds_telefono);

-- Agrego datos de instalaciones
INSERT INTO public.instalaciones (ds_nombre, ds_tipo, ds_descripcion) VALUES
('Pista Padel 1', 'Padel', 'Pista cristal cubierta y climatizada #1'),
('Pista Padel 2', 'Padel', 'Pista cristal cubierta y climatizada #2'),
('Pista Padel 3', 'Padel', 'Pista cristal cubierta y climatizada #3'),
('Pista Padel 4', 'Padel', 'Pista cristal cubierta y climatizada #4'),
('Pista Tenis Tierra 1', 'Tenis', 'Pista tierra batida #1 (Iluminada)'),
('Pista Tenis Tierra 2', 'Tenis', 'Pista tierra batida #2 (Iluminada)'),
('Pista Tenis Rápida 1', 'Tenis', 'Pista rápida resina #1 (Iluminada)'),
('Pista Tenis Rápida 2', 'Tenis', 'Pista rápida resina #2 (Iluminada)'),
('Piscina Climatizada', 'Piscina', 'Piscina semiolímpica 25m cubierta'),
('Piscina Exterior', 'Piscina', 'Piscina recreativa exterior (verano)'),
('Campo Hockey Hierba', 'Hockey', 'Campo Hockey Hierba artificial de agua'),
('Pista Fútbol Sala', 'Futsal', 'Pista cubierta parqué fútbol sala'),
('Gimnasio', 'Gym', 'Sala de Cardio, Musculación y Funcional');

-- Verifica que se insertaron
SELECT * FROM public.instalaciones;


-- Agregar columna es_overbooking (boolean)
ALTER TABLE public.reservas 
ADD COLUMN es_overbooking boolean DEFAULT false;

-- Agregar columna id_reserva_original (integer, puede ser null)
ALTER TABLE public.reservas 
ADD COLUMN id_reserva_original integer;

-- Agregar foreign key para id_reserva_original
ALTER TABLE public.reservas
ADD CONSTRAINT fk_reserva_original 
FOREIGN KEY (id_reserva_original) 
REFERENCES public.reservas(id_reserva);

-- Agregar índice para mejorar el rendimiento de búsquedas
CREATE INDEX idx_reservas_overbooking 
ON public.reservas(es_overbooking, id_reserva_original);