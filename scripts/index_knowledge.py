import os
from dotenv import load_dotenv
from langchain_community.document_loaders import TextLoader 
from langchain_text_splitters import RecursiveCharacterTextSplitter, MarkdownHeaderTextSplitter
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_pinecone import PineconeVectorStore

load_dotenv()

# --- Configuración---
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
PINECONE_INDEX_NAME = "tfm-index"#"kb-tfm"
DOCUMENT_PATH = "data\knowledge-base.txt" 
EMBEDDING_MODEL_NAME = "intfloat/multilingual-e5-large"

# Configuración de headers para Markdown
headers_to_split_on = [
    ("#", "header1"),
    ("##", "header2"),
    ("###", "header3"),
]

try:
    # 1. Cargar el Documento
    print("Cargando documento...")
    loader = TextLoader(DOCUMENT_PATH, encoding='utf-8')
    documents = loader.load()
    print(f"Documento cargado. Número de páginas/documentos iniciales: {len(documents)}")
    
    if not documents:
        raise ValueError("El documento está vacío o no se pudo cargar correctamente.")
    
    # 2. Procesar Markdown
    print("Procesando estructura Markdown...")
    markdown_splitter = MarkdownHeaderTextSplitter(headers_to_split_on=headers_to_split_on)
    md_splits = []
    
    for doc in documents:
        # Dividir por headers de Markdown
        md_header_splits = markdown_splitter.split_text(doc.page_content)
        md_splits.extend(md_header_splits)
    
    print(f"Documento dividido en {len(md_splits)} secciones basadas en Markdown.")
    
    # 3. Dividir en Fragmentos más pequeños
    print("Dividiendo en fragmentos más pequeños...")
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=700,
        chunk_overlap=50
    )
    splits = text_splitter.split_documents(md_splits)
    print(f"Documento dividido en {len(splits)} fragmentos finales.")
    
    # 4. Inicializar Modelo de Embeddings
    print("Inicializando modelo de embeddings...")
    embeddings = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL_NAME)
    
    # 5. Crear/Actualizar Vector Store en Pinecone
    print(f"Conectando y subiendo datos al índice Pinecone '{PINECONE_INDEX_NAME}'...")
    vectorstore = PineconeVectorStore.from_documents(
        documents=splits,
        embedding=embeddings,
        index_name=PINECONE_INDEX_NAME
    )
    
    print("-" * 50)
    print(f"Se han cargado {len(splits)} fragmentos al índice '{PINECONE_INDEX_NAME}' de Pinecone.")
    print("Los fragmentos incluyen la estructura jerárquica de Markdown.")
    print("-" * 50)

except Exception as e:
    print(f"\nERROR DURANTE EL PROCESO: {e}")
    import traceback
    print(traceback.format_exc())