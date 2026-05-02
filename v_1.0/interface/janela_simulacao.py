"""
janela_simulacao.py — Janela de configuração da simulação.

Melhorias v3:
  - Totalmente conectada ao bot_controller (on_save + on_start)
  - Pré-preenche campos com config atual do controller
  - Validação de campos com feedback visual
  - Campos agrupados por seção com scrollable frame
  - Callbacks tipados: on_save(data: dict), on_start()
"""
from __future__ import annotations

from typing import Any, Callable

import customtkinter as ctk

# ── Paleta (standalone, sem depender de theme.py) ─────────────────────────────
APP_BG   = "#0d1117"
CARD_BG  = "#161b22"
CARD_BG2 = "#1c2128"
BORDER   = "#30363d"
GREEN    = "#22c55e"
RED      = "#ef4444"
YELLOW   = "#f59e0b"
TEXT_PRI = "#e6edf3"
TEXT_SEC = "#8b949e"
ACCENT   = "#1f6feb"


def _parse_float(v: str, default: float = 0.0) -> float:
    try:
        return float(str(v).replace(",", "."))
    except (ValueError, TypeError):
        return default


class JanelaSimulacao(ctk.CTkToplevel):
    def __init__(
        self,
        parent,
        config: dict[str, Any] | None = None,
        on_save: Callable[[dict], None] | None = None,
        on_start: Callable[[], None] | None = None,
    ):
        super().__init__(parent)
        self.title("⚙ Configurações — Automação Bitcoin")
        self.geometry("520x640")
        self.resizable(False, True)
        self.configure(fg_color=APP_BG)
        self.transient(parent)
        self.after(100, self.grab_set)

        self._config   = config or {}
        self._on_save  = on_save
        self._on_start = on_start

        self._fields: dict[str, ctk.CTkEntry] = {}
        self._error_labels: dict[str, ctk.CTkLabel] = {}

        self._criar_layout()
        self._preencher_valores()

    # ══════════════════════════════════════════════════════════════════════════
    # LAYOUT
    # ══════════════════════════════════════════════════════════════════════════
    def _criar_layout(self) -> None:
        # Cabeçalho fixo
        header = ctk.CTkFrame(self, fg_color=CARD_BG, corner_radius=0)
        header.pack(fill="x", padx=0, pady=0)
        ctk.CTkLabel(
            header,
            text="Configurações da Simulação",
            font=("JetBrains Mono", 15, "bold"),
            text_color=TEXT_PRI,
        ).pack(anchor="w", padx=20, pady=(14, 10))

        # Área scrollável
        scroll = ctk.CTkScrollableFrame(self, fg_color=APP_BG, corner_radius=0)
        scroll.pack(fill="both", expand=True, padx=0, pady=0)

        # ── Seção: Saldo e Capital ─────────────────────────────────────────────
        self._secao(scroll, "💰 Saldo e Capital")
        self._campo(scroll, "capital_total",  "Saldo Inicial (R$)", "Ex: 300.00")
        self._campo(scroll, "max_buy_brl",    "Máx. Compra por Trade (R$)", "Ex: 30.00")
        self._campo(scroll, "max_sell_brl",   "Máx. Venda por Trade (R$)", "Ex: 30.00")

        # ── Seção: Risco ───────────────────────────────────────────────────────
        self._secao(scroll, "⚠ Risco e Stop")
        self._campo(scroll, "stop",           "Stop Loss (%)", "Ex: 1.2")
        self._campo(scroll, "take",           "Take Profit (%)", "Ex: 2.5")
        self._campo(scroll, "drawdown",       "Drawdown Máx. para Pausar (%)", "Ex: 12.0")
        self._campo(scroll, "risk_per_trade", "Risco por Trade (% do capital, ex: 0.02 = 2%)", "Ex: 0.02")

        # ── Seção: Estratégia ──────────────────────────────────────────────────
        self._secao(scroll, "📈 Estratégia")
        self._campo(scroll, "regime_threshold", "Sensibilidade Regime (padrão: 0.000003)", "Ex: 0.000003")
        self._campo(scroll, "binance_fee",      "Taxa Binance (padrão: 0.001 = 0.1%)", "Ex: 0.001")

        # Switches
        sw_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        sw_frame.pack(fill="x", padx=20, pady=(4, 8))

        self.sw_aggressive = ctk.CTkSwitch(
            sw_frame, text="Modo Agressivo (entra sem crossover)",
            font=("JetBrains Mono", 11), progress_color=ACCENT,
        )
        self.sw_aggressive.pack(anchor="w", pady=(0, 6))

        self.sw_lateral = ctk.CTkSwitch(
            sw_frame, text="Scalping Lateral (Bollinger Bands)",
            font=("JetBrains Mono", 11), progress_color=ACCENT,
        )
        self.sw_lateral.pack(anchor="w", pady=(0, 6))

        self.sw_acumular = ctk.CTkSwitch(
            sw_frame, text="Acumular Saldo (reservar % dos lucros)",
            font=("JetBrains Mono", 11), progress_color=ACCENT,
        )
        self.sw_acumular.pack(anchor="w")

        # Perfil
        self._secao(scroll, "👤 Perfil de Risco")
        ctk.CTkLabel(scroll, text="Perfil", text_color=TEXT_SEC,
                     font=("JetBrains Mono", 11)).pack(anchor="w", padx=20, pady=(0, 4))
        self.perfil_combo = ctk.CTkComboBox(
            scroll,
            values=["Conservador", "Agressivo"],
            state="readonly",
            fg_color=CARD_BG2,
            border_color=BORDER,
            font=("JetBrains Mono", 12),
        )
        self.perfil_combo.pack(fill="x", padx=20, pady=(0, 10))

        # Descrição do perfil
        self.perfil_desc = ctk.CTkLabel(
            scroll,
            text="",
            font=("JetBrains Mono", 10),
            text_color=TEXT_SEC,
            wraplength=460,
            justify="left",
        )
        self.perfil_desc.pack(anchor="w", padx=20, pady=(0, 10))
        self.perfil_combo.configure(command=self._on_perfil_change)

        # Separador
        ctk.CTkFrame(scroll, fg_color=BORDER, height=1).pack(fill="x", padx=20, pady=10)

        # ── Botões ─────────────────────────────────────────────────────────────
        btns = ctk.CTkFrame(scroll, fg_color="transparent")
        btns.pack(fill="x", padx=20, pady=(0, 16))

        ctk.CTkButton(
            btns, text="💾 Salvar Configuração", height=40,
            fg_color=CARD_BG2, hover_color=BORDER,
            font=("JetBrains Mono", 12, "bold"), text_color=TEXT_PRI,
            command=self._ao_salvar,
        ).pack(fill="x", pady=(0, 8))

        ctk.CTkButton(
            btns, text="▶  Salvar e Iniciar Simulação", height=44,
            fg_color="#166534", hover_color="#15803d",
            font=("JetBrains Mono", 13, "bold"),
            command=self._ao_salvar_e_iniciar,
        ).pack(fill="x", pady=(0, 8))

        ctk.CTkButton(
            btns, text="Cancelar", height=36,
            fg_color="#1c1c1c", hover_color="#2a2a2a",
            font=("JetBrains Mono", 11), text_color=TEXT_SEC,
            command=self.destroy,
        ).pack(fill="x")

    def _secao(self, parent, titulo: str) -> None:
        frame = ctk.CTkFrame(parent, fg_color=CARD_BG, corner_radius=8)
        frame.pack(fill="x", padx=14, pady=(8, 4))
        ctk.CTkLabel(frame, text=titulo, font=("JetBrains Mono", 11, "bold"),
                     text_color=ACCENT).pack(anchor="w", padx=12, pady=(8, 6))

    def _campo(self, parent, key: str, label: str, placeholder: str = "") -> None:
        ctk.CTkLabel(parent, text=label, text_color=TEXT_SEC,
                     font=("JetBrains Mono", 11)).pack(anchor="w", padx=20, pady=(4, 2))
        entry = ctk.CTkEntry(parent, placeholder_text=placeholder, height=36,
                              fg_color=CARD_BG2, border_color=BORDER,
                              font=("JetBrains Mono", 12), text_color=TEXT_PRI)
        entry.pack(fill="x", padx=20, pady=(0, 2))
        err_lbl = ctk.CTkLabel(parent, text="", text_color=RED,
                                font=("JetBrains Mono", 10))
        err_lbl.pack(anchor="w", padx=20, pady=(0, 2))
        self._fields[key]       = entry
        self._error_labels[key] = err_lbl

    # ══════════════════════════════════════════════════════════════════════════
    # PRÉ-PREENCHIMENTO com config atual
    # ══════════════════════════════════════════════════════════════════════════
    def _preencher_valores(self) -> None:
        mapa = {
            "capital_total":    ("capital_total", "saldo_inicial", 300.0),
            "max_buy_brl":      ("max_buy_brl",   None,            30.0),
            "max_sell_brl":     ("max_sell_brl",  None,            30.0),
            "stop":             ("stop",           None,            1.2),
            "take":             ("take",           None,            2.5),
            "drawdown":         ("drawdown",       None,            12.0),
            "risk_per_trade":   ("risk_per_trade", None,            0.02),
            "regime_threshold": ("regime_threshold", None,          0.000003),
            "binance_fee":      ("binance_fee",    None,            0.001),
        }
        for field_key, (cfg_key, fallback_key, default) in mapa.items():
            entry = self._fields.get(field_key)
            if entry is None:
                continue
            val = self._config.get(cfg_key)
            if val is None and fallback_key:
                val = self._config.get(fallback_key)
            if val is None:
                val = default
            entry.insert(0, str(val))

        # Switches
        if self._config.get("aggressive_mode", True):
            self.sw_aggressive.select()
        if self._config.get("lateral_scalping", True):
            self.sw_lateral.select()
        if self._config.get("acumular_saldo", False):
            self.sw_acumular.select()

        # Perfil
        perfil = str(self._config.get("perfil", "Conservador"))
        self.perfil_combo.set(perfil)
        self._on_perfil_change(perfil)

    def _on_perfil_change(self, perfil: str) -> None:
        descs = {
            "Conservador": (
                "Stop: 0.6% | Take: 1.2% | Drawdown máx: 12% | "
                "Risco conservador — menos operações, mais segurança."
            ),
            "Agressivo": (
                "Stop: 1.2% | Take: 2.5% | Drawdown máx: 12% | "
                "Maior exposição — mais operações, maior risco/retorno."
            ),
        }
        self.perfil_desc.configure(text=descs.get(perfil, ""))

    # ══════════════════════════════════════════════════════════════════════════
    # VALIDAÇÃO
    # ══════════════════════════════════════════════════════════════════════════
    def _validar(self) -> tuple[bool, dict[str, Any]]:
        erros = False
        data: dict[str, Any] = {}

        validacoes: list[tuple[str, str, float, float | None]] = [
            ("capital_total",    "Saldo Inicial",          1.0,   None),
            ("max_buy_brl",      "Máx. Compra",            0.01,  None),
            ("max_sell_brl",     "Máx. Venda",             0.01,  None),
            ("stop",             "Stop Loss",              0.01,  50.0),
            ("take",             "Take Profit",            0.01,  100.0),
            ("drawdown",         "Drawdown Máx",           0.5,   99.0),
            ("risk_per_trade",   "Risco por Trade",        0.001, 0.5),
            ("regime_threshold", "Sensibilidade Regime",   0.0,   None),
            ("binance_fee",      "Taxa Binance",           0.0,   0.1),
        ]

        for key, nome, minimo, maximo in validacoes:
            entry = self._fields.get(key)
            err   = self._error_labels.get(key)
            if entry is None:
                continue
            val = _parse_float(entry.get(), default=-999.0)
            if val == -999.0:
                if err: err.configure(text=f"⚠ {nome} inválido")
                entry.configure(border_color=RED)
                erros = True
            elif val < minimo:
                if err: err.configure(text=f"⚠ Mínimo: {minimo}")
                entry.configure(border_color=RED)
                erros = True
            elif maximo is not None and val > maximo:
                if err: err.configure(text=f"⚠ Máximo: {maximo}")
                entry.configure(border_color=RED)
                erros = True
            else:
                if err: err.configure(text="")
                entry.configure(border_color=BORDER)
                data[key] = val

        if not erros:
            data["saldo_inicial"]     = data.get("capital_total", 300.0)
            data["perfil"]            = self.perfil_combo.get()
            data["aggressive_mode"]   = self.sw_aggressive.get() == 1
            data["lateral_scalping"]  = self.sw_lateral.get() == 1
            data["acumular_saldo"]    = self.sw_acumular.get() == 1

        return (not erros), data

    # ══════════════════════════════════════════════════════════════════════════
    # CALLBACKS
    # ══════════════════════════════════════════════════════════════════════════
    def _ao_salvar(self) -> None:
        ok, data = self._validar()
        if not ok:
            return
        if self._on_save:
            self._on_save(data)
        self.destroy()

    def _ao_salvar_e_iniciar(self) -> None:
        ok, data = self._validar()
        if not ok:
            return
        if self._on_save:
            self._on_save(data)
        self.destroy()
        if self._on_start:
            self._on_start()