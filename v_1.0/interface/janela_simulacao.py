import customtkinter as ctk


class JanelaSimulacao(ctk.CTkToplevel):
    def __init__(self, parent, config: dict, on_save, on_start):
        super().__init__(parent)
        self.title("Configuração Simulação")
        self.geometry("540x620")
        self.minsize(520, 580)
        self.transient(parent)
        self.after(80, self.grab_set)

        self._on_save_callback = on_save
        self._on_start_callback = on_start
        self._config = config

        self._criar_layout()
        self._preencher_campos()

    def _criar_layout(self) -> None:
        container = ctk.CTkScrollableFrame(self)
        container.pack(fill="both", expand=True, padx=16, pady=16)

        ctk.CTkLabel(container, text="Configuração Inicial", font=("Arial", 18, "bold")).pack(anchor="w", pady=(0, 12))

        self.entry_saldo_inicial = self._add_field(container, "Saldo Inicial (R$)")
        self.entry_valor_trade = self._add_field(container, "Valor por trade (%)")
        self.entry_drawdown = self._add_field(container, "Drawdown Máximo (%)")

        ctk.CTkLabel(container, text="Perfil", font=("Arial", 16, "bold")).pack(anchor="w", pady=(14, 6))
        self.profile_combo = ctk.CTkComboBox(container, values=["Conservador", "Agressivo"], state="readonly")
        self.profile_combo.pack(fill="x", pady=(0, 12))

        buttons = ctk.CTkFrame(container, fg_color="transparent")
        buttons.pack(fill="x", pady=(10, 6))

        ctk.CTkButton(buttons, text="Salvar Configuração", command=self._salvar).pack(fill="x", pady=(0, 8))
        ctk.CTkButton(buttons, text="Iniciar Simulação", fg_color="#1f8f4e", hover_color="#16a34a", command=self._iniciar).pack(fill="x", pady=(0, 8))
        ctk.CTkButton(buttons, text="Cancelar", fg_color="#374151", hover_color="#4b5563", command=self.destroy).pack(fill="x")

    def _add_field(self, parent, label: str):
        ctk.CTkLabel(parent, text=label).pack(anchor="w", pady=(0, 4))
        e = ctk.CTkEntry(parent)
        e.pack(fill="x", pady=(0, 10))
        return e

    def _preencher_campos(self) -> None:
        self.entry_saldo_inicial.insert(0, str(self._config.get("saldo_inicial", 10000)))
        self.entry_valor_trade.insert(0, str(self._config.get("valor_trade", 5)))
        self.entry_drawdown.insert(0, str(self._config.get("drawdown", 12)))
        self.profile_combo.set(str(self._config.get("perfil", "Conservador")))

    def _to_float(self, value: str, field_name: str, min_value: float) -> float:
        raw = str(value).strip().replace(",", ".")
        if not raw:
            raise ValueError(f"{field_name} é obrigatório.")
        num = float(raw)
        if num < min_value:
            raise ValueError(f"{field_name} deve ser >= {min_value}.")
        return num

    def _collect(self) -> dict:
        saldo = self._to_float(self.entry_saldo_inicial.get(), "Saldo inicial", 1.0)
        valor_trade = self._to_float(self.entry_valor_trade.get(), "Valor por trade (%)", 0.1)
        drawdown = self._to_float(self.entry_drawdown.get(), "Drawdown máximo (%)", 0.5)
        return {
            "saldo_inicial": saldo,
            "valor_trade": min(100.0, valor_trade),
            "drawdown": drawdown,
            "perfil": self.profile_combo.get(),
        }

    def _salvar(self) -> None:
        try:
            data = self._collect()
            self._on_save_callback(data)
            self.destroy()
        except Exception as exc:
            self.title(f"Configuração Simulação | Erro: {exc}")

    def _iniciar(self) -> None:
        try:
            data = self._collect()
            self._on_save_callback(data)
            self._on_start_callback()
            self.destroy()
        except Exception as exc:
            self.title(f"Configuração Simulação | Erro: {exc}")
