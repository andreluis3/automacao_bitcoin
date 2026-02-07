import customtkinter as ctk
from interface.main_window import MainWindow

def main():
    # Configuração visual global
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("dark-blue")

    # Criação da aplicação
    app = MainWindow()
    app.mainloop()

if __name__ == "__main__":
    main()
