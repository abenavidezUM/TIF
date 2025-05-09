# NL2SQL para AdventureWorks con RAG

## Descripción General

Este proyecto implementa un sistema avanzado de traducción de lenguaje natural a SQL (NL2SQL) para la base de datos AdventureWorks. Utiliza técnicas de Retrieval Augmented Generation (RAG) combinadas con esquemas de base de datos en tiempo real para generar consultas SQL precisas y ejecutables a partir de preguntas en lenguaje natural.

## Características Principales

- **Procesamiento de Lenguaje Natural**: Convierte preguntas en español a consultas SQL ejecutables
- **Arquitectura RAG**: Utiliza vectorización y búsqueda semántica para mejorar la generación de consultas
- **Consulta de Esquema en Tiempo Real**: Extrae automáticamente la estructura actual de la base de datos
- **Corrección Automática de Consultas**: Detecta y corrige errores comunes en las consultas generadas
- **Interfaz Gráfica Amigable**: Proporciona una experiencia de usuario intuitiva
- **Depuración y Transparencia**: Permite ver el proceso de generación de consultas paso a paso

## Archivos Excluidos del Repositorio

Por razones de tamaño, los siguientes archivos no están incluidos en el repositorio y deben obtenerse de forma separada:

- **Base de datos AdventureWorks**: El archivo `data/AdventureWorks2019.bak` debe descargarse desde el sitio oficial de Microsoft y colocarse en el directorio `data/`.
- **Vectorstore FAISS**: El directorio `vectorstore/` se generará automáticamente la primera vez que se ejecute la aplicación.

## Arquitectura del Sistema

El sistema implementa una arquitectura cliente-servidor con los siguientes componentes:

```
┌─────────────────┐     ┌─────────────────────────────────────┐     ┌─────────────────┐
│                 │     │                                     │     │                 │
│  Cliente GUI    │────▶│  Servidor NL2SQL con RAG            │────▶│  SQL Server     │
│  (Tkinter)      │◀────│  (FastAPI + OpenAI + Vectorstore)   │◀────│  AdventureWorks │
│                 │     │                                     │     │                 │
└─────────────────┘     └─────────────────────────────────────┘     └─────────────────┘
```

## Componentes del Sistema

### 1. Servidor NL2SQL (`ejemplo_app_rag.py`)

El componente principal que implementa:

- **API RESTful con FastAPI**: Expone endpoints para procesar consultas
- **Vectorización Semántica**: Utiliza SentenceTransformer para crear y buscar embeddings
- **Procesamiento RAG**: Recupera y reordena documentos relevantes para mejorar los prompts
- **Generación con LLM**: Utiliza OpenAI GPT-3.5-Turbo para generar SQL
- **Consulta de Esquema**: Extrae metadatos de la base de datos SQL Server
- **Ejecución de Consultas**: Ejecuta las consultas generadas contra AdventureWorks

### 2. Cliente Gráfico (`cliente_nl2sql.py`)

Interfaz de usuario que proporciona:

- **Campo de Consulta**: Para ingresar preguntas en lenguaje natural
- **Visualización de SQL**: Muestra la consulta SQL generada
- **Visualización de Resultados**: Presenta los resultados en una tabla formateada
- **Opciones de Depuración**: Permite ver información detallada del proceso
- **Corrección Manual**: Permite modificar la consulta SQL antes de ejecutarla

### 3. Script de Inicio (`start_nl2sql.py`)

Facilita la puesta en marcha del sistema:

- **Verificación de Dependencias**: Comprueba que todos los componentes estén instalados
- **Inicio de Servicios**: Arranca el servidor y el cliente
- **Configuración de Base de Datos**: Proporciona herramientas para configurar la conexión

## Flujo del Proceso NL2SQL

1. **Etapa de Recuperación**:
   - Se vectoriza la pregunta del usuario
   - Se buscan documentos relevantes en el vectorstore (ejemplos, descripciones de tablas, relaciones)
   - Se consulta el esquema real de la base de datos para obtener metadatos actualizados

2. **Etapa de Selección de Tablas**:
   - Se identifica qué tablas son necesarias para responder la pregunta
   - Utiliza tanto el contexto recuperado como el esquema de la base de datos

3. **Etapa de Generación de SQL**:
   - Combina el esquema de las tablas seleccionadas con ejemplos relevantes
   - Genera consulta SQL precisa a través del LLM con un prompt detallado

4. **Etapa de Ejecución y Presentación**:
   - Ejecuta la consulta contra la base de datos AdventureWorks
   - Formatea y presenta los resultados al usuario

## Modelos y Tecnologías Utilizadas

### Modelos de IA

- **Modelo LLM**: OpenAI GPT-3.5-Turbo para la generación de SQL
- **Modelos de Embedding**: 
  - `all-MiniLM-L6-v2` (SentenceTransformer) para vectorización de documentos y preguntas
  - `cross-encoder/ms-marco-MiniLM-L-6-v2` para re-ranking de documentos

### Frameworks y Bibliotecas

- **FastAPI**: Para la creación de la API RESTful
- **FAISS**: Para el almacenamiento y búsqueda eficiente de vectores
- **pyodbc**: Para la conexión con SQL Server
- **pandas**: Para el procesamiento de resultados de consultas
- **Tkinter**: Para la interfaz gráfica de usuario
- **Rich**: Para una presentación mejorada en la terminal
- **SentenceTransformer**: Para la generación de embeddings y re-ranking

## Componentes RAG (Retrieval Augmented Generation)

### Vectorstore

El sistema utiliza un vectorstore FAISS para almacenar y recuperar:

- **Descripciones de Tablas**: Información sobre cada tabla de AdventureWorks
- **Relaciones entre Tablas**: Metadatos sobre claves foráneas y relaciones
- **Ejemplos de Selección**: Casos de uso para la selección de tablas
- **Ejemplos de Generación**: Pares de pregunta-SQL para mejorar la generación

### Procesamiento de Contexto

El sistema aprovecha dos tipos de contexto:

1. **Contexto RAG**: Documentos relevantes recuperados del vectorstore
2. **Contexto de Esquema**: Estructura real y actual de la base de datos

Ambos se combinan para generar prompts enriquecidos que mejoran la calidad del SQL generado.

## Mejoras Implementadas

1. **Schema-aware SQL Generation**: 
   - Consulta el esquema real de la base de datos antes de generar SQL
   - Extrae tablas, columnas, tipos de datos y relaciones directamente del sistema
   - Mejora la precisión de las consultas generadas con información actualizada

2. **Corrección Automática de Consultas**:
   - Detecta y corrige nombres de columnas erróneos
   - Resuelve problemas comunes como usar "Quantity" en lugar de "OrderQty"

3. **Prompts Mejorados**:
   - Incorpora ejemplos específicos y convenciones SQL para AdventureWorks
   - Incluye instrucciones detalladas sobre la sintaxis correcta para SQL Server
   - Proporciona información de contexto relevante para cada tipo de consulta

4. **Re-ranking de Documentos**:
   - Utiliza un modelo de cross-encoder para mejorar la relevancia de los documentos recuperados
   - Prioriza ejemplos y documentación más útiles para cada pregunta

## Estructura de Archivos

- **`ejemplo_app_rag.py`**: Servidor principal con la implementación RAG
- **`cliente_nl2sql.py`**: Cliente gráfico para interactuar con el sistema
- **`start_nl2sql.py`**: Script para iniciar todo el sistema
- **`setup_db.py`**: Herramienta para configurar la conexión a la base de datos
- **`data/`**: Directorio con archivos JSON de descripciones y ejemplos
- **`vectorstore/`**: Directorio donde se almacena el índice FAISS

## Requisitos del Sistema

- Python 3.8+
- Base de datos SQL Server con AdventureWorks instalada
- Controlador ODBC 17 para SQL Server
- API Key de OpenAI

## Instalación

1. Clonar el repositorio:
   ```
   git clone https://github.com/abenavidezUM/TIF.git
   cd TIF
   git checkout dev
   ```

2. Instalar dependencias:
   ```
   pip install -r requirements.txt
   ```

3. Descargar la base de datos AdventureWorks:
   - Visitar [Microsoft SQL Server Samples](https://github.com/Microsoft/sql-server-samples/releases/tag/adventureworks)
   - Descargar `AdventureWorks2019.bak`
   - Copiar a la carpeta `data/` del proyecto

4. Crear archivo `.env` con la configuración:
   ```
   OPENAI_API_KEY=sk-your-api-key
   SQL_SERVER=localhost,1433
   SQL_DATABASE=AdventureWorks2019
   SQL_USERNAME=sa
   SQL_PASSWORD=StrongPassword123!
   ```

## Uso

1. Iniciar el sistema completo:
   ```
   python start_nl2sql.py
   ```

2. Seleccionar la opción "Iniciar sistema completo" en el menú

3. Ingresar preguntas en lenguaje natural en la interfaz gráfica, como:
   - "¿Cuáles son los productos más vendidos?"
   - "¿Cuántos productos hay por categoría?"
   - "Mostrar los clientes que más gastaron junto con sus productos favoritos"

## Ventajas del Enfoque Híbrido (RAG + Esquema Real)

La combinación del enfoque RAG con la consulta de esquema en tiempo real proporciona varias ventajas:

1. **Precisión**: Las consultas se basan en la estructura actual de la base de datos
2. **Flexibilidad**: Funciona incluso cuando el esquema cambia o se actualiza
3. **Contextualización**: Utiliza ejemplos y conocimiento previo para mejorar la generación
4. **Robustez**: Proporciona mecanismos de fallback si algún componente falla

## Consideraciones para Desarrollo Futuro

- **Optimización de Consultas**: Implementar análisis de planes de ejecución para mejorar rendimiento
- **Personalización del Modelo**: Fine-tuning de modelos específicos para SQL Server/AdventureWorks
- **Expansión del Contexto**: Incluir estadísticas de la base de datos para mejorar decisiones
- **Soporte Multilingüe**: Expandir para admitir consultas en diferentes idiomas
- **Caché de Consultas**: Implementar almacenamiento de consultas frecuentes para mejorar la velocidad

## Conclusión

Este sistema NL2SQL para AdventureWorks demuestra cómo la combinación de técnicas RAG con la consulta de esquema en tiempo real puede mejorar significativamente la precisión y robustez de la generación de SQL a partir de lenguaje natural. La arquitectura modular facilita el mantenimiento y la ampliación del sistema para adaptarse a diferentes requisitos y casos de uso. 