#!/usr/bin/env python
"""
Utilidad para verificar y configurar la conexión a la base de datos SQL Server
"""
import os
import sys
import pyodbc
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich import print as rprint

# Cargar variables de entorno
load_dotenv()

console = Console()

def verificar_drivers():
    """Verifica los drivers ODBC disponibles"""
    try:
        drivers = pyodbc.drivers()
        if not drivers:
            return False, "No se encontraron drivers ODBC instalados."
        
        # Verificar si existe el driver para SQL Server
        sql_drivers = [d for d in drivers if 'SQL Server' in d]
        if not sql_drivers:
            return False, f"No se encontraron drivers para SQL Server. Drivers disponibles: {', '.join(drivers)}"
        
        return True, sql_drivers
    except Exception as e:
        return False, f"Error al verificar drivers: {str(e)}"

def probar_conexion():
    """Prueba la conexión a SQL Server usando la configuración actual"""
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
        
        # Intentar conexión
        conn = pyodbc.connect(conn_str, timeout=5)
        cursor = conn.cursor()
        
        # Ejecutar una consulta simple
        cursor.execute("SELECT @@VERSION")
        version = cursor.fetchone()[0]
        
        # Verificar tablas de AdventureWorks
        cursor.execute("""
            SELECT COUNT(*) 
            FROM INFORMATION_SCHEMA.TABLES 
            WHERE TABLE_TYPE = 'BASE TABLE'
        """)
        table_count = cursor.fetchone()[0]
        
        conn.close()
        
        return True, {
            "version": version,
            "table_count": table_count,
            "connection_string": conn_str
        }
    except Exception as e:
        return False, f"Error de conexión: {str(e)}"

def configurar_conexion():
    """Permite al usuario configurar los parámetros de conexión"""
    console.print(Panel("[bold]Configuración de Conexión a SQL Server[/]"))
    
    server = input(f"Servidor (default: {os.getenv('SQL_SERVER', 'localhost,1433')}): ") or os.getenv('SQL_SERVER', 'localhost,1433')
    database = input(f"Base de datos (default: {os.getenv('SQL_DATABASE', 'AdventureWorks2019')}): ") or os.getenv('SQL_DATABASE', 'AdventureWorks2019')
    username = input(f"Usuario (default: {os.getenv('SQL_USERNAME', 'sa')}): ") or os.getenv('SQL_USERNAME', 'sa')
    password = input(f"Contraseña (default: ***): ") or os.getenv('SQL_PASSWORD', 'StrongPassword123!')
    
    # Guardar en archivo .env
    with open('.env', 'r') as f:
        env_lines = f.readlines()
    
    with open('.env', 'w') as f:
        for line in env_lines:
            if not any(line.startswith(prefix) for prefix in ['SQL_SERVER=', 'SQL_DATABASE=', 'SQL_USERNAME=', 'SQL_PASSWORD=']):
                f.write(line)
        
        f.write(f"SQL_SERVER={server}\n")
        f.write(f"SQL_DATABASE={database}\n")
        f.write(f"SQL_USERNAME={username}\n")
        f.write(f"SQL_PASSWORD={password}\n")
    
    console.print("[green]Configuración guardada en .env[/]")
    load_dotenv(override=True)
    
    return True

def menu_principal():
    """Menú principal"""
    console.clear()
    rprint("[bold cyan]============================================[/]")
    rprint("[bold cyan]  Configuración de Conexión a SQL Server  [/]")
    rprint("[bold cyan]============================================[/]")
    
    # Verificar drivers
    drivers_ok, drivers_info = verificar_drivers()
    if drivers_ok:
        console.print(Panel(", ".join(drivers_info), title="[green]Drivers ODBC[/]"))
    else:
        console.print(Panel(drivers_info, title="[red]Error de Drivers[/]"))
        return
    
    # Probar conexión actual
    conexion_ok, conexion_info = probar_conexion()
    if conexion_ok:
        console.print(Panel(
            f"[green]Conexión exitosa[/]\n"
            f"Versión: {conexion_info['version'][:50]}...\n"
            f"Tablas: {conexion_info['table_count']}", 
            title="[green]Estado de la Conexión[/]"
        ))
    else:
        console.print(Panel(conexion_info, title="[red]Error de Conexión[/]"))
        
        # Ofrecer configurar
        if input("\n¿Desea configurar la conexión? (s/n): ").lower() == 's':
            configurar_conexion()
            # Verificar nuevamente
            conexion_ok, conexion_info = probar_conexion()
            if conexion_ok:
                console.print(Panel("[green]¡Conexión establecida correctamente![/]"))
            else:
                console.print(Panel(conexion_info, title="[red]Error de Conexión[/]"))

if __name__ == "__main__":
    menu_principal() 