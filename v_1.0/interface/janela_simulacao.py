import customtkinter as ctk


class JanelaSimulacao(ctk.CTkToplevel):
    def __init__(self, master):
        super().__init__(master)
        self.title("JanelaSimulacao")
        self.geometry("560x760")
        self.minsize(520, 700)
        self.configure(fg_color="#1e1f22")
        self.transient(master)
        self.grab_set()

        self._criar_layout()

    def _criar_layout(self) -> None:
        container = ctk.CTkScrollableFrame(self, fg_color="#1e1f22")
        container.pack(fill="both", expand=True, padx=16, pady=16)

        ctk.CTkLabel(
            container,
            text="Configuração Inicial",
            font=("Arial", 18, "bold"),
        ).pack(anchor="w", pady=(0, 12))

        self.entry_saldo_inicial_brl = self._adicionar_campo(container, "Saldo Inicial (R$)")
        self.entry_saldo_inicial_btc = self._adicionar_campo(container, "Saldo Inicial BTC")
        self.entry_taxa_operacao = self._adicionar_campo(container, "Taxa por operação (%)")
        self.entry_valor_trade = self._adicionar_campo(container, "Valor por trade (% do saldo)")
        self.entry_stop_loss = self._adicionar_campo(container, "Stop Loss (%)")
        self.entry_take_profit = self._adicionar_campo(container, "Take Profit (%)")
        self.entry_slippage = self._adicionar_campo(container, "Slippage (% opcional)")

        estrategia_frame = ctk.CTkFrame(container, fg_color="#2a2d31", corner_radius=12)
        estrategia_frame.pack(fill="x", pady=(14, 10))
        ctk.CTkLabel(
            estrategia_frame,
            text="Estratégia",
            font=("Arial", 18, "bold"),
        ).pack(anchor="w", padx=14, pady=(12, 6))
        ctk.CTkLabel(
            estrategia_frame,
            text="Estratégia Atual",
            font=("Arial", 14, "bold"),
            text_color="#d4d4d8",
        ).pack(anchor="w", padx=14)
        ctk.CTkLabel(
            estrategia_frame,
            text="Cruzamento SMA Rápida x SMA Lenta",
            font=("Arial", 14),
            text_color="#e4e4e7",
        ).pack(anchor="w", padx=14, pady=(4, 12))

        ctk.CTkLabel(
            container,
            text="Controle de Risco",
            font=("Arial", 18, "bold"),
        ).pack(anchor="w", pady=(16, 12))

        self.entry_max_trades = self._adicionar_campo(container, "Máximo de trades simultâneos")
        self.entry_max_drawdown = self._adicionar_campo(container, "Máximo de drawdown permitido (%)")

        botoes_frame = ctk.CTkFrame(container, fg_color="transparent")
        botoes_frame.pack(fill="x", pady=(18, 6))

        ctk.CTkButton(
            botoes_frame,
            text="Salvar Configuração",
            height=38,
            fg_color="#334155",
            hover_color="#475569",
            command=self._ao_salvar,
        ).pack(fill="x", pady=(0, 10))

        ctk.CTkButton(
            botoes_frame,
            text="Iniciar Simulação",
            height=40,
            fg_color="#1f8f4e",
            hover_color="#16a34a",
            command=self._ao_iniciar,
        ).pack(fill="x", pady=(0, 10))

        ctk.CTkButton(
            botoes_frame,
            text="Cancelar",
            height=38,
            fg_color="#374151",
            hover_color="#4b5563",
            command=self.destroy,
        ).pack(fill="x")

    def _adicionar_campo(self, parent, label: str) -> ctk.CTkEntry:
        ctk.CTkLabel(parent, text=label, font=("Arial", 14)).pack(anchor="w", pady=(0, 4))
        entry = ctk.CTkEntry(parent, height=36)
        entry.pack(fill="x", pady=(0, 10))
        return entry

    def _ao_salvar(self) -> None:
        # Interface apenas: sem lógica de persistência por enquanto.
        pass

    def _ao_iniciar(self) -> None:
        # Interface apenas: sem lógica de execução por enquanto.
        pass
