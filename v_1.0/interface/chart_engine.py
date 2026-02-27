from __future__ import annotations

from datetime import datetime
import tkinter as tk

try:
    from tkinterweb import HtmlFrame
except Exception:
    HtmlFrame = None

try:
    import plotly.graph_objects as go
except Exception:
    go = None


class ChartEngine:
    def __init__(self, master, theme: dict[str, str]):
        self.theme = theme
        self._mode = "html" if HtmlFrame is not None and go is not None else "canvas"
        self._last_html_payload = ""

        if self._mode == "html":
            self.html_frame = HtmlFrame(master)
            self.html_frame.pack(fill="both", expand=True, padx=10, pady=10)
            self.canvas = None
        else:
            self.canvas = tk.Canvas(master, highlightthickness=0, bg=self.theme["app_bg"])
            self.canvas.pack(fill="both", expand=True, padx=10, pady=10)
            self.html_frame = None

    def _plot_area(self, width: int, height: int) -> tuple[int, int, int, int]:
        left = 56
        top = 18
        right = max(left + 20, width - 14)
        bottom = max(top + 20, height - 26)
        return left, top, right, bottom

    def _to_y(self, value: float, y_min: float, y_max: float, top: int, bottom: int) -> float:
        if y_max <= y_min:
            return float(bottom)
        norm = (value - y_min) / (y_max - y_min)
        return float(bottom - norm * (bottom - top))

    def _draw_line_series(
        self,
        points: list[tuple[float, float]],
        color: str,
        width: int = 2,
        dash: tuple[int, int] | None = None,
    ) -> None:
        if len(points) < 2:
            return
        flat: list[float] = []
        for x, y in points:
            flat.extend([x, y])
        self.canvas.create_line(*flat, fill=color, width=width, smooth=True, dash=dash)

    def render(
        self,
        candles: list[dict],
        sma_rapida: list[float | None],
        sma_intermediaria: list[float | None],
        sma_lenta: list[float | None],
        upper_band: list[float | None],
        lower_band: list[float | None],
        markers: list[dict] | None = None,
        current_price: float | None = None,
    ) -> None:
        if self._mode == "html":
            self._render_html(
                candles=candles,
                sma_rapida=sma_rapida,
                sma_intermediaria=sma_intermediaria,
                sma_lenta=sma_lenta,
                upper_band=upper_band,
                lower_band=lower_band,
                markers=markers,
                current_price=current_price,
            )
            return

        self.canvas.delete("all")
        width = max(240, int(self.canvas.winfo_width()))
        height = max(160, int(self.canvas.winfo_height()))
        left, top, right, bottom = self._plot_area(width, height)

        self.canvas.create_rectangle(0, 0, width, height, fill=self.theme["app_bg"], outline=self.theme["app_bg"])
        self.canvas.create_rectangle(left, top, right, bottom, outline=self.theme["border"])

        if not candles:
            self.canvas.create_text(
                (left + right) / 2,
                (top + bottom) / 2,
                text="Sem dados de mercado",
                fill=self.theme["text_secondary"],
                font=("Segoe UI", 12),
            )
            return

        visible = candles[-180:]
        offset = len(candles) - len(visible)

        highs = [float(c["high"]) for c in visible]
        lows = [float(c["low"]) for c in visible]
        opens = [float(c["open"]) for c in visible]
        closes = [float(c["close"]) for c in visible]

        extra_values: list[float] = []
        for series in (sma_rapida, sma_intermediaria, sma_lenta, upper_band, lower_band):
            for value in series[offset:]:
                if value is not None:
                    extra_values.append(float(value))
        if current_price is not None:
            extra_values.append(float(current_price))

        y_min = min(lows + extra_values) if extra_values else min(lows)
        y_max = max(highs + extra_values) if extra_values else max(highs)
        pad = max((y_max - y_min) * 0.08, 1e-6)
        y_min -= pad
        y_max += pad

        steps = 5
        for i in range(steps + 1):
            y = top + (bottom - top) * i / steps
            self.canvas.create_line(left, y, right, y, fill=self.theme["border"], dash=(2, 4))

        n = len(visible)
        span = max(1, n - 1)
        x_step = (right - left) / span
        candle_w = max(2.0, min(12.0, x_step * 0.62))

        for i in range(n):
            x = left + i * x_step
            o = opens[i]
            h = highs[i]
            l = lows[i]
            c = closes[i]
            color = "#22C55E" if c >= o else "#EF4444"

            y_high = self._to_y(h, y_min, y_max, top, bottom)
            y_low = self._to_y(l, y_min, y_max, top, bottom)
            y_open = self._to_y(o, y_min, y_max, top, bottom)
            y_close = self._to_y(c, y_min, y_max, top, bottom)

            self.canvas.create_line(x, y_high, x, y_low, fill=color, width=1)
            body_top = min(y_open, y_close)
            body_bottom = max(y_open, y_close)
            if abs(body_bottom - body_top) < 1:
                body_bottom = body_top + 1
            self.canvas.create_rectangle(
                x - candle_w / 2,
                body_top,
                x + candle_w / 2,
                body_bottom,
                fill=color,
                outline=color,
            )

        def series_points(values: list[float | None]) -> list[tuple[float, float]]:
            points: list[tuple[float, float]] = []
            for i, value in enumerate(values[offset:]):
                if value is None:
                    continue
                x = left + i * x_step
                y = self._to_y(float(value), y_min, y_max, top, bottom)
                points.append((x, y))
            return points

        self._draw_line_series(series_points(sma_rapida), "#22C55E", width=2)
        self._draw_line_series(series_points(sma_intermediaria), "#38BDF8", width=2)
        self._draw_line_series(series_points(sma_lenta), "#EF4444", width=2)
        self._draw_line_series(series_points(upper_band), "#F59E0B", width=1, dash=(4, 3))
        self._draw_line_series(series_points(lower_band), "#F59E0B", width=1, dash=(4, 3))

        if current_price is not None:
            y_price = self._to_y(float(current_price), y_min, y_max, top, bottom)
            self.canvas.create_line(left, y_price, right, y_price, fill="#FFFFFF", width=1, dash=(5, 3))
            self.canvas.create_text(
                right - 4,
                y_price - 10,
                text=f"{float(current_price):.2f}",
                fill="#FFFFFF",
                font=("Segoe UI", 10, "bold"),
                anchor="e",
            )

        if markers:
            for marker in markers[-100:]:
                idx = int(marker.get("index", -1)) - offset
                if idx < 0 or idx >= n:
                    continue
                side = str(marker.get("side") or "")
                price = float(marker.get("price") or closes[idx])
                x = left + idx * x_step
                y = self._to_y(price, y_min, y_max, top, bottom)
                color = "#22C55E" if side == "SELL" else "#EF4444"
                size = 6
                if side == "SELL":
                    pts = [x, y - size, x - size, y + size, x + size, y + size]
                else:
                    pts = [x, y + size, x - size, y - size, x + size, y - size]
                self.canvas.create_polygon(*pts, fill=color, outline=color)

    def _render_html(
        self,
        candles: list[dict],
        sma_rapida: list[float | None],
        sma_intermediaria: list[float | None],
        sma_lenta: list[float | None],
        upper_band: list[float | None],
        lower_band: list[float | None],
        markers: list[dict] | None = None,
        current_price: float | None = None,
    ) -> None:
        if self.html_frame is None or go is None:
            return

        visible = candles[-180:] if candles else []
        if not visible:
            payload = "<html><body style='background:#0F172A;color:#94A3B8;font-family:Segoe UI,Arial,sans-serif'>Sem dados de mercado</body></html>"
            if payload != self._last_html_payload:
                self._last_html_payload = payload
                self.html_frame.load_html(payload)
            return

        x = [datetime.fromtimestamp(int(c["open_time"]) / 1000.0) for c in visible]
        opens = [float(c["open"]) for c in visible]
        highs = [float(c["high"]) for c in visible]
        lows = [float(c["low"]) for c in visible]
        closes = [float(c["close"]) for c in visible]
        offset = len(candles) - len(visible)

        fig = go.Figure()
        fig.add_trace(
            go.Candlestick(
                x=x,
                open=opens,
                high=highs,
                low=lows,
                close=closes,
                increasing={"line": {"color": "#22C55E"}, "fillcolor": "#22C55E"},
                decreasing={"line": {"color": "#EF4444"}, "fillcolor": "#EF4444"},
                name="Candles",
            )
        )

        def values_for(series: list[float | None]) -> list[float | None]:
            return [None if v is None else float(v) for v in series[offset:]]

        fig.add_trace(go.Scatter(x=x, y=values_for(sma_rapida), mode="lines", line={"color": "#22C55E", "width": 2}, name="SMA Rapida"))
        fig.add_trace(go.Scatter(x=x, y=values_for(sma_intermediaria), mode="lines", line={"color": "#38BDF8", "width": 2}, name="SMA Intermediaria"))
        fig.add_trace(go.Scatter(x=x, y=values_for(sma_lenta), mode="lines", line={"color": "#EF4444", "width": 2}, name="SMA Lenta"))
        fig.add_trace(go.Scatter(x=x, y=values_for(upper_band), mode="lines", line={"color": "#F59E0B", "width": 1, "dash": "dash"}, name="Desvio +"))
        fig.add_trace(go.Scatter(x=x, y=values_for(lower_band), mode="lines", line={"color": "#F59E0B", "width": 1, "dash": "dash"}, name="Desvio -"))

        if markers:
            marker_x: list[datetime] = []
            marker_y: list[float] = []
            marker_symbol: list[str] = []
            marker_color: list[str] = []
            for marker in markers[-100:]:
                idx = int(marker.get("index", -1)) - offset
                if idx < 0 or idx >= len(visible):
                    continue
                side = str(marker.get("side") or "")
                marker_x.append(x[idx])
                marker_y.append(float(marker.get("price") or closes[idx]))
                if side == "SELL":
                    marker_symbol.append("triangle-up")
                    marker_color.append("#22C55E")
                else:
                    marker_symbol.append("triangle-down")
                    marker_color.append("#EF4444")
            if marker_x:
                fig.add_trace(
                    go.Scatter(
                        x=marker_x,
                        y=marker_y,
                        mode="markers",
                        marker={"size": 9, "symbol": marker_symbol, "color": marker_color},
                        name="Trades",
                    )
                )

        if current_price is not None and x:
            fig.add_shape(
                type="line",
                x0=x[0],
                x1=x[-1],
                y0=float(current_price),
                y1=float(current_price),
                line={"color": "#FFFFFF", "width": 1, "dash": "dash"},
            )

        fig.update_layout(
            margin={"l": 24, "r": 16, "t": 18, "b": 24},
            paper_bgcolor="#0F172A",
            plot_bgcolor="#1E293B",
            font={"color": "#E2E8F0", "family": "Segoe UI, Arial, sans-serif"},
            xaxis={"rangeslider": {"visible": False}, "showgrid": False, "linecolor": "#334155"},
            yaxis={"showgrid": True, "gridcolor": "#334155", "zeroline": False},
            hovermode="x unified",
            showlegend=False,
        )

        payload = fig.to_html(include_plotlyjs="cdn", full_html=False, config={"responsive": True, "displaylogo": False})
        if payload != self._last_html_payload:
            self._last_html_payload = payload
            self.html_frame.load_html(payload)
