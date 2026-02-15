import customtkinter as ctk
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.pyplot as plt
import numpy as np
import tkinter as tk
from tkinter import messagebox

from backend.simulator import SimulationEngine


ctk.set_appearance_mode("dark")


class MainWindow(ctk.CTk):
    def __init__(self, market_data):
        super().__init__()
        self.market_data = market_data

        self.title("Automação Bitcoin")
        self.geometry("1200x720")

        self.bot_running = False
        self.preco_anterior = None
        self.modo_operacao = "desligado"
        self.total_trades = 0
        self.preco_referencia_simulacao = None
        self.simulation_engine = SimulationEngine()

        self._criar_layout()
        self._criar_grafico()
        self._atualizar_status_footer()
        self._atualizar_grafico()

    def _criar_layout(self):
        header = ctk.CTkFrame(self, fg_color="#2a2d31", corner_radius=15)
        header.pack(fill="x", padx=20, pady=15)

        self.preco_label = ctk.CTkLabel(
            header,
            text="BTC/USDT: --",
            font=("Arial", 26, "bold")
        )
        self.preco_label.pack(side="left", padx=20, pady=15)

        self.saldo_label = ctk.CTkLabel(
            header,
            text="Saldo: --",
            font=("Arial", 15)
        )
        self.saldo_label.pack(side="right", padx=(10, 20))

        self.lucro_label = ctk.CTkLabel(
            header,
            text="Lucro Hoje: R$0,00",
            font=("Arial", 16)
        )
        self.lucro_label.pack(side="right", padx=(20, 10))

        body = ctk.CTkFrame(self, fg_color="#1e1f22")
        body.pack(fill="both", expand=True, padx=20, pady=10)

        body.grid_columnconfigure(0, weight=3)
        body.grid_columnconfigure(1, weight=1)
        body.grid_rowconfigure(0, weight=1)

        self.chart_frame = ctk.CTkFrame(body, fg_color="#2a2d31", corner_radius=15)
        self.chart_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 15))

        self.side_panel = ctk.CTkFrame(body, fg_color="#2a2d31", corner_radius=15)
        self.side_panel.grid(row=0, column=1, sticky="nsew", padx=5, pady=5)

        titulo = ctk.CTkLabel(
            self.side_panel,
            text="CONFIGURAÇÃO DA ESTRATÉGIA",
            font=("Arial", 16, "bold")
        )
        titulo.pack(pady=(20, 10))

        ctk.CTkLabel(self.side_panel, text="Valor de Entrada (USDT)").pack(pady=(10, 5))
        self.entry_valor = tk.Spinbox(
            self.side_panel,
            from_=10,
            to=10000,
            increment=10,
            width=10
        )
        self.entry_valor.pack(pady=5)

        ctk.CTkLabel(self.side_panel, text="Intervalo de Atuação (%)").pack(pady=(15, 5))
        self.entry_intervalo = tk.Spinbox(
            self.side_panel,
            from_=0.1,
            to=10,
            increment=0.1,
            width=10
        )
        self.entry_intervalo.pack(pady=5)

        self.auto_switch = ctk.CTkSwitch(
            self.side_panel,
            text="Automático (Média Móvel)",
        )
        self.auto_switch.pack(pady=20)

        self.real_mode_switch = ctk.CTkSwitch(
            self.side_panel,
            text="Modo Real (ON/OFF)",
            command=self._alternar_modo_real
        )
        self.real_mode_switch.pack(pady=(0, 8))

        self.simulacao_mode_switch = ctk.CTkSwitch(
            self.side_panel,
            text="Modo Simulação (ON/OFF)",
            command=self._alternar_modo_simulacao
        )
        self.simulacao_mode_switch.pack(pady=(0, 12))

        self.simulacao_button = ctk.CTkButton(
            self.side_panel,
            text="Configurar Simulação",
            fg_color="#3a3f44",
            command=self._abrir_modal_simulacao
        )
        self.simulacao_button.pack(pady=(0, 12), padx=20, fill="x")

        self.bot_button = ctk.CTkButton(
            self.side_panel,
            text="INICIAR BOT",
            fg_color="#1f8f4e",
            height=40,
            command=self._toggle_execucao
        )
        self.bot_button.pack(pady=10, padx=20, fill="x")

        trades_container = ctk.CTkFrame(
            self.side_panel,
            fg_color="white",
            corner_radius=10
        )
        trades_container.pack(pady=25, padx=20, fill="x")

        ctk.CTkLabel(
            trades_container,
            text="QUANTIDADE DE TRADES",
            text_color="black",
            font=("Arial", 12, "bold")
        ).pack(pady=(10, 5))

        self.trades_label = ctk.CTkLabel(
            trades_container,
            text="0",
            text_color="black",
            font=("Arial", 24, "bold")
        )
        self.trades_label.pack(pady=(0, 15))

        footer = ctk.CTkFrame(self, fg_color="#2a2d31", corner_radius=10)
        footer.pack(fill="x", padx=20, pady=(0, 15))

        self.status_label = ctk.CTkLabel(
            footer,
            text="PARADO: DESLIGADO",
            font=("Arial", 14, "bold")
        )
        self.status_label.pack(padx=15, pady=10, anchor="w")

    def _criar_grafico(self):
        self.max_candles = 150
        self.prices = []

        self.fig, self.ax = plt.subplots(figsize=(8, 5))

        self.fig.patch.set_facecolor("#2a2d31")
        self.ax.set_facecolor("#1e1f22")

        self.price_line, = self.ax.plot([], [], color="white", linewidth=1.5)
        self.ma_fast_line, = self.ax.plot([], [], color="#00ff7f", linewidth=1)
        self.ma_slow_line, = self.ax.plot([], [], color="#ff4c4c", linewidth=1)

        self.ax.tick_params(colors="white")
        self.ax.grid(color="#3a3f44")

        self.canvas = FigureCanvasTkAgg(self.fig, master=self.chart_frame)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

    def _atualizar_grafico(self):
        try:
            preco_btc_usdt = self.market_data.pegar_preco_atual("BTCUSDT")
            preco_btc_brl = self._pegar_preco_btc_brl(preco_btc_usdt)

            texto_preco, cor_preco = self._montar_texto_preco_com_variacao(preco_btc_usdt)
            self.preco_label.configure(text=texto_preco, text_color=cor_preco)

            self.prices.append(preco_btc_usdt)
            if len(self.prices) > self.max_candles:
                self.prices = self.prices[-self.max_candles:]

            x = np.arange(len(self.prices))
            y = np.array(self.prices)

            if len(y) >= 7:
                ma_fast = np.convolve(y, np.ones(7) / 7, mode="valid")
                self.ma_fast_line.set_data(x[-len(ma_fast):], ma_fast)

            if len(y) >= 25:
                ma_slow = np.convolve(y, np.ones(25) / 25, mode="valid")
                self.ma_slow_line.set_data(x[-len(ma_slow):], ma_slow)

            self.price_line.set_data(x, y)

            if self.bot_running:
                if self.modo_operacao == "simulacao":
                    self.executar_estrategia_simulada(preco_btc_brl)
                elif self.modo_operacao == "real":
                    self.executar_estrategia(preco_btc_usdt)

            if self.modo_operacao == "simulacao":
                self._atualizar_painel_simulacao(preco_btc_brl)
            elif self.modo_operacao == "real":
                self._atualizar_painel_real(preco_btc_brl)
            else:
                self.saldo_label.configure(text="Saldo: --")

            self.ax.set_xlim(0, len(self.prices))
            self.ax.relim()
            self.ax.autoscale_view()
            self.canvas.draw_idle()

        except Exception as erro:
            print("Erro:", erro)

        self.after(1000, self._atualizar_grafico)

    def _pegar_preco_btc_brl(self, preco_btc_usdt):
        try:
            return self.market_data.pegar_preco_atual("BTCBRL")
        except Exception:
            try:
                usdt_brl = self.market_data.pegar_preco_atual("USDTBRL")
                return preco_btc_usdt * usdt_brl
            except Exception:
                return preco_btc_usdt

    def _montar_texto_preco_com_variacao(self, preco_atual):
        if self.preco_anterior is None or self.preco_anterior == 0:
            self.preco_anterior = preco_atual
            return f"BTC/USDT: ${preco_atual:,.2f}", "white"

        variacao_percentual = ((preco_atual - self.preco_anterior) / self.preco_anterior) * 100

        if variacao_percentual > 0:
            cor = "#1f8f4e"
            sinal = "+"
        elif variacao_percentual < 0:
            cor = "#ff4c4c"
            sinal = ""
        else:
            cor = "white"
            sinal = ""

        texto = f"BTC/USDT: ${preco_atual:,.2f} ({sinal}{variacao_percentual:.2f}%)"
        self.preco_anterior = preco_atual
        return texto, cor

    def _toggle_execucao(self):
        if not self.bot_running:
            if self.modo_operacao == "desligado":
                messagebox.showwarning("Modo", "Ligue o modo real ou o modo simulação antes de iniciar.")
                return

            if self.modo_operacao == "simulacao" and self.simulation_engine.initial_balance_brl <= 0:
                messagebox.showwarning(
                    "Simulação",
                    "Configure o modo simulação antes de iniciar o bot."
                )
                return

            self.bot_running = True
            self.bot_button.configure(text="PARAR BOT", fg_color="#b33939")
        else:
            self.bot_running = False
            self.bot_button.configure(text="INICIAR BOT", fg_color="#1f8f4e")

        self._atualizar_status_footer()

    def _alternar_modo_real(self):
        if self.real_mode_switch.get() == 1:
            self.simulacao_mode_switch.deselect()
            self.modo_operacao = "real"
        elif self.simulacao_mode_switch.get() == 1:
            self.modo_operacao = "simulacao"
        else:
            self.modo_operacao = "desligado"

        if self.modo_operacao == "desligado":
            self.bot_running = False
            self.bot_button.configure(text="INICIAR BOT", fg_color="#1f8f4e")

        self._atualizar_status_footer()

    def _alternar_modo_simulacao(self):
        if self.simulacao_mode_switch.get() == 1:
            self.real_mode_switch.deselect()
            self.modo_operacao = "simulacao"
        elif self.real_mode_switch.get() == 1:
            self.modo_operacao = "real"
        else:
            self.modo_operacao = "desligado"

        if self.modo_operacao == "desligado":
            self.bot_running = False
            self.bot_button.configure(text="INICIAR BOT", fg_color="#1f8f4e")

        self._atualizar_status_footer()

    def _abrir_modal_simulacao(self):
        modal = ctk.CTkToplevel(self)
        modal.title("Configuração de Simulação")
        modal.geometry("420x340")
        modal.resizable(False, False)
        modal.grab_set()

        ctk.CTkLabel(
            modal,
            text="Digite seu saldo que gostaria de simular (R$)",
            font=("Arial", 13, "bold")
        ).pack(pady=(15, 6), padx=20, anchor="w")
        entry_saldo = ctk.CTkEntry(modal, placeholder_text="Ex: 10000")
        entry_saldo.pack(padx=20, fill="x")

        ctk.CTkLabel(
            modal,
            text="Digite até quanto pretende comprar por trade (R$)",
            font=("Arial", 13, "bold")
        ).pack(pady=(14, 6), padx=20, anchor="w")
        entry_comprar = ctk.CTkEntry(modal, placeholder_text="Ex: 500")
        entry_comprar.pack(padx=20, fill="x")

        ctk.CTkLabel(
            modal,
            text="Digite até quanto pretende vender por trade (R$)",
            font=("Arial", 13, "bold")
        ).pack(pady=(14, 6), padx=20, anchor="w")
        entry_vender = ctk.CTkEntry(modal, placeholder_text="Ex: 700")
        entry_vender.pack(padx=20, fill="x")

        entry_saldo.focus()

        ctk.CTkButton(
            modal,
            text="Salvar Configuração",
            fg_color="#1f8f4e",
            command=lambda: self._salvar_modo_simulacao(
                entry_saldo.get(),
                entry_comprar.get(),
                entry_vender.get(),
                modal,
            )
        ).pack(pady=18, padx=20, fill="x")

    def _salvar_modo_simulacao(self, saldo_texto, comprar_texto, vender_texto, modal):
        saldo = self._parse_float_positivo(saldo_texto)
        comprar = self._parse_float_positivo(comprar_texto)
        vender = self._parse_float_positivo(vender_texto)

        if saldo is None or comprar is None or vender is None:
            messagebox.showerror(
                "Valor inválido",
                "Preencha entry_saldo, entry_comprar e entry_vender com valores numéricos maiores que zero."
            )
            return

        self.simulation_engine.configure(
            initial_balance_brl=saldo,
            max_buy_brl=comprar,
            max_sell_brl=vender,
        )
        self.preco_referencia_simulacao = None
        self.total_trades = 0

        self.trades_label.configure(text=str(self.total_trades))
        self.lucro_label.configure(text="Lucro Hoje: R$0,00", text_color="white")
        self.saldo_label.configure(
            text=(
                f"Saldo: R${saldo:,.2f} | BTC: 0.00000000 "
                f"(R$0,00)"
            )
        )

        modal.destroy()

    def _parse_float_positivo(self, valor):
        try:
            numero = float(str(valor).replace(",", "."))
            if numero <= 0:
                return None
            return numero
        except (TypeError, ValueError):
            return None

    def _atualizar_status_footer(self):
        if self.modo_operacao == "simulacao":
            modo = "MODO SIMULAÇÃO"
        elif self.modo_operacao == "real":
            modo = "MODO REAL"
        else:
            modo = "DESLIGADO"

        prefixo = "RODANDO" if self.bot_running else "PARADO"
        self.status_label.configure(text=f"{prefixo}: {modo}")

    def executar_estrategia(self, preco):
        print("Bot executando estratégia no preço:", preco)

    def executar_estrategia_simulada(self, preco_btc_brl):
        if self.simulation_engine.initial_balance_brl <= 0:
            return

        try:
            intervalo = float(self.entry_intervalo.get())
        except (TypeError, ValueError):
            intervalo = 1.0

        if self.preco_referencia_simulacao is None:
            self.preco_referencia_simulacao = preco_btc_brl
            return

        variacao = ((preco_btc_brl - self.preco_referencia_simulacao) / self.preco_referencia_simulacao) * 100

        if variacao <= -intervalo:
            comprado = self.simulation_engine.buy(preco_btc_brl)
            if comprado > 0:
                self.preco_referencia_simulacao = preco_btc_brl
                self.total_trades += 1
                self.trades_label.configure(text=str(self.total_trades))

        elif variacao >= intervalo:
            vendido = self.simulation_engine.sell(preco_btc_brl)
            if vendido > 0:
                self.preco_referencia_simulacao = preco_btc_brl
                self.total_trades += 1
                self.trades_label.configure(text=str(self.total_trades))

    def _atualizar_painel_simulacao(self, preco_btc_brl):
        total_brl = self.simulation_engine.total_balance_brl(preco_btc_brl)
        btc_valor_brl = self.simulation_engine.btc * preco_btc_brl
        lucro = self.simulation_engine.calculate_profit(preco_btc_brl)

        if lucro > 0:
            cor = "#1f8f4e"
            sinal = "+"
        elif lucro < 0:
            cor = "#ff4c4c"
            sinal = ""
        else:
            cor = "white"
            sinal = ""

        self.lucro_label.configure(text=f"Lucro Hoje: {sinal}R${lucro:,.2f}", text_color=cor)
        self.saldo_label.configure(
            text=(
                f"Saldo: R${total_brl:,.2f} | BTC: {self.simulation_engine.btc:.8f} "
                f"(R${btc_valor_brl:,.2f})"
            )
        )

    def _atualizar_painel_real(self, preco_btc_brl):
        try:
            cliente = self.market_data.client

            btc_saldo = self._saldo_asset(cliente, "BTC")
            brl_saldo = self._saldo_asset(cliente, "BRL")
            usdt_saldo = self._saldo_asset(cliente, "USDT")

            usdt_brl = self.market_data.pegar_preco_atual("USDTBRL")
            btc_valor_brl = btc_saldo * preco_btc_brl
            usdt_valor_brl = usdt_saldo * usdt_brl
            total_brl = brl_saldo + btc_valor_brl + usdt_valor_brl

            self.saldo_label.configure(
                text=(
                    f"Saldo: R${total_brl:,.2f} | BTC: {btc_saldo:.8f} "
                    f"(R${btc_valor_brl:,.2f})"
                )
            )
            self.lucro_label.configure(text="Lucro Hoje: Modo real", text_color="white")

        except Exception:
            self.saldo_label.configure(text="Saldo: indisponível (API Binance)")
            self.lucro_label.configure(text="Lucro Hoje: Modo real", text_color="white")

    def _saldo_asset(self, cliente, asset):
        dados = cliente.get_asset_balance(asset=asset)
        if not dados:
            return 0.0
        livre = float(dados.get("free", 0.0))
        bloqueado = float(dados.get("locked", 0.0))
        return livre + bloqueado
