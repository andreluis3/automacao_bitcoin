import customtkinter as ctk


class TabSaldo(ctk.CTkFrame):
    def __init__(self, master, *args, **kwargs):
        super().__init__(master, *args, **kwargs)

        self.frame_principal = ctk.CTkFrame(self, fg_color="#2a2d31", corner_radius=12)
        self.frame_principal.pack(fill="both", expand=True, padx=12, pady=12)

        self.saldo_btc_label = ctk.CTkLabel(
            self.frame_principal,
            text="Saldo em BTC: 0.00000000",
            font=("Arial", 16),
        )
        self.saldo_btc_label.pack(anchor="w", padx=16, pady=(16, 8))

        self.taxas_label = ctk.CTkLabel(
            self.frame_principal,
            text="Taxas: 0.00",
            font=("Arial", 16),
        )
        self.taxas_label.pack(anchor="w", padx=16, pady=8)
