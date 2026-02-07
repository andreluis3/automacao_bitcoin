import customtkinter as ctk

class MainWindow(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Automação Bitcoin")
        self.geometry("1200x700")
        self.resizable(False, False)

        self._criar_layout()

    def _criar_layout(self):
        # Frame principal
        frame = ctk.CTkFrame(self)
        frame.pack(fill="both", expand=True, padx=20, pady=20)

        titulo = ctk.CTkLabel(
            frame,
            text="Automação de Trading Bitcoin",
            font=("Arial", 22, "bold")
        )
        titulo.pack(pady=20)

        status = ctk.CTkLabel(
            frame,
            text="Status: Aguardando mercado...",
            font=("Arial", 14)
        )
        status.pack(pady=10)
