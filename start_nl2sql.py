#!/usr/bin/env python
"""
Script principal para iniciar el sistema completo de NL2SQL para AdventureWorks
"""
import os
import sys
import time
import subprocess
import signal
import threading
from rich.console import Console
from rich import print as rprint
from rich.panel import Panel
import requests

console = Console()

# Rutas y configuración
SERVER_PROCESS = None
SERVER_PORT = 8000
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def iniciar_servidor():
    """Inicia el servidor de NL2SQL en un proceso separado"""
    global SERVER_PROCESS
    os.chdir(BASE_DIR)
    
    console.print("[yellow]Iniciando servidor NL2SQL...[/]")
    
    # Iniciar el servidor
    try:
        SERVER_PROCESS = subprocess.Popen(
            [sys.executable, "ejemplo_app_rag.py"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        
        # Esperar a que el servidor esté listo
        for i in range(30):
            try:
                response = requests.get(f"http://localhost:{SERVER_PORT}/health")
                if response.status_code == 200:
                    console.print("[green]Servidor NL2SQL iniciado correctamente[/]")
                    return True
            except requests.exceptions.ConnectionError:
                pass
            
            time.sleep(1)
            console.print(f"[yellow]Esperando a que el servidor esté listo... ({i+1}/30)[/]")
        
        console.print("[red]Error: No se pudo iniciar el servidor NL2SQL[/]")
        return False
    except Exception as e:
        console.print(f"[red]Error al iniciar el servidor: {str(e)}[/]")
        return False

def detener_servidor():
    """Detiene el servidor NL2SQL"""
    global SERVER_PROCESS
    if SERVER_PROCESS is not None:
        console.print("[yellow]Deteniendo servidor NL2SQL...[/]")
        
        # Enviar señal para terminar el proceso
        SERVER_PROCESS.terminate()
        try:
            SERVER_PROCESS.wait(timeout=5)
            console.print("[green]Servidor NL2SQL detenido correctamente[/]")
        except subprocess.TimeoutExpired:
            console.print("[red]Forzando cierre del servidor...[/]")
            SERVER_PROCESS.kill()
        
        SERVER_PROCESS = None

def iniciar_cliente():
    """Inicia el cliente de NL2SQL"""
    os.chdir(BASE_DIR)
    console.print("[yellow]Iniciando cliente NL2SQL...[/]")
    
    # Ejecutar el cliente
    try:
        subprocess.run([sys.executable, "cliente_nl2sql.py"])
    except KeyboardInterrupt:
        console.print("[yellow]Cliente NL2SQL interrumpido por el usuario[/]")
    except Exception as e:
        console.print(f"[red]Error al ejecutar el cliente: {str(e)}[/]")

def verificar_instalacion():
    """Verifica si todos los componentes necesarios están instalados"""
    console.print("[yellow]Verificando instalación...[/]")
    
    # Verificar archivos críticos
    archivos_requeridos = [
        "ejemplo_app_rag.py",
        "cliente_nl2sql.py",
        "setup_db.py",
        ".env"
    ]
    
    todos_presentes = True
    for archivo in archivos_requeridos:
        if not os.path.exists(os.path.join(BASE_DIR, archivo)):
            console.print(f"[red]Error: Archivo requerido no encontrado: {archivo}[/]")
            todos_presentes = False
    
    if not todos_presentes:
        return False
    
    # Verificar dependencias de Python
    try:
        import pyodbc
        import openai
        import fastapi
        import rich
        import tabulate
        import requests
    except ImportError as e:
        console.print(f"[red]Error: Falta dependencia de Python: {str(e)}[/]")
        return False
    
    console.print("[green]Verificación de instalación completada con éxito[/]")
    return True

def configurar_bd():
    """Ejecuta el script de configuración de la base de datos"""
    os.chdir(BASE_DIR)
    console.print("[yellow]Ejecutando configuración de la base de datos...[/]")
    
    try:
        subprocess.run([sys.executable, "setup_db.py"])
    except Exception as e:
        console.print(f"[red]Error al configurar la base de datos: {str(e)}[/]")

def menu_principal():
    """Menú principal del sistema"""
    console.clear()
    rprint("[bold cyan]============================================[/]")
    rprint("[bold cyan]    Sistema NL2SQL para AdventureWorks    [/]")
    rprint("[bold cyan]============================================[/]")
    
    while True:
        rprint("\n[bold green]Opciones:[/]")
        rprint("1. Iniciar sistema completo")
        rprint("2. Configurar conexión a la base de datos")
        rprint("3. Verificar instalación")
        rprint("4. Salir")
        
        opcion = input("\nElija una opción (1-4): ")
        
        if opcion == "1":
            console.clear()
            if verificar_instalacion():
                # Iniciar servidor en segundo plano
                if iniciar_servidor():
                    # Iniciar cliente
                    iniciar_cliente()
                    # Detener servidor al salir
                    detener_servidor()
            
            input("\nPresione Enter para continuar...")
        
        elif opcion == "2":
            console.clear()
            configurar_bd()
            input("\nPresione Enter para continuar...")
        
        elif opcion == "3":
            console.clear()
            verificar_instalacion()
            input("\nPresione Enter para continuar...")
        
        elif opcion == "4":
            rprint("[bold cyan]¡Gracias por usar el sistema NL2SQL para AdventureWorks![/]")
            # Asegurarse de que el servidor esté detenido
            detener_servidor()
            break
        
        else:
            rprint("[bold red]Opción no válida. Intente de nuevo.[/]")

def detener_por_señal(sig, frame):
    """Manejador de señales para detener graciosamente"""
    print("\nDeteniendo servicios...")
    detener_servidor()
    sys.exit(0)

if __name__ == "__main__":
    # Configurar manejo de señales
    signal.signal(signal.SIGINT, detener_por_señal)
    
    # Ejecutar menú principal
    menu_principal() 