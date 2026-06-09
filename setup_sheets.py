"""
Ejecuta esto UNA VEZ para crear las hojas y cabeceras en Google Sheets.
    python setup_sheets.py
"""
from services.sheets_service import init_sheet

if __name__ == "__main__":
    print("Inicializando Google Sheets...")
    init_sheet()
    print("✅ Hojas creadas correctamente.")
    print("   - 'Apuestas': donde se registran todas las apuestas")
    print("   - 'Resumen':  estadísticas con fórmulas automáticas")
