import asyncio
import pygame
import sys
import threading
from bleak import BleakClient, BleakScanner

# Configuration
UART_RX_CHAR_UUID = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"
ROBOT_NAME = "AIRA Motor"

# Variable partagée pour communiquer entre la manette et le Bluetooth
shared_data = {"cmd": "q", "running": True}

async def bluetooth_worker():
    """Gère la connexion et la reconnexion automatique"""
    while shared_data["running"]:
        print(f"🔍 Recherche de '{ROBOT_NAME}'...")
        device = await BleakScanner.find_device_by_filter(
            lambda d, ad: ad.local_name == ROBOT_NAME, timeout=5.0
        )

        if not device:
            print("❌ Robot non trouvé, nouvelle tentative...")
            await asyncio.sleep(1)
            continue

        try:
            async with BleakClient(device) as client:
                print(f"✅ CONNECTÉ !")
                last_sent = ""
                while client.is_connected and shared_data["running"]:
                    current_cmd = shared_data["cmd"]
                    if current_cmd != last_sent:
                        await client.write_gatt_char(UART_RX_CHAR_UUID, current_cmd.encode())
                        last_sent = current_cmd
                    await asyncio.sleep(0.05)
        except Exception as e:
            print(f"\n⚠️ Connexion perdue : {e}")
            # On ne coupe pas shared_data["running"] ici pour permettre de retenter

def start_ble_loop():
    """Lance la boucle asyncio dans un thread séparé"""
    asyncio.run(bluetooth_worker())

def main():
    # 1. INITIALISATION MANETTE
    pygame.init()
    pygame.joystick.init()
    
    if pygame.joystick.get_count() == 0:
        print("❌ Aucune manette détecté.")
        return
    
    controller = pygame.joystick.Joystick(0)
    controller.init()
    print(f"🎮 Manette : {controller.get_name()}")

    # 2. LANCEMENT DU THREAD BLUETOOTH
    ble_thread = threading.Thread(target=start_ble_loop, daemon=True)
    ble_thread.start()

    # 3. BOUCLE PYGAME (THREAD PRINCIPAL)
    try:
        print("--- Affichage des inputs activé ---")
        while shared_data["running"]:
            pygame.event.pump()
            
            v = controller.get_axis(1)
            h = controller.get_axis(0)
            
            # Détermination de la commande
            cmd = "a"
            if v < -0.5: cmd = "z"
            elif v > 0.5: cmd = "s"
            elif h < -0.5: cmd = "q"
            elif h > 0.5: cmd = "d"
            
            shared_data["cmd"] = cmd

            # Affichage console
            sys.stdout.write(f"\rV: {v:>5.2f} | H: {h:>5.2f} | Envoi: {cmd}  ")
            sys.stdout.flush()
            
            pygame.time.wait(50) # On attend 50ms

    except KeyboardInterrupt:
        print("\nArrêt...")
    finally:
        shared_data["running"] = False
        pygame.quit()

if __name__ == "__main__":
    main()