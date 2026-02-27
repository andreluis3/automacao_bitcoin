import customtkinter as ctk
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.pyplot as plt
import random
import numpy as np
from CTkSpinbox import CTkSpinbox
import tkinter as tk





ctk.set_appearance_mode("dark")

class MainWindow(ctk.CTk):
    def __init__(self, market_data):   # ← RECEBE AQUI
        super().__init__()
        self.market_data = market_data

        self.title("Automação Bitcoin")
        self.geometry("1200x720")
        self.bot_running = False

        self.dados = []
        self._criar_layout()
        self._criar_grafico()
        self._atualizar_grafico()

    def _criar_layout(self):

        # ================= HEADER =================
        header = ctk.CTkFrame(self, fg_color="#2a2d31", corner_radius=15)
        header.pack(fill="x", padx=20, pady=15)

        self.preco_label = ctk.CTkLabel(
            header,
            text="BTC/USDT: --",
            font=("Arial", 26, "bold")
        )
        self.preco_label.pack(side="left", padx=20, pady=15)

        self.lucro_label = ctk.CTkLabel(
            header,
            text="Lucro Hoje: $0.00",
            font=("Arial", 16)
        )
        self.lucro_label.pack(side="right", padx=20)

        # ================= BODY =================
        body = ctk.CTkFrame(self, fg_color="#1e1f22")
        body.pack(fill="both", expand=True, padx=20, pady=10)

        body.grid_columnconfigure(0, weight=3)
        body.grid_columnconfigure(1, weight=1)
        body.grid_rowconfigure(0, weight=1)

        # ================= GRÁFICO =================
        self.chart_frame = ctk.CTkFrame(body, fg_color="#2a2d31", corner_radius=15)
        self.chart_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 15))

        # ================= SIDE PANEL =================
        side_panel = ctk.CTkFrame(body, fg_color="#2a2d31", corner_radius=15)
        side_panel.grid(row=0, column=1, sticky="nsew", padx=5, pady=5)

        # ===== TÍTULO =====
        titulo = ctk.CTkLabel(
            side_panel,
            text="CONFIGURAÇÃO DA ESTRATÉGIA",
            font=("Arial", 16, "bold")
        )
        titulo.pack(pady=(20, 10))

        # ===== VALOR DE ENTRADA =====
        ctk.CTkLabel(side_panel, text="Valor de Entrada (USDT)").pack(pady=(10, 5))

        self.entry_valor = tk.Spinbox(
        side_panel,
        from_=10,
        to=10000,
        increment=10,
        width=10
            )
        self.entry_valor.pack(pady=5)


        # ===== VALOR DE SAÍDA =====
        ctk.CTkLabel(side_panel, text="Intervalo de Atuação (%)").pack(pady=(15, 5))

        self.entry_intervalo = tk.Spinbox(
            side_panel,
            from_=0.1,
            to=10,
            increment=0.1,
            width=10
        )
        self.entry_intervalo.pack(pady=5)


        # ===== MODO AUTOMÁTICO =====
        self.auto_switch = ctk.CTkSwitch(
            side_panel,
            text="Automático (Média Móvel)",
        )
        self.auto_switch.pack(pady=20)

        # ===== BOTÃO INICIAR =====
        ctk.CTkButton(
            side_panel,
            text="INICIAR BOT",
            fg_color="#1f8f4e",
            height=40
        ).pack(pady=10, padx=20, fill="x")

        # ===== QUANTIDADE DE TRADES =====
        trades_container = ctk.CTkFrame(
            side_panel,
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


    def _criar_grafico(self):

        self.max_candles = 150
        self.prices = []

        self.fig, self.ax = plt.subplots(figsize=(8, 5))

        self.fig.patch.set_facecolor("#2a2d31")
        self.ax.set_facecolor("#1e1f22")

        # Linha preço
        self.price_line, = self.ax.plot([], [], color="white", linewidth=1.5)

        # Média rápida
        self.ma_fast_line, = self.ax.plot([], [], color="#00ff7f", linewidth=1)

        # Média lenta
        self.ma_slow_line, = self.ax.plot([], [], color="#ff4c4c", linewidth=1)

        self.ax.tick_params(colors="white")
        self.ax.grid(color="#3a3f44")

        self.canvas = FigureCanvasTkAgg(self.fig, master=self.chart_frame)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

    def _atualizar_grafico(self):

        try:
            preco = self.market_data.pegar_preco_atual("BTCUSDT")
            self.preco_label.configure(text=f"BTC/USDT: ${preco:,.2f}")

            self.prices.append(preco)

            if len(self.prices) > self.max_candles:
                self.prices = self.prices[-self.max_candles:]

            x = np.arange(len(self.prices))
            y = np.array(self.prices)

            # Médias móveis
            if len(y) >= 7:
                ma_fast = np.convolve(y, np.ones(7)/7, mode="valid")
                self.ma_fast_line.set_data(x[-len(ma_fast):], ma_fast)

            if len(y) >= 25:
                ma_slow = np.convolve(y, np.ones(25)/25, mode="valid")
                self.ma_slow_line.set_data(x[-len(ma_slow):], ma_slow)

            self.price_line.set_data(x, y) 

            if self.bot_running:
                self.executar_estrategia(preco)


            # Auto-scroll X
            self.ax.set_xlim(0, len(self.prices))

            # Auto-scale Y apenas do visível
            self.ax.relim()
            self.ax.autoscale_view()

            self.canvas.draw_idle() 

        except Exception as e:
            print("Erro:", e)

        self.after(1000, self._atualizar_grafico)

    def toggle_bot(self):
        if self.bot_switch.get() == 1:
            self.bot_switch.configure(text="BOT ON")
            self.bot_running = True
        else:
            self.bot_switch.configure(text="BOT OFF")
            self.bot_running = False

    def executar_estrategia(self, preco):
        print("Bot executando estratégia no preço:", preco)




