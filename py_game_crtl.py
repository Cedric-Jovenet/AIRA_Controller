import asyncio
import pygame
import sys
import os
from bleak import BleakClient, BleakScanner

# Configuration du Robot
UART_RX_CHAR_UUID = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"
ROBOT_NAME = "AIRA Motor"

async def main():
    # 1. RECHERCHE DU ROBOT (Avant d'initialiser Pygame pour éviter l'erreur Windows)
    print(f"🔍 Recherche de '{ROBOT_NAME}'...")
    device = await BleakScanner.find_device_by_filter(
        lambda d, ad: ad.local_name == ROBOT_NAME, timeout=5.0
    )

    if not device:
        print("❌ Robot non trouvé. Assure-toi qu'il clignote (mode appairage).")
        return

    # 2. INITIALISATION DU CONTRÔLEUR
    pygame.init()
    pygame.joystick.init()
    
    if pygame.joystick.get_count() == 0:
        print("❌ Aucun contrôleur PS4 détecté en USB.")
        return
    
    controller = pygame.joystick.Joystick(0)
    controller.init()
    print(f"✅ Contrôleur détecté : {controller.get_name()}")

    # 3. CONNEXION ET AFFICHAGE DES INPUTS
    try:
        async with BleakClient(device) as client:
            print(f"🚀 Connecté à {ROBOT_NAME} ! Pilotez maintenant.")
            last_cmd = ""

            while True:
                pygame.event.pump() # Actualise les entrées du joystick
                
                # --- LECTURE DES INPUTS ---
                # Axes (Sticks)
                axis_v = controller.get_axis(1) # Stick Gauche Vertical
                axis_h = controller.get_axis(0) # Stick Gauche Horizontal
                
                # Boutons (Exemples sur PS4)
                btn_x = controller.get_button(0)
                btn_circle = controller.get_button(1)
                btn_square = controller.get_button(2)
                btn_triangle = controller.get_button(3)

                # --- AFFICHAGE DYNAMIQUE DANS LA CONSOLE ---
                # On utilise \r pour réécrire sur la même ligne
                status_text = (f"V: {axis_v:>5.2f} | H: {axis_h:>5.2f} | "
                               f"X: {btn_x} O: {btn_circle} []: {btn_square} Δ: {btn_triangle}")
                sys.stdout.write(f"\rInputs -> {status_text}")
                sys.stdout.flush()

                # --- LOGIQUE DE COMMANDE ---
                current_cmd = "q" # Stop par défaut
                
                if axis_v < -0.5: current_cmd = "w"   # Avancer
                elif axis_v > 0.5: current_cmd = "s"  # Reculer
                elif axis_h < -0.5: current_cmd = "l" # Gauche
                elif axis_h > 0.5: current_cmd = "r"  # Droite

                # Envoi seulement si la commande change
                if current_cmd != last_cmd:
                    await client.write_gatt_char(UART_RX_CHAR_UUID, current_cmd.encode())
                    last_cmd = current_cmd
                    # On affiche la commande envoyée sur une nouvelle ligne pour ne pas effacer le moniteur
                    print(f"\n[BLE] Commande envoyée : {current_cmd}")

                await asyncio.sleep(0.05) # 20 mises à jour par seconde

    except Exception as e:
        print(f"\n❌ Erreur de connexion : {e}")
    finally:
        pygame.quit()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nArrêt du programme.")