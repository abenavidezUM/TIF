"""
Aplicación de conversión de lenguaje natural a SQL para AdventureWorks 
con implementación completa de RAG (Retrieval Augmented Generation)
"""
import os
import json
import re
import logging
from typing import Dict, List, Optional, Any, Tuple
from pathlib import Path

# Bibliotecas externas
from dotenv import load_dotenv
import numpy as np
import openai
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import pyodbc
import pandas as pd
import tiktoken
from sentence_transformers import SentenceTransformer, util
from langchain_community.vectorstores import FAISS
from langchain.schema import Document
from langchain_community.docstore.in_memory import InMemoryDocstore

# Configuración de logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# Cargar variables de entorno
load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")

# Inicializar FastAPI
app = FastAPI(title="AdventureWorks NL a SQL con RAG")

# Configurar CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- MODELOS DE DATOS ---
class QueryRequest(BaseModel):
    question: str
    execute: bool = False
    debug: bool = False
    sql_override: Optional[str] = None

class QueryResponse(BaseModel):
    sql_query: str
    execution_result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    debug_info: Optional[Dict[str, Any]] = None

# --- CONFIGURACIÓN DE EMBEDDINGS Y MODELOS ---
# Inicializar modelo de embeddings
EMBEDDING_MODEL = SentenceTransformer('all-MiniLM-L6-v2')
RERANKING_MODEL = SentenceTransformer('cross-encoder/ms-marco-MiniLM-L-6-v2')

# Tokenizer para contar tokens
tokenizer = tiktoken.get_encoding("cl100k_base")

# --- CONFIGURACIÓN DE CARPETAS ---
DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

# Asegurar que la carpeta vectorstore existe
VECTOR_DIR = Path("vectorstore")
VECTOR_DIR.mkdir(exist_ok=True)

# --- CONFIGURACIÓN DE CONEXIÓN A BASE DE DATOS ---
def get_db_connection():
    """Establece conexión con SQL Server"""
    try:
        server = os.getenv("SQL_SERVER", "localhost,1433")
        database = os.getenv("SQL_DATABASE", "AdventureWorks2019")
        username = os.getenv("SQL_USERNAME", "sa")
        password = os.getenv("SQL_PASSWORD", "StrongPassword123!")
        
        conn_str = (
            f"DRIVER={{ODBC Driver 17 for SQL Server}};"
            f"SERVER={server};"
            f"DATABASE={database};"
            f"UID={username};"
            f"PWD={password};"
            f"TrustServerCertificate=yes;"
        )
        return pyodbc.connect(conn_str)
    except Exception as e:
        logger.error(f"Error de conexión a la base de datos: {str(e)}")
        return None

def execute_query(query: str) -> Dict[str, Any]:
    """Ejecuta una consulta SQL y devuelve los resultados como diccionario"""
    try:
        conn = get_db_connection()
        if not conn:
            return {"success": False, "error": "No se pudo conectar a la base de datos"}
        
        df = pd.read_sql(query, conn)
        conn.close()
        
        return {
            "success": True,
            "data": df.to_dict(orient="records"),
            "rows": len(df),
            "columns": list(df.columns)
        }
    except Exception as e:
        logger.error(f"Error al ejecutar consulta: {str(e)}")
        return {"success": False, "error": str(e)}

# Función para obtener el esquema real de la base de datos
def get_database_schema() -> Dict[str, Any]:
    """
    Consulta el esquema real de la base de datos AdventureWorks y devuelve información
    detallada sobre tablas, columnas y relaciones.
    """
    try:
        conn = get_db_connection()
        if not conn:
            logger.error("No se pudo conectar a la base de datos para obtener el esquema")
            return {}
        
        # Obtener información de tablas y columnas
        tables_query = """
        SELECT 
            t.name AS TableName,
            s.name AS SchemaName,
            ISNULL(ep.value, 'Sin descripción') AS TableDescription,
            c.name AS ColumnName,
            ty.name AS DataType,
            c.max_length,
            c.precision,
            c.scale,
            c.is_nullable,
            CASE WHEN EXISTS (
                SELECT 1 FROM sys.index_columns ic
                JOIN sys.indexes i ON ic.object_id = i.object_id AND ic.index_id = i.index_id
                WHERE i.is_primary_key = 1 AND ic.object_id = c.object_id AND ic.column_id = c.column_id
            ) THEN 1 ELSE 0 END AS IsPrimaryKey,
            ISNULL(ec.value, 'Sin descripción') AS ColumnDescription
        FROM sys.tables t
        JOIN sys.schemas s ON t.schema_id = s.schema_id
        JOIN sys.columns c ON t.object_id = c.object_id
        JOIN sys.types ty ON c.user_type_id = ty.user_type_id
        LEFT JOIN sys.extended_properties ep ON t.object_id = ep.major_id AND ep.minor_id = 0 AND ep.name = 'MS_Description'
        LEFT JOIN sys.extended_properties ec ON c.object_id = ec.major_id AND c.column_id = ec.minor_id AND ec.name = 'MS_Description'
        ORDER BY s.name, t.name, c.column_id
        """
        
        # Obtener información de relaciones (claves foráneas)
        relations_query = """
        SELECT 
            OBJECT_SCHEMA_NAME(f.parent_object_id) AS ParentSchema,
            OBJECT_NAME(f.parent_object_id) AS ParentTable,
            COL_NAME(fc.parent_object_id, fc.parent_column_id) AS ParentColumn,
            OBJECT_SCHEMA_NAME(f.referenced_object_id) AS ReferencedSchema,
            OBJECT_NAME(f.referenced_object_id) AS ReferencedTable,
            COL_NAME(fc.referenced_object_id, fc.referenced_column_id) AS ReferencedColumn
        FROM sys.foreign_keys f
        JOIN sys.foreign_key_columns fc ON f.object_id = fc.constraint_object_id
        ORDER BY ParentSchema, ParentTable, ParentColumn
        """
        
        # Ejecutar las consultas
        tables_df = pd.read_sql(tables_query, conn)
        relations_df = pd.read_sql(relations_query, conn)
        
        conn.close()
        
        # Transformar DataFrames a estructuras anidadas
        schema_data = {}
        tables_list = []
        
        # Procesar tablas y columnas
        for schema_name, group in tables_df.groupby('SchemaName'):
            for table_name, table_group in group.groupby('TableName'):
                # Obtener primera fila para descripción de tabla
                first_row = table_group.iloc[0]
                full_table_name = f"{schema_name}.{table_name}"
                
                # Procesar columnas
                columns = []
                for _, column in table_group.iterrows():
                    columns.append({
                        "name": column['ColumnName'],
                        "data_type": column['DataType'],
                        "is_nullable": bool(column['is_nullable']),
                        "is_primary_key": bool(column['IsPrimaryKey']),
                        "description": column['ColumnDescription']
                    })
                
                tables_list.append({
                    "name": full_table_name,
                    "description": first_row['TableDescription'],
                    "columns": columns
                })
        
        # Procesar relaciones
        relations_list = []
        for _, relation in relations_df.iterrows():
            relations_list.append({
                "table1": f"{relation['ParentSchema']}.{relation['ParentTable']}",
                "column1": relation['ParentColumn'],
                "table2": f"{relation['ReferencedSchema']}.{relation['ReferencedTable']}",
                "column2": relation['ReferencedColumn'],
                "relation": "references",  # FK -> PK relationship
                "description": f"Foreign key from {relation['ParentSchema']}.{relation['ParentTable']}.{relation['ParentColumn']} to {relation['ReferencedSchema']}.{relation['ReferencedTable']}.{relation['ReferencedColumn']}"
            })
        
        schema_data["tables"] = tables_list
        schema_data["relations"] = relations_list
        
        logger.info(f"Esquema de base de datos obtenido: {len(tables_list)} tablas, {len(relations_list)} relaciones")
        return schema_data
    
    except Exception as e:
        logger.error(f"Error al obtener esquema de la base de datos: {str(e)}")
        return {}

# Obtener el esquema al iniciar y guardarlo en caché
_schema_cache = None

def get_cached_schema():
    """Obtiene el esquema de la base de datos (desde caché o consultando si es necesario)"""
    global _schema_cache
    if _schema_cache is None:
        _schema_cache = get_database_schema()
    return _schema_cache

def refresh_schema_cache():
    """Refresca la caché del esquema de la base de datos"""
    global _schema_cache
    _schema_cache = get_database_schema()
    return _schema_cache

# --- CARGA DE DATOS ---
def load_json_file(filename: str) -> Dict:
    """Carga un archivo JSON desde la carpeta data"""
    try:
        file_path = DATA_DIR / filename
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error al cargar {filename}: {e}")
        return {}

# Cargar descripciones de tablas y relaciones
tables_desc = load_json_file("adventureworks_tables_description.json")
relations = load_json_file("adventureworks_relations.json")
selection_examples = load_json_file("adventureworks_selection_examples.json")
generation_examples = load_json_file("adventureworks_generation_examples.json")

# --- FUNCIONES DE PROCESAMIENTO DE DOCUMENTOS ---
def create_documents_from_tables() -> List[Document]:
    """Crea documentos de tablas para vectorización"""
    documents = []
    
    # Documentos para tablas
    for table in tables_desc:
        content = f"""
Tabla: {table['Name']}
Descripción: {table['Description']}
"""
        doc = Document(
            page_content=content,
            metadata={
                "type": "table",
                "table_name": table['Name'],
                "schema": table['Name'].split('.')[0] if '.' in table['Name'] else ""
            }
        )
        documents.append(doc)
    
    # Documentos para relaciones
    for relation in relations:
        content = f"""
Relación entre tablas:
Tabla1: {relation['Table1']} (Columna: {relation['Column1']})
Tabla2: {relation['Table2']} (Columna: {relation['Column2']})
Tipo: {relation['Relation']}
Descripción: {relation['Description']}
"""
        doc = Document(
            page_content=content,
            metadata={
                "type": "relation",
                "table1": relation['Table1'],
                "table2": relation['Table2'],
                "relation_type": relation['Relation']
            }
        )
        documents.append(doc)
    
    # Documentos para ejemplos de selección
    for example in selection_examples:
        tables_str = ", ".join(example.get('Tablas Seleccionadas', []))
        content = f"""
Ejemplo de Selección de Tablas:
Pregunta: {example['Pregunta']}
Tablas Seleccionadas: {tables_str}
"""
        doc = Document(
            page_content=content,
            metadata={
                "type": "selection_example",
                "tables": example.get('Tablas Seleccionadas', [])
            }
        )
        documents.append(doc)
    
    # Documentos para ejemplos de generación de SQL
    for example in generation_examples:
        content = f"""
Ejemplo de Generación SQL:
Pregunta: {example['Pregunta']}
Consulta SQL: {example.get('Consulta SQL Generada', '')}
"""
        tables = example.get('Tablas Utilizadas', [])
        # Si no hay tablas especificadas, extraerlas de la consulta
        if not tables and 'Consulta SQL Generada' in example:
            sql = example['Consulta SQL Generada']
            tables = extract_tables_from_query(sql)
            
        doc = Document(
            page_content=content,
            metadata={
                "type": "generation_example",
                "tables": tables
            }
        )
        documents.append(doc)
    
    logger.info(f"Creados {len(documents)} documentos para el vectorstore")
    return documents

# --- FUNCIONES DE PROCESAMIENTO DE TEXTO ---
def extract_tables_from_query(query: str) -> List[str]:
    """Extrae nombres de tablas de una consulta SQL"""
    if not query:
        return []
        
    # Normalizar consulta
    query = re.sub(r'--.*?\n', ' ', query)
    query = re.sub(r'/\*.*?\*/', ' ', query, flags=re.DOTALL)
    query = ' '.join(query.split()).lower()
    
    # Patrones para identificar tablas
    patterns = [
        r'from\s+\[?([a-zA-Z0-9_\.\[\]]+)\]?',
        r'join\s+\[?([a-zA-Z0-9_\.\[\]]+)\]?',
        r'into\s+\[?([a-zA-Z0-9_\.\[\]]+)\]?',
        r'update\s+\[?([a-zA-Z0-9_\.\[\]]+)\]?',
    ]
    
    tables = []
    for pattern in patterns:
        matches = re.finditer(pattern, query)
        for match in matches:
            table_name = match.group(1)
            # Limpiar corchetes y extraer nombre de tabla
            clean_name = re.sub(r'[\[\]]', '', table_name)
            if '.' in clean_name:
                schema, table = clean_name.rsplit('.', 1)
                tables.append(f"{schema}.{table}")
            else:
                tables.append(clean_name)
    
    # Eliminar duplicados
    return list(set(tables))

def extract_sql_query(text: str) -> str:
    """Extrae una consulta SQL desde un texto"""
    # Buscar consultas SQL con punto y coma
    pattern = r"(SELECT|INSERT|UPDATE|DELETE|CREATE|DROP|ALTER)[\s\S]+?;"
    match = re.search(pattern, text, re.IGNORECASE)
    
    if match:
        return match.group(0).strip()
    
    # Buscar sin punto y coma (por si acaso)
    pattern = r"(SELECT|INSERT|UPDATE|DELETE|CREATE|DROP|ALTER)[\s\S]+"
    match = re.search(pattern, text, re.IGNORECASE)
    return match.group(0).strip() if match else ""

def count_tokens(text: str) -> int:
    """Cuenta el número de tokens en un texto"""
    return len(tokenizer.encode(text))

# --- RAG: VECTORSTORE Y RETRIEVERS ---
def create_or_load_vectorstore():
    """Crea o carga el vectorstore FAISS"""
    vector_path = VECTOR_DIR / "adventureworks_faiss"
    
    # Comprobar si ya existe
    if os.path.exists(vector_path) and os.path.isdir(vector_path):
        try:
            # Cargar vectorstore existente
            vectorstore = FAISS.load_local(str(vector_path), EMBEDDING_MODEL, allow_dangerous_deserialization=True)
            logger.info(f"Vectorstore cargado desde {vector_path}")
            return vectorstore
        except Exception as e:
            logger.warning(f"Error al cargar vectorstore: {e}. Creando uno nuevo.")
    
    # Crear nuevo vectorstore
    documents = create_documents_from_tables()
    
    # Generar embeddings para los documentos
    embeddings = []
    for doc in documents:
        embedding = EMBEDDING_MODEL.encode(doc.page_content)
        embeddings.append(embedding)
    
    # Crear índice FAISS
    import faiss
    
    vector_dimension = len(embeddings[0])
    index = faiss.IndexFlatL2(vector_dimension)
    index.add(np.array(embeddings).astype('float32'))
    
    # Guardar índice y documentos
    faiss.write_index(index, str(vector_path / "index.faiss"))
    
    # Guardar documentos y sus metadatos
    with open(vector_path / "documents.json", "w") as f:
        json.dump([{
            "content": doc.page_content,
            "metadata": doc.metadata
        } for doc in documents], f)
    
    # Envolver en clase FAISS para interfaz compatible
    index_to_docstore_id = {i: str(i) for i in range(len(documents))}
    docstore = InMemoryDocstore({str(i): doc for i, doc in enumerate(documents)})
    vectorstore = FAISS(EMBEDDING_MODEL, index, docstore, index_to_docstore_id)
    vectorstore.save_local(str(vector_path))
    
    logger.info(f"Vectorstore creado y guardado en {vector_path}")
    return vectorstore

def retrieve_relevant_documents(question: str, document_types=None, top_k=10) -> List[Document]:
    """Recupera documentos relevantes del vectorstore"""
    # Obtener vectorstore
    vectorstore = create_or_load_vectorstore()
    
    # Convertir pregunta a embedding
    question_embedding = EMBEDDING_MODEL.encode(question)
    
    # Buscar documentos similares
    scores, indices = vectorstore.index.search(
        np.array([question_embedding]).astype('float32'), 
        k=top_k * 2  # Recuperamos más para poder filtrar
    )
    
    # Filtrar por tipos de documentos si es necesario
    retrieved_docs = []
    for i, idx in enumerate(indices[0]):
        # Convertir idx de np.int64 a int de Python para evitar errores de serialización
        idx_int = int(idx)
        if idx_int < len(vectorstore.docstore._dict):
            doc = vectorstore.docstore._dict[str(idx_int)]
            # Si no hay filtro de tipos o el tipo del documento está en los tipos solicitados
            if not document_types or doc.metadata.get('type') in document_types:
                # Convertir score de np.float32 a float de Python
                retrieved_docs.append((doc, float(scores[0][i])))
    
    # Limitar a top_k
    retrieved_docs = retrieved_docs[:top_k]
    
    # Ordenar por puntuación (menor distancia es mejor)
    retrieved_docs.sort(key=lambda x: x[1])
    
    # Devolver solo los documentos
    return [doc for doc, _ in retrieved_docs]

def rerank_documents(question: str, docs: List[Document], top_k=5) -> List[Document]:
    """Re-rankea documentos usando un modelo de cross-encoder"""
    if not docs:
        return []
    
    doc_texts = [doc.page_content for doc in docs]
    
    # Usar cross-encoder para re-ranking
    # El SentenceTransformer no tiene método predict, usamos la forma correcta
    scores = []
    for doc_text in doc_texts:
        # Para cross-encoder calculamos la similitud entre pregunta y documento
        embeddings1 = EMBEDDING_MODEL.encode(question, convert_to_tensor=True)
        embeddings2 = EMBEDDING_MODEL.encode(doc_text, convert_to_tensor=True)
        similarity = util.pytorch_cos_sim(embeddings1, embeddings2).item()
        scores.append(float(similarity))  # Convertir a float de Python
    
    # Combinar documentos con sus nuevas puntuaciones
    doc_score_pairs = list(zip(docs, scores))
    
    # Ordenar por puntuación en orden descendente
    doc_score_pairs.sort(key=lambda x: x[1], reverse=True)
    
    # Devolver los top_k documentos
    return [doc for doc, _ in doc_score_pairs[:top_k]]

# --- FUNCIONES LLM ---
def get_tables_for_question(question: str, debug=False) -> Tuple[List[str], Dict]:
    """Identifica las tablas necesarias para responder una pregunta usando RAG"""
    debug_info = {}
    
    try:
        # Paso 1: Recuperar documentos relevantes
        logger.info(f"Buscando documentos relevantes para: {question}")
        retrieved_docs = retrieve_relevant_documents(
            question, 
            document_types=["table", "relation", "selection_example"],
            top_k=15
        )
        
        # Paso 2: Re-rankear documentos
        ranked_docs = rerank_documents(question, retrieved_docs, top_k=7)
        
        # Guardar para depuración
        if debug:
            debug_info["retrieved_documents"] = [
                {"content": doc.page_content, "metadata": doc.metadata}
                for doc in retrieved_docs[:10]
            ]
            debug_info["reranked_documents"] = [
                {"content": doc.page_content, "metadata": doc.metadata}
                for doc in ranked_docs
            ]
        
        # Obtener el esquema real de la base de datos
        schema_data = get_cached_schema()
        
        # Construir información del esquema 
        database_structure = "# ESQUEMA DE LA BASE DE DATOS ADVENTUREWORKS #\n\n"
        
        # Si tenemos el esquema real, utilizarlo
        if schema_data and 'tables' in schema_data and schema_data['tables']:
            # Agrupar tablas por esquema
            schema_tables = {}
            for table in schema_data['tables']:
                schema = table['name'].split('.')[0] if '.' in table['name'] else "dbo"
                if schema not in schema_tables:
                    schema_tables[schema] = []
                schema_tables[schema].append(table)
            
            # Añadir información de tablas por esquema
            for schema, tables in schema_tables.items():
                database_structure += f"## Esquema: {schema}\n\n"
                for table in tables:
                    database_structure += f"### Tabla: {table['name']}\n"
                    database_structure += f"Descripción: {table['description']}\n\n"
                    database_structure += "Columnas:\n"
                    for column in table.get('columns', []):
                        pk_marker = " (PK)" if column.get('is_primary_key') else ""
                        nullable = " (NULL)" if column.get('is_nullable') else " (NOT NULL)"
                        database_structure += f"- {column['name']}{pk_marker}{nullable}: {column.get('data_type', 'unknown')} - {column.get('description', 'Sin descripción')}\n"
                    database_structure += "\n"
            
            # Añadir información de relaciones
            database_structure += "## Relaciones entre tablas\n\n"
            for relation in schema_data.get('relations', []):
                database_structure += f"- {relation['table1']} ({relation['column1']}) {relation['relation']} {relation['table2']} ({relation['column2']}): {relation['description']}\n"
        else:
            # Usar la información de esquema estática como fallback
            # Agrupar tablas por esquema
            schema_tables = {}
            for table in tables_desc:
                schema = table['Name'].split('.')[0] if '.' in table['Name'] else "dbo"
                if schema not in schema_tables:
                    schema_tables[schema] = []
                schema_tables[schema].append(table)
            
            # Añadir información de tablas por esquema
            for schema, tables in schema_tables.items():
                database_structure += f"## Esquema: {schema}\n\n"
                for table in tables:
                    database_structure += f"### Tabla: {table['Name']}\n"
                    database_structure += f"Descripción: {table['Description']}\n\n"
            
            # Añadir información de relaciones
            database_structure += "## Relaciones entre tablas\n\n"
            for relation in relations:
                database_structure += f"- {relation['Table1']} ({relation['Column1']}) {relation['Relation']} {relation['Table2']} ({relation['Column2']}): {relation['Description']}\n"
        
        # Preparar contexto con documentos recuperados
        retrieved_context = "\n\n".join([doc.page_content for doc in ranked_docs])
        
        # Prompt mejorado para la selección de tablas
        table_selection_prompt = f"""
Eres un agente especialista en la base de datos AdventureWorks encargado de seleccionar exclusivamente las tablas relevantes para responder a la pregunta dada.

Esquema de la base de datos AdventureWorks:
{database_structure}

Contexto Adicional (ejemplos y documentación relevante):
{retrieved_context}

Seguir los siguientes pasos:
1. Analizar cada palabra clave en la pregunta e identificar las entidades mencionadas (productos, ventas, empleados, etc.).
2. Seleccionar las tablas necesarias para acceder a la información solicitada.
3. Asegurarse que las tablas seleccionadas tengan una relación directa entre sí.
4. Incluir tablas de unión necesarias para conectar las tablas principales.

CONSIDERACIONES IMPORTANTES:
- Para consultas sobre productos, debes incluir Production.Product
- Para consultas sobre ventas, debes incluir Sales.SalesOrderHeader y posiblemente Sales.SalesOrderDetail
- Para consultas sobre empleados, debes incluir HumanResources.Employee y posiblemente Person.Person
- Para consultas sobre clientes, debes incluir Sales.Customer y posiblemente Person.Person
- Para consultas sobre inventario, debes incluir Production.ProductInventory
- Al relacionar productos con categorías, debes incluir Production.ProductSubcategory y Production.ProductCategory

EJEMPLO N°1
Pregunta: ¿Cuáles son los productos más vendidos?
Tablas seleccionadas: Production.Product, Sales.SalesOrderDetail

Razonamiento: Para saber qué productos son los más vendidos, necesitamos información de la tabla Production.Product para los detalles del producto y Sales.SalesOrderDetail para las cantidades vendidas de cada producto.

EJEMPLO N°2
Pregunta: ¿Cuántos productos hay por categoría?
Tablas seleccionadas: Production.Product, Production.ProductSubcategory, Production.ProductCategory

Razonamiento: Para contar los productos por categoría, necesitamos Production.Product que contiene los productos, Production.ProductSubcategory que relaciona productos con subcategorías, y Production.ProductCategory que contiene las categorías principales.

EJEMPLO N°3
Pregunta: ¿Cuáles son los clientes que más compran?
Tablas seleccionadas: Sales.Customer, Sales.SalesOrderHeader, Person.Person

Razonamiento: Para saber qué clientes compran más, necesitamos Sales.Customer para la información del cliente, Sales.SalesOrderHeader para los datos de compras, y Person.Person para obtener nombres completos de los clientes.

Pregunta: {question}
Tablas seleccionadas:
"""
        
        # Paso 3: Usar LLM para identificar tablas basado en el contexto
        response = openai.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": table_selection_prompt}],
            temperature=0.1
        )
        
        tables_text = response.choices[0].message.content.strip()
        
        # Guardar para depuración
        if debug:
            debug_info["llm_table_prompt"] = table_selection_prompt
            debug_info["llm_table_response"] = tables_text
        
        # Extraer tablas de la respuesta
        # Podría ser una lista separada por comas, una por línea o una lista en formato Python
        if '[' in tables_text and ']' in tables_text:
            # Parece una lista en formato Python
            try:
                # Extraer contenido entre corchetes
                content = tables_text[tables_text.find('['):tables_text.rfind(']')+1]
                selected_tables = eval(content)
            except:
                # Si falla, intentar otras formas
                selected_tables = re.split(r'[,\s]+', tables_text)
        else:
            # Dividir por comas o espacios
            selected_tables = re.split(r'[,\s]+', tables_text)
        
        # Limpiar nombres de tablas
        selected_tables = [t.strip().strip("'\"[]") for t in selected_tables if t.strip()]
        
        # Filtrar tablas vacías
        selected_tables = [t for t in selected_tables if t]
        
        # Si no se pudieron identificar tablas, usar una selección por defecto
        # basada en el sistema de votación existente
        if not selected_tables:
            # Paso 3: Extraer nombres de tablas de los documentos de selección
            table_votes = {}
            
            # Primero, mirar ejemplos similares
            for doc in ranked_docs:
                if doc.metadata.get('type') == 'selection_example':
                    tables = doc.metadata.get('tables', [])
                    for table in tables:
                        table_votes[table] = table_votes.get(table, 0) + 3  # Peso mayor para ejemplos directos
            
            # Luego, considerar documentos de tablas
            for doc in ranked_docs:
                if doc.metadata.get('type') == 'table':
                    table_name = doc.metadata.get('table_name', '')
                    if table_name:
                        table_votes[table_name] = table_votes.get(table_name, 0) + 2
            
            # Finalmente, considerar relaciones
            for doc in ranked_docs:
                if doc.metadata.get('type') == 'relation':
                    table1 = doc.metadata.get('table1', '')
                    table2 = doc.metadata.get('table2', '')
                    if table1:
                        table_votes[table1] = table_votes.get(table1, 0) + 1
                    if table2:
                        table_votes[table2] = table_votes.get(table2, 0) + 1
            
            # Ordenar tablas por votos y seleccionar las más votadas
            sorted_tables = sorted(table_votes.items(), key=lambda x: x[1], reverse=True)
            selected_tables = [table for table, _ in sorted_tables[:5]]  # Top 5 tablas
        
        # Guardar para depuración
        if debug:
            debug_info["table_votes"] = table_votes if "table_votes" in locals() else {}
            debug_info["selected_tables"] = selected_tables
        
        logger.info(f"Tablas seleccionadas: {selected_tables}")
        return selected_tables, debug_info
    
    except Exception as e:
        logger.error(f"Error al identificar tablas: {str(e)}")
        # Devolver algunas tablas comunes como fallback
        return ["Production.Product", "Sales.SalesOrderHeader", "Person.Person"], {"error": str(e)}

def generate_sql_query(question: str, tables: List[str], debug=False) -> Tuple[str, Dict]:
    """Genera una consulta SQL para la pregunta dada usando RAG"""
    debug_info = {}
    
    try:
        # Paso 1: Recuperar documentos relevantes, incluyendo ejemplos de generación
        logger.info(f"Buscando documentos relevantes para generación SQL: {question}")
        
        # Recuperar ejemplos de generación similares
        generation_docs = retrieve_relevant_documents(
            question, 
            document_types=["generation_example"],
            top_k=5
        )
        
        # Recuperar documentos de tablas relevantes
        table_docs = []
        for table in tables:
            table_specific_docs = retrieve_relevant_documents(
                f"table {table}", 
                document_types=["table", "relation"],
                top_k=3
            )
            table_docs.extend(table_specific_docs)
        
        # Combinar y reordenar documentos
        all_docs = generation_docs + table_docs
        ranked_docs = rerank_documents(question, all_docs, top_k=7)
        
        # Guardar para depuración
        if debug:
            debug_info["retrieved_documents"] = [
                {"content": doc.page_content, "metadata": doc.metadata}
                for doc in all_docs[:10]
            ]
            debug_info["reranked_documents"] = [
                {"content": doc.page_content, "metadata": doc.metadata}
                for doc in ranked_docs
            ]
        
        # Obtener esquema real de la base de datos
        schema_data = get_cached_schema()
        
        # Construir esquema estructurado de la base de datos enfocado en las tablas seleccionadas
        database_structure = "# ESQUEMA DE LAS TABLAS SELECCIONADAS #\n\n"
        
        # Si tenemos esquema real, utilizarlo
        if schema_data and 'tables' in schema_data and schema_data['tables']:
            # Filtrar solo las tablas seleccionadas
            selected_tables_info = []
            for table_info in schema_data['tables']:
                if any(table_info['name'].lower() == table.lower() for table in tables):
                    selected_tables_info.append(table_info)
            
            # Añadir información detallada de las tablas seleccionadas
            for table_info in selected_tables_info:
                database_structure += f"## Tabla: {table_info['name']}\n"
                database_structure += f"Descripción: {table_info['description']}\n\n"
                
                # Añadir columnas
                database_structure += "Columnas:\n"
                for column in table_info.get('columns', []):
                    pk_marker = " (PK)" if column.get('is_primary_key') else ""
                    nullable = " (NULL)" if column.get('is_nullable') else " (NOT NULL)"
                    database_structure += f"- {column['name']}{pk_marker}{nullable}: {column.get('data_type', 'unknown')} - {column.get('description', 'Sin descripción')}\n"
                database_structure += "\n"
            
            # Añadir relaciones relevantes
            database_structure += "\n## Relaciones entre tablas seleccionadas\n\n"
            for relation in schema_data.get('relations', []):
                if any(relation['table1'].lower() == table.lower() for table in tables) or \
                   any(relation['table2'].lower() == table.lower() for table in tables):
                    database_structure += f"- {relation['table1']} ({relation['column1']}) {relation['relation']} {relation['table2']} ({relation['column2']})\n"
        else:
            # Usar información estática como fallback
            # Añadir información detallada de las tablas seleccionadas
            for table_name in tables:
                table_info = next((t for t in tables_desc if t['Name'] == table_name), None)
                if table_info:
                    database_structure += f"## Tabla: {table_info['Name']}\n"
                    database_structure += f"Descripción: {table_info['Description']}\n\n"
                    
                    # Añadir columnas si están disponibles (aunque en nuestro ejemplo no tenemos esta información)
                    database_structure += "Columnas principales:\n"
                    
                    # Definir columnas principales para tablas comunes
                    if table_name == "Production.Product":
                        database_structure += "- ProductID (PK)\n- Name (nombre del producto)\n- ProductNumber\n- Color\n- StandardCost\n- ListPrice\n- Size\n- Weight\n- ProductSubcategoryID (FK a Production.ProductSubcategory)\n"
                    elif table_name == "Sales.SalesOrderHeader":
                        database_structure += "- SalesOrderID (PK)\n- CustomerID (FK a Sales.Customer)\n- SalesPersonID (FK a Sales.SalesPerson)\n- OrderDate\n- DueDate\n- ShipDate\n- Status\n- TotalDue\n"
                    elif table_name == "Sales.SalesOrderDetail":
                        database_structure += "- SalesOrderID (PK, FK a Sales.SalesOrderHeader)\n- SalesOrderDetailID (PK)\n- OrderQty (cantidad ordenada)\n- ProductID (FK a Production.Product)\n- UnitPrice\n- LineTotal\n"
                    elif table_name == "Production.ProductCategory":
                        database_structure += "- ProductCategoryID (PK)\n- Name (nombre de la categoría)\n"
                    elif table_name == "Production.ProductSubcategory":
                        database_structure += "- ProductSubcategoryID (PK)\n- ProductCategoryID (FK a Production.ProductCategory)\n- Name (nombre de la subcategoría)\n"
                    elif table_name == "Person.Person":
                        database_structure += "- BusinessEntityID (PK)\n- PersonType\n- FirstName\n- LastName\n- EmailPromotion\n"
                    elif table_name == "Sales.Customer":
                        database_structure += "- CustomerID (PK)\n- PersonID (FK a Person.Person)\n- StoreID (FK a Sales.Store)\n- TerritoryID (FK a Sales.SalesTerritory)\n"
                    elif table_name == "Production.ProductInventory":
                        database_structure += "- ProductID (PK, FK a Production.Product)\n- LocationID (PK, FK a Production.Location)\n- Shelf\n- Bin\n- Quantity\n"
                    else:
                        database_structure += "- No se dispone de información detallada de columnas para esta tabla\n"
            
            # Añadir relaciones relevantes
            database_structure += "\n## Relaciones entre tablas seleccionadas\n\n"
            for relation in relations:
                if relation['Table1'] in tables or relation['Table2'] in tables:
                    database_structure += f"- {relation['Table1']} ({relation['Column1']}) {relation['Relation']} {relation['Table2']} ({relation['Column2']}): {relation['Description']}\n"
        
        # Preparar el contexto con ejemplos
        context_parts = [doc.page_content for doc in ranked_docs]
        
        # Añadir también descripciones directas de las tablas seleccionadas
        for table in tables:
            table_info = next((t for t in tables_desc if t['Name'].lower() == table.lower()), None)
            if table_info:
                context_parts.append(f"Tabla: {table_info['Name']}\nDescripción: {table_info['Description']}")
        
        # Filtrar duplicados preservando el orden
        seen = set()
        filtered_context = []
        for part in context_parts:
            if part not in seen:
                seen.add(part)
                filtered_context.append(part)
        
        context = "\n\n".join(filtered_context)
        
        # Verificar si el contexto es demasiado largo y truncarlo si es necesario
        token_count = count_tokens(context)
        if token_count > 3000:  # límite arbitrario para dejar espacio para el resto del prompt
            logger.warning(f"Contexto demasiado largo ({token_count} tokens), truncando...")
            
            # Truncar a aproximadamente 3000 tokens
            parts = context.split("\n\n")
            truncated_parts = []
            current_tokens = 0
            
            for part in parts:
                part_tokens = count_tokens(part)
                if current_tokens + part_tokens <= 3000:
                    truncated_parts.append(part)
                    current_tokens += part_tokens
                else:
                    break
            
            context = "\n\n".join(truncated_parts)
            logger.info(f"Contexto truncado a {current_tokens} tokens")
        
        # Prompt mejorado para generar consultas SQL
        sql_generation_prompt = f"""
Eres un agente especialista en la traducción de preguntas en lenguaje natural a consultas en lenguaje SQL para la base de datos AdventureWorks.
Tu tarea es generar una consulta SQL precisa que responda exactamente a la pregunta del usuario.

ESQUEMA DE LA BASE DE DATOS ADVENTUREWORKS:
{database_structure}

ESPECIFICACIONES Y CONVENCIONES IMPORTANTES:

1. NOMBRES DE TABLAS Y COLUMNAS:
   - Usa siempre el formato completo [Schema].[Table].[Column] con corchetes, por ejemplo [Production].[Product].[Name]
   - Respeta mayúsculas/minúsculas de los nombres: ProductID, SalesOrderDetail, etc.

2. FORMATO DE JOINS:
   - Usa la sintaxis de ANSI SQL para los JOINs (INNER JOIN, LEFT JOIN)
   - Incluye aliases para las tablas solo cuando sea necesario para claridad
   - Asegúrate de que todas las relaciones sean correctas según las claves foráneas

3. FUNCIONES ESPECÍFICAS:
   - Para consultas que involucran los productos más vendidos, unir Production.Product con Sales.SalesOrderDetail y sumar OrderQty
   - Para consultas de ingresos/ventas, usa el campo TotalDue de Sales.SalesOrderHeader o LineTotal de Sales.SalesOrderDetail
   - Para fechas, usa OrderDate de Sales.SalesOrderHeader para filtrar períodos

4. PARTICULARIDADES DE ADVENTUREWORKS:
   - Para obtener el nombre completo de una persona, concatena con + los campos FirstName y LastName de Person.Person
   - Para consultas sobre categorías, recuerda la jerarquía: Product → ProductSubcategory → ProductCategory
   - Para filtros de inventario, usa Quantity de Production.ProductInventory
   - Para consultar información del cliente, recuerda que Sales.Customer puede estar vinculado a Person.Person o a Store

5. OPTIMIZACIÓN DE CONSULTAS:
   - Incluye solo los JOINs necesarios para responder la pregunta
   - Utiliza subconsultas solo cuando sea absolutamente necesario
   - Agrega TOP N cuando la pregunta pida "los mejores", "los principales", etc.
   - Incluye ORDER BY para ordenar resultados cuando se solicite un orden específico

EJEMPLOS DE CONSULTAS SQL CORRECTAS PARA ADVENTUREWORKS:

Ejemplo 1:
Pregunta: ¿Cuáles son los 5 productos más vendidos?
Consulta SQL: 
SELECT TOP 5 [Production].[Product].[Name] AS ProductName, 
SUM([Sales].[SalesOrderDetail].[OrderQty]) AS TotalQuantitySold
FROM [Production].[Product]
INNER JOIN [Sales].[SalesOrderDetail] ON [Production].[Product].[ProductID] = [Sales].[SalesOrderDetail].[ProductID]
GROUP BY [Production].[Product].[Name]
ORDER BY TotalQuantitySold DESC;

Ejemplo 2:
Pregunta: ¿Cuántos productos hay por categoría?
Consulta SQL:
SELECT [Production].[ProductCategory].[Name] AS CategoryName,
COUNT([Production].[Product].[ProductID]) AS ProductCount
FROM [Production].[Product]
INNER JOIN [Production].[ProductSubcategory] ON [Production].[Product].[ProductSubcategoryID] = [Production].[ProductSubcategory].[ProductSubcategoryID]
INNER JOIN [Production].[ProductCategory] ON [Production].[ProductSubcategory].[ProductCategoryID] = [Production].[ProductCategory].[ProductCategoryID]
GROUP BY [Production].[ProductCategory].[Name]
ORDER BY ProductCount DESC;

Ejemplo 3:
Pregunta: Listar los ingresos totales por territorio de ventas
Consulta SQL:
SELECT [Sales].[SalesTerritory].[Name] AS Territory,
SUM([Sales].[SalesOrderHeader].[TotalDue]) AS TotalRevenue
FROM [Sales].[SalesOrderHeader]
INNER JOIN [Sales].[SalesTerritory] ON [Sales].[SalesOrderHeader].[TerritoryID] = [Sales].[SalesTerritory].[TerritoryID]
GROUP BY [Sales].[SalesTerritory].[Name]
ORDER BY TotalRevenue DESC;

Contexto adicional (ejemplos y tablas relevantes):
{context}

PREGUNTA: {question}

TABLAS SELECCIONADAS: {', '.join(tables)}

Basado en la información anterior, genera una única consulta SQL para SQL Server (T-SQL) que responda precisamente a la pregunta.
Devuelve SOLO la consulta SQL, sin explicaciones ni comentarios.
Asegúrate de que la consulta termine con punto y coma (;) y siga todas las especificaciones mencionadas.
Consulta SQL:
"""
        
        # Guardar para depuración
        if debug:
            debug_info["llm_prompt"] = sql_generation_prompt
            prompt_tokens = count_tokens(sql_generation_prompt)
            debug_info["prompt_tokens"] = prompt_tokens
        
        # Llamar a la API
        response = openai.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": sql_generation_prompt}],
            temperature=0.1
        )
        
        sql_text = response.choices[0].message.content.strip()
        
        # Guardar para depuración
        if debug:
            debug_info["llm_response"] = sql_text
        
        # Extraer consulta SQL
        sql_query = extract_sql_query(sql_text)
        
        # Si no se pudo extraer, usar el texto completo
        if not sql_query and sql_text:
            sql_query = sql_text
        
        logger.info(f"SQL generado: {sql_query[:100]}...")
        return sql_query, debug_info
    
    except Exception as e:
        logger.error(f"Error al generar SQL: {str(e)}")
        return "", {"error": str(e)}

# --- API ENDPOINTS ---
@app.get("/health")
def health_check():
    """Endpoint para verificar que la API está funcionando"""
    return {"status": "ok"}

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Maneja excepciones globales"""
    logger.error(f"Error global: {str(exc)}")
    return JSONResponse(
        status_code=500,
        content={"error": str(exc)}
    )

@app.post("/query", response_model=QueryResponse)
def process_query(request: QueryRequest):
    """Procesa una pregunta en lenguaje natural y devuelve una consulta SQL"""
    debug_info = {} if request.debug else None
    
    try:
        question = request.question
        logger.info(f"Procesando consulta: {question}")
        
        # Si se proporciona una consulta SQL personalizada, usarla directamente
        if request.sql_override:
            logger.info("Usando consulta SQL personalizada")
            sql_query = request.sql_override
            sql_debug = {"note": "Se usó una consulta SQL personalizada"}
            if request.debug:
                debug_info = {"sql_override": True, "sql_generation": sql_debug}
        else:
            # Paso 1: Identificar tablas relevantes
            logger.info("Identificando tablas relevantes...")
            tables, tables_debug = get_tables_for_question(question, debug=request.debug)
            if request.debug:
                debug_info["tables_selection"] = tables_debug
                
            if not tables:
                error_msg = "No se pudieron identificar tablas relevantes"
                logger.error(error_msg)
                raise HTTPException(status_code=400, detail=error_msg)
            
            logger.info(f"Tablas identificadas: {tables}")
            
            # Paso 2: Generar consulta SQL
            logger.info("Generando consulta SQL...")
            try:
                sql_query, sql_debug = generate_sql_query(question, tables, debug=request.debug)
                if request.debug:
                    debug_info["sql_generation"] = sql_debug
            except Exception as e:
                logger.error(f"Error al generar SQL: {str(e)}")
                raise HTTPException(status_code=400, detail=f"Error al generar SQL: {str(e)}")
                
            if not sql_query:
                error_msg = "No se pudo generar una consulta SQL válida"
                logger.error(error_msg)
                raise HTTPException(status_code=400, detail=error_msg)
        
        logger.info(f"SQL a ejecutar: {sql_query[:100]}...")
        
        # Paso 3: Ejecutar consulta si se solicita
        result = None
        if request.execute:
            logger.info("Ejecutando consulta SQL...")
            result = execute_query(sql_query)
            if request.debug:
                debug_info["execution"] = result
        
        # Paso 4: Devolver respuesta
        return QueryResponse(
            sql_query=sql_query,
            execution_result=result,
            error=result.get("error") if result and not result.get("success") else None,
            debug_info=debug_info
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error en process_query: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error interno: {str(e)}")

@app.get("/vector-info")
def vector_info():
    """Devuelve información sobre el vectorstore"""
    try:
        vectorstore = create_or_load_vectorstore()
        
        # Contar documentos por tipo
        doc_types = {}
        for doc_id in vectorstore.docstore._dict:
            doc = vectorstore.docstore._dict[doc_id]
            doc_type = doc.metadata.get("type", "unknown")
            doc_types[doc_type] = doc_types.get(doc_type, 0) + 1
        
        return {
            "vector_dimension": vectorstore.index.d,
            "document_count": len(vectorstore.docstore._dict),
            "document_types": doc_types
        }
    except Exception as e:
        logger.error(f"Error al obtener información del vectorstore: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")

# Añadir endpoint para actualizar el esquema
@app.post("/refresh-schema")
def refresh_schema():
    """Actualiza el esquema de la base de datos"""
    try:
        schema = refresh_schema_cache()
        return {
            "success": True,
            "tables_count": len(schema.get('tables', [])),
            "relations_count": len(schema.get('relations', []))
        }
    except Exception as e:
        logger.error(f"Error al actualizar el esquema: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")

# --- INICIO DE LA APLICACIÓN ---
if __name__ == "__main__":
    import uvicorn
    
    # Crear vectorstore si no existe
    logger.info("Verificando/creando vectorstore...")
    create_or_load_vectorstore()
    
    # Cargar el esquema de la base de datos
    logger.info("Cargando esquema de la base de datos...")
    get_cached_schema()
    
    logger.info("Iniciando servidor NL a SQL con RAG para AdventureWorks...")
    logger.info("Para probar: curl -X POST -H 'Content-Type: application/json' -d '{\"question\":\"¿Cuántos productos hay por categoría?\"}' http://localhost:8000/query")
    uvicorn.run(app, host="0.0.0.0", port=8000) 