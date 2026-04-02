import pygame
import sys
import time

def test_controller():
    # Initialisation de Pygame
    pygame.init()
    pygame.joystick.init()

    # Vérification de la présence d'une manette
    count = pygame.joystick.get_count()
    if count == 0:
        print("❌ AUCUNE MANETTE DÉTECTÉE !")
        print("1. Vérifie ton câble USB (essaie un autre port).")
        print("2. Vérifie que Windows reconnaît la 'Wireless Controller' dans le Panneau de Configuration.")
        return

    # Initialisation de la première manette trouvée
    joystick = pygame.joystick.Joystick(0)
    joystick.init()

    print(f"✅ Manette détectée : {joystick.get_name()}")
    print("Appuie sur 'Ctrl+C' pour quitter.")
    print("-" * 50)

    try:
        while True:
            # Récupère les événements (obligatoire pour mettre à jour les valeurs)
            pygame.event.pump()

            # Lecture des Sticks (Axes 0 et 1 pour le stick gauche)
            axis_0 = joystick.get_axis(0) # Horizontal
            axis_1 = joystick.get_axis(1) # Vertical
            
            # Lecture des Boutons principaux (0, 1, 2, 3)
            buttons = []
            for i in range(joystick.get_numbuttons()):
                if joystick.get_button(i):
                    buttons.append(i)

            # Affichage en temps réel
            # \r permet d'effacer la ligne précédente
            output = f"Stick L -> H: {axis_0:>6.2f} | V: {axis_1:>6.2f} | Boutons pressés: {buttons}"
            sys.stdout.write(f"\r{output}")
            sys.stdout.flush()

            time.sleep(0.05) # 20Hz pour ne pas surcharger la console

    except KeyboardInterrupt:
        print("\n\nFin du test.")
    finally:
        pygame.quit()

if __name__ == "__main__":
    test_controller()