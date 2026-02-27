from __future__ import annotations

import logging
from tkinter import messagebox
from typing import Callable

import customtkinter as ctk
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from interface.theme import (
    ACCENT,
    APP_BG,
    CARD_BG,
    CARD_BORDER,
    FONT_LABEL,
    FONT_SECTION,
    FONT_SMALL,
    FONT_TITLE,
    FONT_VALUE,
    GREEN,
    RED,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
)



class TradingTab(ctk.CTkFrame):
    def __init__(self, master, market_data, trade_manager, on_trade_update: Callable[[], None] | None = None):
        super().__init__(master, fg_color=APP_BG)
        self.logger = logging.getLogger(__name__)
        self.market_data = market_data
        self.on_trade_update = on_trade_update

        self.bot_running = False
        self.preco_anterior: float | None = None
        self.modo_operacao = "desligado"
        self.total_trades = 0

        self.simulation_engine = SimulationEngine(trade_manager=trade_manager)
        self.strategy_sma = StrategySMA()

        self._ultimo_preco_brl: float = 0.0
        self._preco_color_atual = TEXT_PRIMARY
        self._preco_anim_after_id: str | None = None
        self._pulse_after_id: str | None = None
        self._peak_balance_brl: float = 0.0

        self.max_candles = 180
        self.prices: list[float] = []

        self._criar_layout()
        self._criar_grafico()
        self._atualizar_status_footer()
        self._atualizar_grafico()

    def _criar_layout(self) -> None:
        header = ctk.CTkFrame(self, fg_color=CARD_BG, corner_radius=16, border_width=1, border_color=CARD_BORDER)
        header.pack(fill="x", padx=18, pady=(14, 10))
        header.grid_columnconfigure(0, weight=1)
        header.grid_columnconfigure(1, weight=0)

        left_header = ctk.CTkFrame(header, fg_color="transparent")
        left_header.grid(row=0, column=0, sticky="w", padx=18, pady=14)

        self.preco_label = ctk.CTkLabel(left_header, text="BTC/USDT: --", font=FONT_TITLE, text_color=TEXT_PRIMARY)
        self.preco_label.pack(anchor="w")

        signals_frame = ctk.CTkFrame(left_header, fg_color="transparent")
        signals_frame.pack(anchor="w", pady=(8, 0))

        self.buy_indicator = ctk.CTkLabel(signals_frame, text="●", font=("Segoe UI", 16, "bold"), text_color=CARD_BORDER)
        self.buy_indicator.pack(side="left")
        ctk.CTkLabel(signals_frame, text="Compra", font=FONT_SMALL, text_color=TEXT_SECONDARY).pack(
            side="left", padx=(6, 16)
        )

        self.sell_indicator = ctk.CTkLabel(
            signals_frame, text="●", font=("Segoe UI", 16, "bold"), text_color=CARD_BORDER
        )
        self.sell_indicator.pack(side="left")
        ctk.CTkLabel(signals_frame, text="Venda", font=FONT_SMALL, text_color=TEXT_SECONDARY).pack(
            side="left", padx=(6, 16)
        )

        self.drawdown_label = ctk.CTkLabel(
            signals_frame,
            text="Drawdown: 0.00%",
            font=FONT_VALUE,
            text_color=GREEN,
        )
        self.drawdown_label.pack(side="left")

        right_header = ctk.CTkFrame(header, fg_color="transparent")
        right_header.grid(row=0, column=1, sticky="e", padx=20, pady=14)

        self.saldo_label = ctk.CTkLabel(right_header, text="Saldo: --", font=FONT_LABEL, text_color=TEXT_PRIMARY)
        self.saldo_label.pack(anchor="e")

        self.lucro_label = ctk.CTkLabel(right_header, text="Lucro Hoje: R$0,00", font=FONT_VALUE, text_color=TEXT_PRIMARY)
        self.lucro_label.pack(anchor="e", pady=(6, 0))

        body = ctk.CTkFrame(self, fg_color=APP_BG)
        body.pack(fill="both", expand=True, padx=18, pady=(0, 10))
        body.grid_columnconfigure(0, weight=3)
        body.grid_columnconfigure(1, weight=1)
        body.grid_rowconfigure(0, weight=1)

        self.chart_frame = ctk.CTkFrame(body, fg_color=CARD_BG, corner_radius=16, border_width=1, border_color=CARD_BORDER)
        self.chart_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 12))

        self.side_panel = ctk.CTkFrame(body, fg_color=CARD_BG, corner_radius=16, border_width=1, border_color=CARD_BORDER)
        self.side_panel.grid(row=0, column=1, sticky="nsew")

        ctk.CTkLabel(
            self.side_panel,
            text="CONFIGURACAO DA ESTRATEGIA",
            font=FONT_SECTION,
            text_color=TEXT_PRIMARY,
        ).pack(pady=(18, 12))

        self.real_mode_switch = ctk.CTkSwitch(
            self.side_panel,
            text="Modo Real (ON/OFF)",
            font=FONT_LABEL,
            progress_color=ACCENT,
            command=self._alternar_modo_real,
        )
        self.real_mode_switch.pack(pady=(4, 8))

        self.simulacao_mode_switch = ctk.CTkSwitch(
            self.side_panel,
            text="Modo Simulacao (ON/OFF)",
            font=FONT_LABEL,
            progress_color=ACCENT,
            command=self._alternar_modo_simulacao,
        )
        self.simulacao_mode_switch.pack(pady=(0, 14))

        self.simulacao_button = ctk.CTkButton(
            self.side_panel,
            text="Configurar Simulacao",
            height=40,
            font=FONT_LABEL,
            fg_color="#334155",
            hover_color="#475569",
            command=self._abrir_modal_simulacao,
        )
        self.simulacao_button.pack(pady=(0, 12), padx=20, fill="x")

        self.bot_button = ctk.CTkButton(
            self.side_panel,
            text="INICIAR BOT",
            height=42,
            font=FONT_VALUE,
            fg_color=GREEN,
            hover_color="#16A34A",
            command=self._toggle_execucao,
        )
        self.bot_button.pack(pady=8, padx=20, fill="x")

        trades_container = ctk.CTkFrame(
            self.side_panel,
            fg_color=APP_BG,
            corner_radius=12,
            border_width=1,
            border_color=CARD_BORDER,
        )
        trades_container.pack(pady=20, padx=20, fill="x")

        ctk.CTkLabel(
            trades_container,
            text="QUANTIDADE DE TRADES",
            text_color=TEXT_SECONDARY,
            font=FONT_SMALL,
        ).pack(pady=(12, 4))

        self.trades_label = ctk.CTkLabel(trades_container, text="0", text_color=TEXT_PRIMARY, font=("Segoe UI", 28, "bold"))
        self.trades_label.pack(pady=(0, 12))

        footer = ctk.CTkFrame(self, fg_color=CARD_BG, corner_radius=12, border_width=1, border_color=CARD_BORDER)
        footer.pack(fill="x", padx=18, pady=(0, 14))
        self.status_label = ctk.CTkLabel(footer, text="PARADO: DESLIGADO", font=FONT_LABEL, text_color=TEXT_PRIMARY)
        self.status_label.pack(padx=14, pady=10, anchor="w")

    def _criar_grafico(self) -> None: # Graficos 
        self.fig, self.ax = plt.subplots(figsize=(8, 5))
        self.fig.patch.set_facecolor(CARD_BG)
        self.ax.set_facecolor(APP_BG)

        self.price_line, = self.ax.plot([], [], color=TEXT_PRIMARY, linewidth=2.0, alpha=0.95)
        self.ma_fast_line, = self.ax.plot([], [], color=GREEN, linewidth=1.5, alpha=0.9)
        self.ma_slow_line, = self.ax.plot([], [], color=RED, linewidth=1.5, alpha=0.9)
        self.ax.tick_params(colors=TEXT_SECONDARY)
        self.ax.grid(color=CARD_BORDER, alpha=0.45)

        self.canvas = FigureCanvasTkAgg(self.fig, master=self.chart_frame)
        self.canvas.get_tk_widget().pack(fill="both", expand=True, padx=10, pady=10)

    def _atualizar_grafico(self) -> None:
        try:
            preco_btc_usdt = self.market_data.pegar_preco_atual("BTCUSDT")
            preco_btc_brl = self._pegar_preco_btc_brl(preco_btc_usdt)
            self._ultimo_preco_brl = preco_btc_brl
            dados_estrategia = self.strategy_sma.update_dados(preco_btc_brl)

            self._atualizar_preco_animado(preco_btc_usdt)

            self.prices.append(preco_btc_usdt)
            if len(self.prices) > self.max_candles:
                self.prices = self.prices[-self.max_candles:]

            x = np.arange(len(self.prices))
            y = np.array(self.prices)

            self.price_line.set_data(x, y)

            if len(y) >= 7:
                ma_fast = np.convolve(y, np.ones(7) / 7, mode="valid")
                self.ma_fast_line.set_data(x[-len(ma_fast) :], ma_fast)
            else:
                self.ma_fast_line.set_data([], [])

            if len(y) >= 40:
                ma_slow = np.convolve(y, np.ones(40) / 40, mode="valid")
                self.ma_slow_line.set_data(x[-len(ma_slow) :], ma_slow)
            else:
                self.ma_slow_line.set_data([], [])

            if self.bot_running:
                if self.modo_operacao == "simulacao":
                    self.executar_estrategia_simulada(dados_estrategia)
                elif self.modo_operacao == "real":
                    self.executar_estrategia(preco_btc_usdt)

            if self.modo_operacao == "simulacao":
                self._atualizar_painel_simulacao(preco_btc_brl)
            elif self.modo_operacao == "real":
                self._atualizar_painel_real(preco_btc_brl)
                self.drawdown_label.configure(text="Drawdown: --", text_color=TEXT_SECONDARY)
            else:
                self.saldo_label.configure(text="Saldo: --")
                self.drawdown_label.configure(text="Drawdown: --", text_color=TEXT_SECONDARY)

            if len(self.prices) > 2:
                self.ax.set_xlim(max(0, len(self.prices) - self.max_candles), len(self.prices))
            self.ax.relim()
            self.ax.autoscale_view()
            self.canvas.draw_idle()

        except Exception as erro:
            self.logger.exception("Erro ao atualizar grafico: %s", erro)

        self.after(1000, self._atualizar_grafico)

    def _pegar_preco_btc_brl(self, preco_btc_usdt: float) -> float:
        try:
            return self.market_data.pegar_preco_atual("BTCBRL")
        except Exception:
            try:
                usdt_brl = self.market_data.pegar_preco_atual("USDTBRL")
                return preco_btc_usdt * usdt_brl
            except Exception:
                return preco_btc_usdt

    def _atualizar_preco_animado(self, preco_atual: float) -> None:
        texto_preco, cor_preco = self._montar_texto_preco_com_variacao(preco_atual)
        self.preco_label.configure(text=texto_preco)
        self._animar_cor_label(self.preco_label, self._preco_color_atual, cor_preco, 8, 28)
        self._preco_color_atual = cor_preco

    def _montar_texto_preco_com_variacao(self, preco_atual: float) -> tuple[str, str]:
        if self.preco_anterior is None or self.preco_anterior == 0:
            self.preco_anterior = preco_atual
            return f"BTC/USDT: ${preco_atual:,.2f}", TEXT_PRIMARY

        variacao_percentual = ((preco_atual - self.preco_anterior) / self.preco_anterior) * 100
        if variacao_percentual > 0:
            cor, sinal = GREEN, "+"
        elif variacao_percentual < 0:
            cor, sinal = RED, ""
        else:
            cor, sinal = TEXT_PRIMARY, ""

        texto = f"BTC/USDT: ${preco_atual:,.2f} ({sinal}{variacao_percentual:.2f}%)"
        self.preco_anterior = preco_atual
        return texto, cor

    def _animar_cor_label(
        self,
        label: ctk.CTkLabel,
        cor_inicio: str,
        cor_fim: str,
        passos: int,
        intervalo_ms: int,
    ) -> None:
        if self._preco_anim_after_id:
            self.after_cancel(self._preco_anim_after_id)
            self._preco_anim_after_id = None

        inicio_rgb = self._hex_to_rgb(cor_inicio)
        fim_rgb = self._hex_to_rgb(cor_fim)

        def _passo(i: int) -> None:
            proporcao = i / max(1, passos)
            atual = (
                int(inicio_rgb[0] + (fim_rgb[0] - inicio_rgb[0]) * proporcao),
                int(inicio_rgb[1] + (fim_rgb[1] - inicio_rgb[1]) * proporcao),
                int(inicio_rgb[2] + (fim_rgb[2] - inicio_rgb[2]) * proporcao),
            )
            label.configure(text_color=self._rgb_to_hex(atual))
            if i < passos:
                self._preco_anim_after_id = self.after(intervalo_ms, lambda: _passo(i + 1))

        _passo(0)

    def _toggle_execucao(self) -> None:
        if not self.bot_running:
            if self.modo_operacao == "desligado":
                messagebox.showwarning("Modo", "Ligue o modo real ou o modo simulacao antes de iniciar.")
                return
            if self.modo_operacao == "simulacao" and self.simulation_engine.initial_balance_brl <= 0:
                messagebox.showwarning("Simulacao", "Configure o modo simulacao antes de iniciar o bot.")
                return

            self.bot_running = True
            self.bot_button.configure(text="PARAR BOT", fg_color=RED, hover_color="#DC2626")
        else:
            if self.modo_operacao == "simulacao" and self._ultimo_preco_brl > 0:
                self.simulation_engine.finalizar_simulacao(self._ultimo_preco_brl)
            self.bot_running = False
            self.bot_button.configure(text="INICIAR BOT", fg_color=GREEN, hover_color="#16A34A")

        self._atualizar_status_footer()

    def _alternar_modo_real(self) -> None:
        if self.real_mode_switch.get() == 1:
            self.simulacao_mode_switch.deselect()
            self.modo_operacao = "real"
        elif self.simulacao_mode_switch.get() == 1:
            self.modo_operacao = "simulacao"
        else:
            self.modo_operacao = "desligado"

        if self.modo_operacao == "desligado":
            self.bot_running = False
            self.bot_button.configure(text="INICIAR BOT", fg_color=GREEN, hover_color="#16A34A")
        self._atualizar_status_footer()

    def _alternar_modo_simulacao(self) -> None:
        if self.simulacao_mode_switch.get() == 1:
            self.real_mode_switch.deselect()
            self.modo_operacao = "simulacao"
        elif self.real_mode_switch.get() == 1:
            self.modo_operacao = "real"
        else:
            self.modo_operacao = "desligado"

        if self.modo_operacao == "desligado":
            self.bot_running = False
            self.bot_button.configure(text="INICIAR BOT", fg_color=GREEN, hover_color="#16A34A")
        self._atualizar_status_footer()

    def _abrir_modal_simulacao(self) -> None:
        modal = ctk.CTkToplevel(self)
        modal.title("Configuracao de Simulacao")
        modal.geometry("430x330")
        modal.resizable(False, False)
        modal.grab_set()
        modal.configure(fg_color=APP_BG)

        ctk.CTkLabel(
            modal,
            text="Saldo inicial para simulacao (R$)",
            font=FONT_LABEL,
            text_color=TEXT_PRIMARY,
        ).pack(pady=(16, 6), padx=20, anchor="w")
        entry_saldo = ctk.CTkEntry(modal, placeholder_text="Ex: 10000")
        entry_saldo.pack(padx=20, fill="x")

        ctk.CTkLabel(
            modal,
            text="Valor maximo de compra por trade (R$)",
            font=FONT_LABEL,
            text_color=TEXT_PRIMARY,
        ).pack(pady=(14, 6), padx=20, anchor="w")
        entry_comprar = ctk.CTkEntry(modal, placeholder_text="Ex: 500")
        entry_comprar.pack(padx=20, fill="x")

        ctk.CTkLabel(
            modal,
            text="Valor maximo de venda por trade (R$)",
            font=FONT_LABEL,
            text_color=TEXT_PRIMARY,
        ).pack(pady=(14, 6), padx=20, anchor="w")
        entry_vender = ctk.CTkEntry(modal, placeholder_text="Ex: 700")
        entry_vender.pack(padx=20, fill="x")

        entry_saldo.focus()

        ctk.CTkButton(
            modal,
            text="Salvar Configuracao",
            height=40,
            font=FONT_LABEL,
            fg_color=GREEN,
            hover_color="#16A34A",
            command=lambda: self._salvar_modo_simulacao(
                entry_saldo.get(),
                entry_comprar.get(),
                entry_vender.get(),
                modal,
            ),
        ).pack(pady=20, padx=20, fill="x")

    def _salvar_modo_simulacao(self, saldo_texto: str, comprar_texto: str, vender_texto: str, modal: ctk.CTkToplevel) -> None:
        saldo = self._parse_float_positivo(saldo_texto)
        comprar = self._parse_float_positivo(comprar_texto)
        vender = self._parse_float_positivo(vender_texto)

        if saldo is None or comprar is None or vender is None:
            messagebox.showerror(
                "Valor invalido",
                "Preencha saldo, compra e venda com valores numericos maiores que zero.",
            )
            return

        self.simulation_engine.configure(initial_balance_brl=saldo, max_buy_brl=comprar, max_sell_brl=vender)
        self.total_trades = 0
        self._peak_balance_brl = saldo
        self.trades_label.configure(text=str(self.total_trades))
        self.lucro_label.configure(text="Lucro Hoje: R$0,00", text_color=TEXT_PRIMARY)
        self.drawdown_label.configure(text="Drawdown: +0.00%", text_color=GREEN)
        self.saldo_label.configure(text=f"Saldo: R${saldo:,.2f} | BTC: 0.00000000 (R$0,00)")
        modal.destroy()

    def _parse_float_positivo(self, valor: str) -> float | None:
        try:
            numero = float(str(valor).replace(",", "."))
            if numero <= 0:
                return None
            return numero
        except (TypeError, ValueError):
            return None

    def _atualizar_status_footer(self) -> None:
        if self.modo_operacao == "simulacao":
            modo = "MODO SIMULACAO"
        elif self.modo_operacao == "real":
            modo = "MODO REAL"
        else:
            modo = "DESLIGADO"
        prefixo = "RODANDO" if self.bot_running else "PARADO"
        self.status_label.configure(text=f"{prefixo}: {modo}")

    def executar_estrategia(self, preco: float) -> None:
        self.logger.info("Bot executando estrategia em modo real no preco: %s", preco)

    def executar_estrategia_simulada(self, dados: StrategySnapshot) -> None:
        if self.simulation_engine.initial_balance_brl <= 0:
            return

        btc_antes = self.simulation_engine.btc
        houve_trade = self.strategy_sma.executar_estrategia(self.simulation_engine, dados)
        if not houve_trade:
            return

        self.total_trades += 1
        self.trades_label.configure(text=str(self.total_trades))

        lado = "BUY" if self.simulation_engine.btc > btc_antes else "SELL"
        self._animar_pulso_trade(lado)

        if self.on_trade_update:
            self.on_trade_update()

    def _atualizar_painel_simulacao(self, preco_btc_brl: float) -> None:
        total_brl = self.simulation_engine.total_balance_brl(preco_btc_brl)
        btc_valor_brl = self.simulation_engine.btc * preco_btc_brl
        lucro = self.simulation_engine.calculate_profit(preco_btc_brl)

        if self._peak_balance_brl <= 0:
            self._peak_balance_brl = total_brl
        if total_brl > self._peak_balance_brl:
            self._peak_balance_brl = total_brl
        drawdown_pct = ((total_brl - self._peak_balance_brl) / self._peak_balance_brl) * 100 if self._peak_balance_brl > 0 else 0.0

        if lucro > 0:
            cor_lucro, sinal = GREEN, "+"
        elif lucro < 0:
            cor_lucro, sinal = RED, ""
        else:
            cor_lucro, sinal = TEXT_PRIMARY, ""

        cor_drawdown = GREEN if drawdown_pct >= 0 else RED
        self.drawdown_label.configure(text=f"Drawdown: {drawdown_pct:+.2f}%", text_color=cor_drawdown)
        self.lucro_label.configure(text=f"Lucro Hoje: {sinal}R${lucro:,.2f}", text_color=cor_lucro)
        self.saldo_label.configure(
            text=(
                f"Saldo: R${total_brl:,.2f} | BTC: {self.simulation_engine.btc:.8f} "
                f"(R${btc_valor_brl:,.2f}) | Compra max: R${self.simulation_engine.max_buy_brl:,.2f} "
                f"| Venda max: R${self.simulation_engine.max_sell_brl:,.2f}"
            )
        )

    def _atualizar_painel_real(self, preco_btc_brl: float) -> None:
        try:
            cliente = self.market_data.client
            btc_saldo = self._saldo_asset(cliente, "BTC")
            brl_saldo = self._saldo_asset(cliente, "BRL")
            usdt_saldo = self._saldo_asset(cliente, "USDT")
            usdt_brl = self.market_data.pegar_preco_atual("USDTBRL")

            btc_valor_brl = btc_saldo * preco_btc_brl
            usdt_valor_brl = usdt_saldo * usdt_brl
            total_brl = brl_saldo + btc_valor_brl + usdt_valor_brl
            self.saldo_label.configure(text=f"Saldo: R${total_brl:,.2f} | BTC: {btc_saldo:.8f} (R${btc_valor_brl:,.2f})")
            self.lucro_label.configure(text="Lucro Hoje: modo real", text_color=TEXT_PRIMARY)
        except Exception:
            self.saldo_label.configure(text="Saldo: indisponivel (API Binance)")
            self.lucro_label.configure(text="Lucro Hoje: modo real", text_color=TEXT_PRIMARY)

    def _saldo_asset(self, cliente, asset: str) -> float:
        dados = cliente.get_asset_balance(asset=asset)
        if not dados:
            return 0.0
        livre = float(dados.get("free", 0.0))
        bloqueado = float(dados.get("locked", 0.0))
        return livre + bloqueado

    def _animar_pulso_trade(self, side: str) -> None:
        if self._pulse_after_id:
            self.after_cancel(self._pulse_after_id)
            self._pulse_after_id = None

        alvo = self.buy_indicator if side == "BUY" else self.sell_indicator
        base_cor = GREEN if side == "BUY" else RED
        outro = self.sell_indicator if side == "BUY" else self.buy_indicator
        outro.configure(text_color=CARD_BORDER)

        passos = [0.35, 0.55, 0.75, 1.0, 0.8, 0.6, 0.42, 0.3]

        def _passo(i: int) -> None:
            intensidade = passos[i]
            cor = self._misturar_cores(base_cor, CARD_BG, intensidade)
            alvo.configure(text_color=cor)
            if i < len(passos) - 1:
                self._pulse_after_id = self.after(70, lambda: _passo(i + 1))
            else:
                alvo.configure(text_color=CARD_BORDER)

        _passo(0)

    @staticmethod
    def _hex_to_rgb(color_hex: str) -> tuple[int, int, int]:
        color_hex = color_hex.lstrip("#")
        return tuple(int(color_hex[i : i + 2], 16) for i in (0, 2, 4))

    @staticmethod
    def _rgb_to_hex(rgb: tuple[int, int, int]) -> str:
        return f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"

    def _misturar_cores(self, color_a: str, color_b: str, factor: float) -> str:
        rgb_a = self._hex_to_rgb(color_a)
        rgb_b = self._hex_to_rgb(color_b)
        f = max(0.0, min(1.0, factor))
        rgb_mix = (
            int(rgb_a[0] * f + rgb_b[0] * (1 - f)),
            int(rgb_a[1] * f + rgb_b[1] * (1 - f)),
            int(rgb_a[2] * f + rgb_b[2] * (1 - f)),
        )
        return self._rgb_to_hex(rgb_mix)
