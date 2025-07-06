from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_pinecone import PineconeVectorStore

# --- Constantes para RAG ---
PINECONE_INDEX_NAME = "kb-tfm" 
EMBEDDING_MODEL_NAME = "intfloat/multilingual-e5-large"

# Variable global para almacenar el modelo de embeddings cacheado
EMBEDDINGS_MODEL = None

def initialize_embeddings():
    """Inicializa el modelo de embeddings y lo cachea globalmente."""
    global EMBEDDINGS_MODEL
    if EMBEDDINGS_MODEL is None:
        print("Cargando y cacheando el modelo de embeddings por primera vez...")
        EMBEDDINGS_MODEL = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL_NAME)
        print("Modelo de embeddings cargado exitosamente.")
    return EMBEDDINGS_MODEL

# === Función para RAG ===
def buscar_info_complejo(query: str) -> str:
    """Busca información relevante en la base de conocimiento del complejo deportivo para responder la pregunta del usuario."""
    print(f"\n--- Ejecutando RAG Tool: Buscando info para '{query}' ---")
    try:
        # Usar el modelo de embeddings cacheado
        if EMBEDDINGS_MODEL is None:
            # Esto no debería ocurrir si se llama a initialize_embeddings() al inicio,
            # pero es una salvaguarda.
            initialize_embeddings()

        # Conectar al índice existente
        print(f"Conectando a Pinecone (Índice: {PINECONE_INDEX_NAME})...")
        vectorstore = PineconeVectorStore.from_existing_index(
            index_name=PINECONE_INDEX_NAME,
            embedding=EMBEDDINGS_MODEL # Usar el modelo global
        )

        # Crear retriever y buscar
        retriever = vectorstore.as_retriever(search_kwargs={'k': 3}) # Obtener los 3 fragmentos más relevantes
        print("Recuperando fragmentos relevantes...")
        results = retriever.invoke(query)

        if not results:
            print("RAG: No se encontraron fragmentos relevantes.")
            return "No encontré información específica sobre eso en la base de conocimiento del complejo."
        else:
            # Formatear los resultados incluyendo la estructura de Markdown
            formatted_results = []
            for doc in results:
                # Extraer metadatos de headers
                metadata = doc.metadata
                header_info = []
                if 'header1' in metadata:
                    header_info.append(metadata['header1'])
                if 'header2' in metadata:
                    header_info.append(metadata['header2'])
                if 'header3' in metadata:
                    header_info.append(metadata['header3'])
                
                # Construir el resultado formateado
                result = doc.page_content
                if header_info:
                    result = f"Sección: {' > '.join(header_info)}\n{result}"
                
                formatted_results.append(result)

            context = "\n\n---\n\n".join(formatted_results)
            print(f"RAG: Contexto encontrado:\n{context[:500]}...")
            return f"Aquí tienes información relevante encontrada en la base de conocimiento del complejo:\n{context}"

    except Exception as e:
        print(f"ERROR en la herramienta RAG 'buscar_info_complejo': {e}")
        return "Lo siento, tuve un problema al buscar información en la base de conocimiento."