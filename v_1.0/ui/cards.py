from __future__ import annotations

import customtkinter as ctk


def create_card(parent, title: str, value: str, row: int, col: int):
    card = ctk.CTkFrame(parent, fg_color="#0f172a", corner_radius=10)
    card.grid(row=row, column=col, sticky="nsew", padx=6, pady=6)
    ctk.CTkLabel(card, text=title, text_color="#9ca3af", font=("Arial", 11)).pack(anchor="w", padx=10, pady=(8, 2))
    value_label = ctk.CTkLabel(card, text=value, font=("Arial", 18, "bold"))
    value_label.pack(anchor="w", padx=10, pady=(0, 8))
    return value_label
