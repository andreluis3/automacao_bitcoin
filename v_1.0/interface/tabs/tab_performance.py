import customtkinter as ctk


class TabPerformance(ctk.CTkFrame):
    def __init__(self, master, *args, **kwargs):
        super().__init__(master, *args, **kwargs)

        self.frame_principal = ctk.CTkFrame(self, fg_color="#2a2d31", corner_radius=12)
        self.frame_principal.pack(fill="both", expand=True, padx=12, pady=12)

        self.titulo = ctk.CTkLabel(
            self.frame_principal,
            text="Performance",
            font=("Arial", 22, "bold"),
        )
        self.titulo.pack(anchor="w", padx=16, pady=(14, 10))

        self.placeholder_grafico = ctk.CTkFrame(
            self.frame_principal,
            fg_color="#1e1f22",
            corner_radius=10,
            border_width=1,
            border_color="#3a3f44",
        )
        self.placeholder_grafico.pack(fill="both", expand=True, padx=16, pady=(0, 16))
