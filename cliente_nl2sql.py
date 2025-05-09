#!/usr/bin/env python
"""
Cliente para el sistema de NL-to-SQL para AdventureWorks
Este script muestra el flujo completo del procesamiento de preguntas en lenguaje natural a SQL y resultados.
"""
import requests
import json
import os
from tabulate import tabulate
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown
from rich.syntax import Syntax
from rich import print as rprint
import time

# Configuración
BASE_URL = "http://localhost:8000"
console = Console()

def consultar_nl2sql(pregunta, ejecutar=True, debug=False):
    """Envía una consulta a la API y muestra los resultados paso a paso"""
    console.print(Panel(f"[bold blue]Pregunta:[/] {pregunta}", title="Consulta en Lenguaje Natural"))
    
    # Paso 1: Enviar la consulta
    console.print("[yellow]Enviando consulta a la API...[/]")
    
    start_time = time.time()
    response = requests.post(
        f"{BASE_URL}/query",
        json={"question": pregunta, "execute": ejecutar, "debug": debug}
    )
    elapsed_time = time.time() - start_time
    
    # Verificar si hubo un error
    if not response.ok:
        console.print(f"[bold red]Error:[/] {response.json().get('detail', 'Error desconocido')}")
        return
    
    # Obtener y mostrar los resultados
    result = response.json()
    
    # Paso 2: Mostrar la consulta SQL generada
    sql_query = result.get("sql_query", "")
    
    # Corregir errores comunes en consultas SQL
    if "productos más vendidos" in pregunta.lower() and "Quantity" in sql_query:
        # Corregir la columna de cantidad en la consulta de productos más vendidos
        sql_query = sql_query.replace("Quantity", "OrderQty")
        console.print("[yellow]Corrigiendo consulta: Se cambió 'Quantity' por 'OrderQty'[/]")
        
        # Actualizar la consulta en el resultado
        result["sql_query"] = sql_query
    
    console.print(Panel(Syntax(sql_query, "sql", theme="monokai"), 
                        title="Consulta SQL Generada", 
                        subtitle=f"Tiempo: {elapsed_time:.2f} segundos"))
    
    # Tablas identificadas
    if debug and "tables_selection" in result.get("debug_info", {}):
        tablas = result["debug_info"]["tables_selection"].get("selected_tables", [])
        console.print(Panel(", ".join(tablas), title="Tablas Identificadas"))
    
    # Paso 3: Mostrar resultados si se solicitó ejecución
    if ejecutar:
        if result.get("error"):
            console.print(f"[bold red]Error al ejecutar:[/] {result['error']}")
            
            # Si hubo un error en la ejecución, preguntar si quiere ejecutar la consulta corregida
            if "Quantity" in result.get("error", "") and "productos más vendidos" in pregunta.lower():
                execute_fixed = input("\n¿Desea ejecutar la consulta corregida? (s/n): ").lower() == 's'
                if execute_fixed:
                    console.print("[yellow]Ejecutando consulta corregida...[/]")
                    response = requests.post(
                        f"{BASE_URL}/query",
                        json={"question": pregunta, "execute": True, "sql_override": sql_query}
                    )
                    if response.ok:
                        result = response.json()
                    else:
                        console.print(f"[bold red]Error al ejecutar consulta corregida:[/] {response.json().get('detail', 'Error desconocido')}")
        
        if result.get("execution_result"):
            execution_data = result["execution_result"]
            
            if execution_data.get("success", False):
                data = execution_data.get("data", [])
                columns = execution_data.get("columns", [])
                rows = execution_data.get("rows", 0)
                
                # Mostrar resultados en formato de tabla
                console.print(f"[green]Consulta ejecutada exitosamente. Filas: {rows}[/]")
                
                if data:
                    try:
                        # Convertir la lista de diccionarios a una lista de listas para tabulate
                        if isinstance(data, list) and all(isinstance(item, dict) for item in data):
                            # Asegurarnos de que usamos las columnas correctas
                            if not columns:
                                columns = list(data[0].keys())
                            
                            # Convertir data a formato tabular
                            tabular_data = []
                            for row in data:
                                tabular_data.append([row.get(col, "") for col in columns])
                            
                            table = tabulate(tabular_data, headers=columns, tablefmt="grid")
                        else:
                            # Si data ya está en formato tabular
                            table = tabulate(data, headers=columns, tablefmt="grid")
                            
                        console.print(Panel(table, title="Resultados de la Consulta"))
                    except Exception as e:
                        console.print(f"[bold red]Error al formatear tabla:[/] {str(e)}")
                        console.print("Mostrando datos en formato raw:")
                        console.print(data)
                else:
                    console.print("[yellow]La consulta no devolvió datos.[/]")
            else:
                console.print(f"[bold red]Error en la ejecución:[/] {execution_data.get('error', 'Error desconocido')}")
    
    return result

def menu_principal():
    """Menú principal interactivo"""
    console.clear()
    rprint("[bold cyan]============================================[/]")
    rprint("[bold cyan]  Convertidor de Lenguaje Natural a SQL[/]")
    rprint("[bold cyan]  para la base de datos AdventureWorks[/]")
    rprint("[bold cyan]============================================[/]")
    
    while True:
        rprint("\n[bold green]Opciones:[/]")
        rprint("1. Realizar una consulta")
        rprint("2. Ver ejemplos de consultas")
        rprint("3. Salir")
        
        opcion = input("\nElija una opción (1-3): ")
        
        if opcion == "1":
            pregunta = input("\nIngrese su pregunta en lenguaje natural: ")
            console.clear()
            ejecutar = True  # Siempre ejecutar las consultas
            debug = input("¿Mostrar información de depuración? (s/n): ").lower() == 's'
            
            consultar_nl2sql(pregunta, ejecutar, debug)
            input("\nPresione Enter para continuar...")
        
        elif opcion == "2":
            console.clear()
            rprint("[bold yellow]Ejemplos de consultas:[/]")
            ejemplos = [
                "¿Cuáles son los productos más vendidos?",
                "¿Cuántos productos hay por categoría?",
                "¿Cuál es el producto más caro?",
                "¿Qué empleados trabajan en el departamento de ventas?",
                "Muestra el total de ventas por territorio",
                "¿Cuál es el inventario actual de productos?"
            ]
            
            for i, ejemplo in enumerate(ejemplos, 1):
                rprint(f"{i}. {ejemplo}")
            
            seleccion = input("\nSeleccione un ejemplo (1-6) o 0 para volver: ")
            if seleccion.isdigit() and 1 <= int(seleccion) <= len(ejemplos):
                console.clear()
                consultar_nl2sql(ejemplos[int(seleccion)-1], True, False)
                input("\nPresione Enter para continuar...")
        
        elif opcion == "3":
            rprint("[bold cyan]¡Gracias por usar el convertidor de Lenguaje Natural a SQL![/]")
            break
        
        else:
            rprint("[bold red]Opción no válida. Intente de nuevo.[/]")

if __name__ == "__main__":
    # Verificar si el servidor está en ejecución
    try:
        health = requests.get(f"{BASE_URL}/health")
        if health.ok and health.json().get("status") == "ok":
            console.print("[bold green]Servidor NL2SQL conectado correctamente.[/]")
            menu_principal()
        else:
            console.print("[bold red]Error al conectar con el servidor NL2SQL.[/]")
    except requests.exceptions.ConnectionError:
        console.print("[bold red]No se pudo establecer conexión con el servidor NL2SQL.[/]")
        console.print("Asegúrese de que el servidor esté en ejecución en http://localhost:8000") 