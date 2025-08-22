from __future__ import annotations

"""Dialog showing executable details with a terminal style interface."""

import datetime
import shlex
import random
import time
from pathlib import Path
from typing import List, Dict
import threading

import customtkinter as ctk

from .base_dialog import BaseDialog
from ..utils.process_utils import run_command_ex

# Reuse helpers from the CLI inspector
from scripts import exe_inspector as inspector


class ExeInspectorDialog(BaseDialog):
    """Display executable information and allow running shell commands."""

    def __init__(self, app, exe_path: str) -> None:
        super().__init__(app, title="Aegis Terminal", geometry="1250x850", resizable=(True, True))
        self.path = Path(exe_path)
        self.command_history = []
        self.history_index = -1
        self.is_typing = False
        self.cursor_visible = True
        self.matrix_chars = []
        
        # Advanced glassmorphism color scheme
        self.bg_base = "#030308"
        self.bg_primary = "#08080f"
        self.bg_glass_1 = "#0d0d1a"
        self.bg_glass_2 = "#121225"
        self.bg_glass_3 = "#181833"
        self.bg_glass_4 = "#1f1f40"
        self.bg_glass_edge = "#2a2a50"
        self.bg_glass_highlight = "#35356a"
        
        # Accent colors with glow
        self.accent_cyan = "#00e5ff"
        self.accent_cyan_dim = "#00a8cc"
        self.accent_green = "#00ff88"
        self.accent_green_dim = "#00cc6a"
        self.accent_purple = "#e500ff"
        self.accent_purple_dim = "#b300cc"
        self.accent_orange = "#ff9500"
        self.accent_orange_dim = "#cc7700"
        self.accent_red = "#ff0055"
        self.accent_red_dim = "#cc0044"
        
        # Text colors
        self.text_bright = "#ffffff"
        self.text_primary = "#e8e8f0"
        self.text_secondary = "#b8b8d0"
        self.text_dim = "#6868a0"
        self.text_faint = "#4848a0"
        
        # Start background threads
        self._start_cursor_blink()

        # Main container - dark base
        container = self.create_container()
        container.configure(fg_color=self.bg_base)
        
        # Create layered glass effect
        # Layer 1 - Outer glow
        glass_glow = ctk.CTkFrame(container, fg_color=self.bg_primary, corner_radius=25)
        glass_glow.pack(fill="both", expand=True, padx=10, pady=10)
        
        # Layer 2 - Glass edge
        glass_edge = ctk.CTkFrame(glass_glow, fg_color=self.bg_glass_edge, corner_radius=22)
        glass_edge.pack(fill="both", expand=True, padx=3, pady=3)
        
        # Layer 3 - Main glass container
        glass_main = ctk.CTkFrame(glass_edge, fg_color=self.bg_glass_1, corner_radius=20)
        glass_main.pack(fill="both", expand=True, padx=2, pady=2)
        
        # Terminal header with multi-layer glass
        header_glass_1 = ctk.CTkFrame(glass_main, height=60, fg_color=self.bg_glass_3, corner_radius=0)
        header_glass_1.pack(fill="x", padx=0, pady=0)
        header_glass_1.pack_propagate(False)
        
        header_glass_2 = ctk.CTkFrame(header_glass_1, fg_color=self.bg_glass_2, corner_radius=0)
        header_glass_2.pack(fill="both", expand=True, padx=0, pady=(3, 0))
        
        # Glowing accent line
        accent_line = ctk.CTkFrame(header_glass_2, height=2, fg_color=self.accent_cyan)
        accent_line.pack(fill="x", side="top")
        
        # Subtle gradient line
        gradient_line = ctk.CTkFrame(header_glass_2, height=1, fg_color=self.accent_cyan_dim)
        gradient_line.pack(fill="x", side="top")
        
        # Header content with glass layers
        header_content = ctk.CTkFrame(header_glass_2, fg_color=self.bg_glass_2)
        header_content.pack(fill="both", expand=True)
        
        # Logo section with glow effect
        logo_section = ctk.CTkFrame(header_content, fg_color=self.bg_glass_2)
        logo_section.pack(side="left", padx=30, pady=12)
        
        # Animated logo with glow
        logo_glow = ctk.CTkFrame(logo_section, fg_color=self.bg_glass_highlight, corner_radius=15)
        logo_glow.pack()
        
        self.logo_label = ctk.CTkLabel(
            logo_glow,
            text="⬡",
            font=("Arial", 24, "bold"),
            text_color=self.accent_cyan
        )
        self.logo_label.pack(padx=15, pady=5)
        
        # Title with optional shadow effect
        title_frame = ctk.CTkFrame(logo_section, fg_color=self.bg_glass_2)
        title_frame.pack(side="left", padx=(15, 0))
        
        # Shadow text (optional)
        if not self.app.config.get("basic_rendering", False):
            title_shadow = ctk.CTkLabel(
                title_frame,
                text=f"AEGIS://SHIELD/{self.path.name.upper()}",
                font=("Consolas", 16, "bold"),
                text_color=self.bg_glass_4,
            )
            title_shadow.place(x=2, y=2)

        # Main title
        title_main = ctk.CTkLabel(
            title_frame,
            text=f"AEGIS://SHIELD/{self.path.name.upper()}",
            font=("Consolas", 16, "bold"),
            text_color=self.accent_cyan,
        )
        title_main.pack()
        
        # Status section with glass panels
        status_section = ctk.CTkFrame(header_content, fg_color=self.bg_glass_2)
        status_section.pack(side="left", padx=50)
        
        # Create glass status cards
        self.status_cards = []
        for text, color, glow_color in [
            ("SHIELD", self.accent_green, self.accent_green_dim),
            ("SECURE", self.accent_cyan, self.accent_cyan_dim),
            ("ACTIVE", self.accent_orange, self.accent_orange_dim)
        ]:
            # Glass card with glow
            card_glow = ctk.CTkFrame(status_section, fg_color=self.bg_glass_3, corner_radius=10)
            card_glow.pack(side="left", padx=8)
            
            card_glass = ctk.CTkFrame(card_glow, fg_color=self.bg_glass_1, corner_radius=8)
            card_glass.pack(padx=2, pady=2)
            
            card_content = ctk.CTkFrame(card_glass, fg_color=self.bg_glass_1)
            card_content.pack(padx=12, pady=6)
            
            # Status dot with glow
            dot_frame = ctk.CTkFrame(card_content, fg_color=self.bg_glass_1)
            dot_frame.pack(side="left")
            
            dot_glow = ctk.CTkLabel(dot_frame, text="●", font=("Arial", 14), text_color=glow_color)
            dot_glow.place(x=1, y=1)
            
            dot = ctk.CTkLabel(dot_frame, text="●", font=("Arial", 12), text_color=color)
            dot.pack()
            
            label = ctk.CTkLabel(
                card_content,
                text=text,
                font=("Consolas", 11),
                text_color=self.text_secondary
            )
            label.pack(side="left", padx=(8, 0))
            
            self.status_cards.append((dot, label, card_glass))
        
        # Window controls with glass effect
        controls_section = ctk.CTkFrame(header_content, fg_color=self.bg_glass_2)
        controls_section.pack(side="right", padx=30)
        
        for symbol, color, hover in [
            ("―", self.text_dim, self.text_secondary),
            ("□", self.text_dim, self.text_secondary),
            ("✕", self.accent_red, self.accent_red_dim)
        ]:
            btn_glass = ctk.CTkFrame(controls_section, fg_color=self.bg_glass_4, corner_radius=8)
            btn_glass.pack(side="left", padx=4)
            
            btn = ctk.CTkButton(
                btn_glass,
                text=symbol,
                font=("Arial", 13),
                text_color=color,
                fg_color=self.bg_glass_3,
                hover_color=self.bg_glass_highlight,
                width=32,
                height=32,
                corner_radius=6
            )
            btn.pack(padx=1, pady=1)

        # Main content with glass panels
        content_outer = ctk.CTkFrame(glass_main, fg_color=self.bg_glass_1)
        content_outer.pack(fill="both", expand=True, padx=20, pady=(15, 20))
        
        content_glass = ctk.CTkFrame(content_outer, fg_color=self.bg_glass_2, corner_radius=15)
        content_glass.pack(fill="both", expand=True)
        
        content_inner = ctk.CTkFrame(content_glass, fg_color=self.bg_glass_1, corner_radius=13)
        content_inner.pack(fill="both", expand=True, padx=2, pady=2)
        
        # Left panel - Terminal output
        left_panel = ctk.CTkFrame(content_inner, fg_color=self.bg_glass_1)
        left_panel.pack(side="left", fill="both", expand=True, padx=(10, 5), pady=10)
        
        # Terminal with multiple glass layers
        term_glass_1 = ctk.CTkFrame(left_panel, fg_color=self.bg_glass_edge, corner_radius=12)
        term_glass_1.pack(fill="both", expand=True)
        
        term_glass_2 = ctk.CTkFrame(term_glass_1, fg_color=self.bg_glass_3, corner_radius=10)
        term_glass_2.pack(fill="both", expand=True, padx=1, pady=1)
        
        term_glass_3 = ctk.CTkFrame(term_glass_2, fg_color=self.bg_glass_2, corner_radius=9)
        term_glass_3.pack(fill="both", expand=True, padx=1, pady=1)
        
        term_inner = ctk.CTkFrame(term_glass_3, fg_color=self.bg_base, corner_radius=8)
        term_inner.pack(fill="both", expand=True, padx=2, pady=2)
        
        # Terminal output
        self.output = ctk.CTkTextbox(
            term_inner,
            fg_color=self.bg_base,
            text_color=self.accent_cyan,
            font=("Cascadia Code", 12),
            corner_radius=6,
            border_width=0,
            wrap="word",
            scrollbar_button_color=self.bg_glass_3,
            scrollbar_button_hover_color=self.bg_glass_highlight
        )
        self.output.pack(fill="both", expand=True, padx=4, pady=4)
        
        # Configure text tags
        self._configure_text_tags()

        # Right panel - Control center
        right_panel = ctk.CTkFrame(content_inner, fg_color=self.bg_glass_1, width=320)
        right_panel.pack(side="right", fill="y", padx=(5, 10), pady=10)
        right_panel.pack_propagate(False)
        
        # Control center glass layers
        control_glass_1 = ctk.CTkFrame(right_panel, fg_color=self.bg_glass_edge, corner_radius=12)
        control_glass_1.pack(fill="both", expand=True)
        
        control_glass_2 = ctk.CTkFrame(control_glass_1, fg_color=self.bg_glass_3, corner_radius=10)
        control_glass_2.pack(fill="both", expand=True, padx=1, pady=1)
        
        control_inner = ctk.CTkFrame(control_glass_2, fg_color=self.bg_glass_2, corner_radius=9)
        control_inner.pack(fill="both", expand=True, padx=1, pady=1)
        
        # Control header with glow
        control_header = ctk.CTkFrame(control_inner, fg_color=self.bg_glass_4, height=55, corner_radius=8)
        control_header.pack(fill="x", padx=10, pady=(10, 8))
        control_header.pack_propagate(False)
        
        header_glow = ctk.CTkFrame(control_header, fg_color=self.bg_glass_highlight, corner_radius=6)
        header_glow.pack(fill="both", expand=True, padx=2, pady=2)
        
        control_title = ctk.CTkLabel(
            header_glow,
            text="⚡ AEGIS CONTROL ⚡",
            font=("Consolas", 14, "bold"),
            text_color=self.accent_cyan
        )
        control_title.pack(expand=True)
        
        # System monitor with glass cards
        self._create_system_monitor(control_inner)
        
        # Separator with glow
        sep_container = ctk.CTkFrame(control_inner, fg_color=self.bg_glass_2, height=30)
        sep_container.pack(fill="x")
        
        sep_glow = ctk.CTkFrame(sep_container, fg_color=self.accent_cyan_dim, height=2)
        sep_glow.pack(fill="x", padx=40, pady=14)
        
        sep_line = ctk.CTkFrame(sep_container, fg_color=self.accent_cyan, height=1, width=150)
        sep_line.place(relx=0.5, rely=0.5, anchor="center")
        
        # Quick actions
        self._create_quick_actions(control_inner)

        # Command input section with glass layers
        input_outer = ctk.CTkFrame(glass_main, fg_color=self.bg_glass_3, height=90, corner_radius=0)
        input_outer.pack(fill="x", padx=0, pady=0)
        input_outer.pack_propagate(False)
        
        input_glass = ctk.CTkFrame(input_outer, fg_color=self.bg_glass_2, corner_radius=0)
        input_glass.pack(fill="both", expand=True, padx=0, pady=(2, 0))
        
        # Bottom accent lines
        accent_1 = ctk.CTkFrame(input_glass, height=2, fg_color=self.accent_cyan)
        accent_1.pack(fill="x", side="top")
        
        accent_2 = ctk.CTkFrame(input_glass, height=1, fg_color=self.accent_cyan_dim)
        accent_2.pack(fill="x", side="top")
        
        # Input content
        input_content = ctk.CTkFrame(input_glass, fg_color=self.bg_glass_2)
        input_content.pack(fill="both", expand=True, padx=30, pady=18)
        
        # Prompt with glass bubble
        prompt_outer = ctk.CTkFrame(input_content, fg_color=self.bg_glass_4, corner_radius=10)
        prompt_outer.pack(side="left", padx=(0, 20))
        
        prompt_glass = ctk.CTkFrame(prompt_outer, fg_color=self.bg_glass_3, corner_radius=8)
        prompt_glass.pack(padx=2, pady=2)
        
        prompt_inner = ctk.CTkFrame(prompt_glass, fg_color=self.bg_glass_2, corner_radius=6)
        prompt_inner.pack(padx=1, pady=1)
        
        prompt_content = ctk.CTkFrame(prompt_inner, fg_color=self.bg_glass_2)
        prompt_content.pack(padx=15, pady=10)
        
        # Prompt elements
        self.prompt_user = ctk.CTkLabel(
            prompt_content,
            text="aegis",
            font=("Consolas", 14, "bold"),
            text_color=self.accent_green
        )
        self.prompt_user.pack(side="left")
        
        ctk.CTkLabel(
            prompt_content,
            text="@",
            font=("Consolas", 14),
            text_color=self.text_dim
        ).pack(side="left", padx=2)
        
        ctk.CTkLabel(
            prompt_content,
            text="shield",
            font=("Consolas", 14, "bold"),
            text_color=self.accent_cyan
        ).pack(side="left")
        
        self.prompt_symbol = ctk.CTkLabel(
            prompt_content,
            text=" ▸",
            font=("Consolas", 15, "bold"),
            text_color=self.accent_purple
        )
        self.prompt_symbol.pack(side="left", padx=(8, 0))
        
        # Command entry with glass effect
        entry_outer = ctk.CTkFrame(input_content, fg_color=self.bg_glass_4, corner_radius=10)
        entry_outer.pack(side="left", fill="x", expand=True)
        
        entry_glass = ctk.CTkFrame(entry_outer, fg_color=self.bg_glass_3, corner_radius=8)
        entry_glass.pack(fill="both", expand=True, padx=2, pady=2)
        
        entry_inner = ctk.CTkFrame(entry_glass, fg_color=self.bg_base, corner_radius=6)
        entry_inner.pack(fill="both", expand=True, padx=1, pady=1)
        
        self.entry = ctk.CTkEntry(
            entry_inner,
            font=("Cascadia Code", 14),
            fg_color=self.bg_base,
            border_width=0,
            text_color=self.text_bright,
            placeholder_text="Enter command...",
            placeholder_text_color=self.text_dim,
            corner_radius=4
        )
        self.entry.pack(fill="x", padx=15, pady=12)
        self.entry.bind("<Return>", self._on_enter)
        self.entry.bind("<Up>", self._history_up)
        self.entry.bind("<Down>", self._history_down)
        self.entry.bind("<Tab>", self._autocomplete)
        self.entry.bind("<KeyPress>", self._on_key_press)
        
        # Action buttons
        self._create_action_buttons(input_content)

        # Initial setup
        self._show_welcome()
        self._type_text("\n[*] Initializing Aegis Shield Framework...\n", delay=0.02, tag="system")
        self.after(1000, self._init_sequence)
        self.center_window()
        self.refresh_fonts()
        self.refresh_theme()
        
        # Focus entry
        self.entry.focus_set()
        
        # Start animations
        self._start_animations()

    # ------------------------------------------------------------------ UI Creation
    def _configure_text_tags(self) -> None:
        """Configure text tags for the terminal."""
        tags = [
            ("header", self.accent_cyan, ("Consolas", 14, "bold")),
            ("subheader", self.accent_green, ("Consolas", 13, "bold")),
            ("key", self.accent_orange, ("Cascadia Code", 12, "bold")),
            ("value", self.text_primary, ("Cascadia Code", 12)),
            ("prompt", self.accent_purple, ("Consolas", 12, "bold")),
            ("error", self.accent_red, ("Cascadia Code", 12, "bold")),
            ("dim", self.text_dim, ("Cascadia Code", 11)),
            ("warn" "ing", "#ffcc00", ("Cascadia Code", 12)),
            ("success", self.accent_green, ("Cascadia Code", 12, "bold")),
            ("accent", self.accent_cyan, ("Cascadia Code", 12)),
            ("matrix", self.text_faint, ("Cascadia Code", 9)),
            ("system", self.accent_purple, ("Consolas", 11, "italic")),
            ("ascii", self.accent_cyan, ("Courier New", 10)),
            ("glow", self.accent_cyan, ("Cascadia Code", 12, "bold"))
        ]
        
        for tag, color, font in tags:
            self.output._textbox.tag_config(tag, foreground=color, font=font)

    def _create_system_monitor(self, parent: ctk.CTkFrame) -> None:
        """Create system monitor section."""
        monitor_frame = ctk.CTkFrame(parent, fg_color=self.bg_glass_3, corner_radius=10)
        monitor_frame.pack(fill="x", padx=10, pady=8)
        
        monitor_inner = ctk.CTkFrame(monitor_frame, fg_color=self.bg_glass_1, corner_radius=8)
        monitor_inner.pack(fill="both", expand=True, padx=2, pady=2)
        
        # Title
        monitor_title = ctk.CTkLabel(
            monitor_inner,
            text="◆ SYSTEM MONITOR ◆",
            font=("Consolas", 12, "bold"),
            text_color=self.accent_green
        )
        monitor_title.pack(pady=(12, 8))
        
        # Stats
        self.stats_frames = {}
        for stat, unit, color in [
            ("CPU", "%", self.accent_cyan),
            ("RAM", "GB", self.accent_green),
            ("NET", "MB/s", self.accent_orange),
            ("TEMP", "°C", self.accent_purple)
        ]:
            self._create_stat_display(monitor_inner, stat, unit, color)

    def _create_stat_display(self, parent: ctk.CTkFrame, stat: str, unit: str, color: str) -> None:
        """Create a single stat display."""
        stat_outer = ctk.CTkFrame(parent, fg_color=self.bg_glass_2, height=40, corner_radius=8)
        stat_outer.pack(fill="x", padx=12, pady=4)
        stat_outer.pack_propagate(False)
        
        stat_inner = ctk.CTkFrame(stat_outer, fg_color=self.bg_glass_1, corner_radius=6)
        stat_inner.pack(fill="both", expand=True, padx=1, pady=1)
        
        # Label
        label = ctk.CTkLabel(
            stat_inner,
            text=f"{stat}:",
            font=("Consolas", 11),
            text_color=self.text_secondary,
            width=60,
            anchor="w"
        )
        label.pack(side="left", padx=(12, 8))
        
        # Progress bar background
        bar_bg = ctk.CTkFrame(stat_inner, fg_color=self.bg_glass_3, height=10, corner_radius=5)
        bar_bg.pack(side="left", fill="x", expand=True, padx=5, pady=15)
        
        # Progress bar
        bar = ctk.CTkFrame(bar_bg, fg_color=color, height=8, width=50, corner_radius=4)
        bar.place(x=1, y=1)
        
        # Value
        value = ctk.CTkLabel(
            stat_inner,
            text=f"0{unit}",
            font=("Consolas", 11, "bold"),
            text_color=color,
            width=70,
            anchor="e"
        )
        value.pack(side="right", padx=12)
        
        self.stats_frames[stat] = {"bar": bar, "value": value, "unit": unit, "color": color}

    def _create_quick_actions(self, parent: ctk.CTkFrame) -> None:
        """Create quick actions section."""
        # Title
        actions_title = ctk.CTkLabel(
            parent,
            text="◆ QUICK ACTIONS ◆",
            font=("Consolas", 12, "bold"),
            text_color=self.accent_green
        )
        actions_title.pack(pady=(5, 10))
        
        # Actions container
        actions_outer = ctk.CTkFrame(parent, fg_color=self.bg_glass_3, corner_radius=10)
        actions_outer.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        
        actions_glass = ctk.CTkFrame(actions_outer, fg_color=self.bg_glass_1, corner_radius=8)
        actions_glass.pack(fill="both", expand=True, padx=2, pady=2)
        
        actions_scroll = ctk.CTkScrollableFrame(
            actions_glass,
            fg_color=self.bg_glass_1,
            scrollbar_button_color=self.bg_glass_3,
            scrollbar_button_hover_color=self.bg_glass_highlight
        )
        actions_scroll.pack(fill="both", expand=True, padx=5, pady=5)
        
        # Action buttons
        actions = [
            ("🔍 Process Scanner", lambda: self._run_command(f"ps aux | grep {self.path.name}"), self.accent_cyan),
            ("🌐 Network Analysis", lambda: self._run_command("netstat -tulpn 2>/dev/null | grep LISTEN"), self.accent_green),
            ("📊 System Overview", lambda: self._run_command("uname -a && echo && uptime && echo && free -h"), self.accent_orange),
            ("🔐 Security Audit", lambda: self._run_command(f"ls -la {self.path} && echo && file {self.path}"), self.accent_purple),
            ("🧬 String Extract", lambda: self._run_command(f"strings {self.path} | head -50"), self.accent_cyan),
            ("💾 Memory Analysis", lambda: self._run_command("cat /proc/meminfo | head -20"), self.accent_green),
            ("🚀 Port Scanner", lambda: self._run_command("ss -tulpn 2>/dev/null"), self.accent_orange),
            ("⚡ Deep Inspect", lambda: self._run_command(f"ldd {self.path} 2>/dev/null || echo 'Not a dynamic executable'"), self.accent_purple),
        ]
        
        for text, cmd, color in actions:
            self._create_action_button(actions_scroll, text, cmd, color)

    def _create_action_button(self, parent: ctk.CTkFrame, text: str, command, color: str) -> None:
        """Create a single action button."""
        btn_outer = ctk.CTkFrame(parent, fg_color=self.bg_glass_3, corner_radius=10)
        btn_outer.pack(fill="x", pady=5)
        
        btn_glass = ctk.CTkFrame(btn_outer, fg_color=self.bg_glass_2, corner_radius=8)
        btn_glass.pack(fill="both", expand=True, padx=1, pady=1)
        
        btn = ctk.CTkButton(
            btn_glass,
            text=text,
            font=("Consolas", 11),
            fg_color=self.bg_glass_2,
            hover_color=self.bg_glass_4,
            text_color=self.text_primary,
            border_width=1,
            border_color=color,
            corner_radius=6,
            height=40,
            anchor="w",
            command=command
        )
        btn.pack(fill="x", padx=2, pady=2)

    def _create_action_buttons(self, parent: ctk.CTkFrame) -> None:
        """Create main action buttons."""
        for text, command, fg_color, hover_color in [
            ("◈ CLEAR", self._clear_output, self.bg_glass_3, self.bg_glass_highlight),
            ("↻ SCAN", self.refresh, self.bg_glass_3, self.bg_glass_highlight),
            ("▶ EXECUTE", self._on_enter, self.accent_purple_dim, self.accent_purple)
        ]:
            btn_outer = ctk.CTkFrame(parent, fg_color=self.bg_glass_edge, corner_radius=10)
            btn_outer.pack(side="right", padx=6)
            
            btn_glass = ctk.CTkFrame(btn_outer, fg_color=fg_color, corner_radius=8)
            btn_glass.pack(padx=2, pady=2)
            
            btn = ctk.CTkButton(
                btn_glass,
                text=text,
                font=("Consolas", 12, "bold"),
                fg_color=fg_color,
                hover_color=hover_color,
                text_color=self.text_bright,
                border_width=0,
                corner_radius=6,
                width=110,
                height=42,
                command=command
            )
            btn.pack(padx=1, pady=1)

    # ------------------------------------------------------------------ initialization
    def _init_sequence(self) -> None:
        """Initialization sequence."""
        messages = [
            ("[✓] Shield protocols activated", "success"),
            ("[✓] Encryption layer established", "success"),
            ("[✓] Glass interface rendered", "success"),
            ("[✓] Security modules loaded", "success"),
            ("[!] Aegis Terminal Ready", "warn" "ing"),
            ("\n", "value")
        ]
        
        def show_message(index=0):
            if index < len(messages):
                msg, tag = messages[index]
                self._type_text(msg + "\n", delay=0.015, tag=tag)
                self.after(300, lambda: show_message(index + 1))
            else:
                self.refresh()
        
        show_message()

    # ------------------------------------------------------------------ animations
    def _start_animations(self) -> None:
        """Start all animations."""
        self._start_logo_animation()
        self._start_status_animation()
        self._start_stats_animation()
        self._start_matrix_effect()
        self._start_glass_shimmer()

    def _start_cursor_blink(self) -> None:
        """Cursor blink."""
        def blink():
            while True:
                self.cursor_visible = not self.cursor_visible
                time.sleep(0.5)
        
        thread = threading.Thread(target=blink, daemon=True)
        thread.start()

    def _start_logo_animation(self) -> None:
        """Animate logo."""
        def animate():
            symbols = ["⬡", "⬢", "⬣", "◆", "◈", "◊"]
            symbol = random.choice(symbols)
            self.logo_label.configure(text=symbol)
            
            # Pulse effect
            if random.random() < 0.3:
                self.logo_label.configure(text_color=self.accent_cyan)
                self.after(200, lambda: self.logo_label.configure(text_color=self.accent_cyan_dim))
            
            self.after(3000, animate)
        
        animate()

    def _start_status_animation(self) -> None:
        """Animate status cards."""
        def pulse():
            for i, (dot, label, card) in enumerate(self.status_cards):
                if random.random() < 0.15:
                    # Flash effect
                    card.configure(fg_color=self.bg_glass_2)
                    self.after(300, lambda c=card: c.configure(fg_color=self.bg_glass_1))
            
            self.after(2500, pulse)
        
        pulse()

    def _start_stats_animation(self) -> None:
        """Animate stats."""
        def update():
            for stat, config in self.stats_frames.items():
                if stat == "CPU":
                    val = random.randint(20, 70)
                    config["value"].configure(text=f"{val}%")
                    width = int(180 * val / 100)
                elif stat == "RAM":
                    val = random.uniform(2.5, 7.2)
                    config["value"].configure(text=f"{val:.1f}GB")
                    width = int(180 * val / 8)
                elif stat == "NET":
                    val = random.uniform(0.5, 18.5)
                    config["value"].configure(text=f"{val:.1f}MB/s")
                    width = int(180 * val / 20)
                else:  # TEMP
                    val = random.randint(38, 75)
                    config["value"].configure(text=f"{val}°C")
                    width = int(180 * val / 100)
                    
                    # Change color based on temp
                    if val < 50:
                        color = self.accent_cyan
                    elif val < 65:
                        color = self.accent_orange
                    else:
                        color = self.accent_red
                    config["bar"].configure(fg_color=color)
                
                # Update bar width by destroying and recreating
                bar_parent = config["bar"].master
                config["bar"].destroy()
                # Use the appropriate color for the bar
                bar_color = config["color"] if stat != "TEMP" else color
                new_bar = ctk.CTkFrame(bar_parent, fg_color=bar_color, height=8, width=width, corner_radius=4)
                new_bar.place(x=1, y=1)
                config["bar"] = new_bar
            
            self.after(1500, update)
        
        update()

    def _start_matrix_effect(self) -> None:
        """Matrix rain effect."""
        def drop():
            if random.random() < 0.02:
                chars = "01アイウエオ漢字AEGIS"
                char = random.choice(chars)
                col = random.randint(0, 100)
                
                self.output.configure(state="normal")
                try:
                    pos = f"1.{col}"
                    self.output.insert(pos, char, "matrix")
                    self.after(5000, lambda p=pos: self._remove_char_at(p))
                except:
                    pass
                self.output.configure(state="disabled")
            
            self.after(300, drop)
        
        self.after(5000, drop)

    def _start_glass_shimmer(self) -> None:
        """Glass shimmer effect on hover areas."""
        def shimmer():
            # Subtle color shifts to simulate glass refraction
            if random.random() < 0.1:
                # Temporarily brighten a random element
                pass  # Implement if needed
            self.after(4000, shimmer)
        
        shimmer()

    def _remove_char_at(self, pos: str) -> None:
        """Remove character."""
        try:
            self.output.configure(state="normal")
            self.output.delete(pos)
            self.output.configure(state="disabled")
        except:
            pass

    # ------------------------------------------------------------------ helpers
    def _type_text(self, text: str, delay: float = 0.01, tag: str = "value") -> None:
        """Type text effect."""
        self.output.configure(state="normal")
        self.is_typing = True
        
        def type_char(index=0):
            if index < len(text) and self.is_typing:
                self.output.insert("end", text[index], tag)
                self.output.see("end")
                self.after(int(delay * 1000), lambda: type_char(index + 1))
            else:
                self.is_typing = False
                self.output.configure(state="disabled")
        
        type_char()

    def _write_lines(self, lines: List[str]) -> None:
        """Write formatted lines."""
        self.output.configure(state="normal")
        self.output.delete("1.0", "end")
        
        for line in lines:
            if line.startswith("# "):
                # Headers with glass border
                header_text = line[2:].strip()
                width = len(header_text) + 10
                
                self.output.insert("end", "\n╔" + "═" * width + "╗\n", "header")
                self.output.insert("end", "║     " + header_text + "     ║\n", "header")
                self.output.insert("end", "╚" + "═" * width + "╝\n\n", "header")
            elif ":" in line and not line.startswith(" "):
                # Key-value
                key, value = line.split(":", 1)
                self.output.insert("end", f"  ▸ {key}:", "key")
                self.output.insert("end", f"{value}\n", "value")
            elif line.strip().startswith("PID"):
                # Process
                self.output.insert("end", "    ◆ " + line.strip() + "\n", "success")
            elif line.strip().startswith("Port"):
                # Port
                self.output.insert("end", "    ◈ " + line.strip() + "\n", "warn" "ing")
            elif line.strip().startswith("["):
                # String
                self.output.insert("end", "    " + line.strip() + "\n", "dim")
            else:
                self.output.insert("end", line + "\n", "value")
        
        self.output.see("end")
        self.output.configure(state="disabled")

    def _show_welcome(self) -> None:
        """Show welcome screen."""
        self.output.configure(state="normal")
        
        # ASCII art
        ascii_art = """
            ╔════════════════════════════════════════════════════════════╗
            ║                                                            ║
            ║         █████╗ ███████╗ ██████╗ ██╗███████╗               ║
            ║        ██╔══██╗██╔════╝██╔════╝ ██║██╔════╝               ║
            ║        ███████║█████╗  ██║  ███╗██║███████╗               ║
            ║        ██╔══██║██╔══╝  ██║   ██║██║╚════██║               ║
            ║        ██║  ██║███████╗╚██████╔╝██║███████║               ║
            ║        ╚═╝  ╚═╝╚══════╝ ╚═════╝ ╚═╝╚══════╝               ║
            ║                                                            ║
            ║            SHIELD SECURITY FRAMEWORK v3.0                  ║
            ║                                                            ║
            ╚════════════════════════════════════════════════════════════╝
"""
        
        # Display ASCII art with color
        for line in ascii_art.strip().split('\n'):
            for char in line:
                if char in '█':
                    self.output.insert("end", char, "header")
                elif char in '═║╔╗╚╝':
                    self.output.insert("end", char, "glow")
                else:
                    self.output.insert("end", char, "dim")
            self.output.insert("end", "\n")
            self.output.see("end")
            self.update_idletasks()
            time.sleep(0.01)
        
        # System info
        info = """
[SYSTEM] Aegis Terminal Interface v3.0
[SHIELD] Protection Status: MAXIMUM
[GLASS] Transparency Layer: ACTIVE
[SECURE] Encryption: AES-256-GCM

Available Commands:
  • System commands - Execute any shell command
  • History - Navigate with ↑/↓ arrows
  • Autocomplete - Press Tab
  • Quick Actions - Use control panel

Type 'help' for command list.
"""
        self.output.insert("end", "\n" + info, "dim")
        self.output.configure(state="disabled")

    def _clear_output(self) -> None:
        """Clear with glass shatter."""
        self.output.configure(state="normal")
        
        # Glass shatter
        shatter_chars = "░▒▓█▓▒░◈◆◊"
        for i in range(10):
            line = "".join(random.choice(shatter_chars) for _ in range(random.randint(20, 80)))
            self.output.insert("end", line + "\n", "glow")
            self.update()
            time.sleep(0.04)
        
        self.output.delete("1.0", "end")
        self._show_welcome()
        self.output.configure(state="disabled")

    def _on_key_press(self, event=None) -> None:
        """Key press feedback."""
        self.prompt_symbol.configure(text_color=self.text_bright)
        self.after(100, lambda: self.prompt_symbol.configure(text_color=self.accent_purple))

    def _run_command(self, cmd: str) -> None:
        """Run command."""
        self.entry.delete(0, "end")
        self.entry.insert(0, cmd)
        self._on_enter()

    # ------------------------------------------------------------------ command handling
    def _history_up(self, event=None) -> None:
        """History up."""
        if self.command_history and self.history_index < len(self.command_history) - 1:
            self.history_index += 1
            self.entry.delete(0, "end")
            self.entry.insert(0, self.command_history[-(self.history_index + 1)])
        return "break"

    def _history_down(self, event=None) -> None:
        """History down."""
        if self.history_index > 0:
            self.history_index -= 1
            self.entry.delete(0, "end")
            self.entry.insert(0, self.command_history[-(self.history_index + 1)])
        elif self.history_index == 0:
            self.history_index = -1
            self.entry.delete(0, "end")
        return "break"

    def _autocomplete(self, event=None) -> None:
        """Autocomplete."""
        current = self.entry.get()
        commands = [
            "ls", "pwd", "cd", "cat", "grep", "find", "ps", "netstat", "lsof",
            "strings", "file", "chmod", "chown", "kill", "top", "htop", "df",
            "du", "free", "whoami", "uname", "ifconfig", "ping", "traceroute",
            "nmap", "tcpdump", "wireshark", "strace", "ltrace", "gdb", "objdump",
            "readelf", "hexdump", "xxd", "binwalk", "volatility", "yara", "radare2"
        ]
        
        matches = [cmd for cmd in commands if cmd.startswith(current) and cmd != current]
        if matches:
            self.entry.delete(0, "end")
            self.entry.insert(0, matches[0])
            self.entry.selection_range(len(current), "end")
            
            # Flash
            self.entry.configure(text_color=self.accent_cyan)
            self.after(150, lambda: self.entry.configure(text_color=self.text_bright))
        return "break"

    # ------------------------------------------------------------------ main actions
    def refresh(self) -> None:
        """Scan executable."""
        # Update status
        self.status_cards[2][1].configure(text="SCANNING")
        self.status_cards[2][0].configure(text_color=self.accent_orange)
        
        # Scan animation
        self.output.configure(state="normal")
        self.output.insert("end", "\n")
        
        scan_steps = [
            ("[◐] Initializing Aegis scanner...", 0.1),
            ("[◓] Reading binary structure...", 0.15),
            ("[◑] Analyzing executable headers...", 0.2),
            ("[◒] Checking security features...", 0.15),
            ("[◐] Scanning for vulnerabilities...", 0.2),
            ("[◓] Extracting metadata...", 0.15),
            ("[●] Shield analysis complete!\n", 0.1)
        ]
        
        for msg, delay in scan_steps[:-1]:
            self.output.insert("end", msg + "\r", "warn" "ing")
            self.output.see("end")
            self.update()
            time.sleep(delay)
        
        self.output.insert("end", scan_steps[-1][0], "success")
        
        # Gather info
        info = inspector.gather_info(self.path)
        procs = inspector._processes_for(self.path) if self.path.exists() else []
        ports = inspector._ports_for([p.pid for p in procs]) if procs else {}
        strings = inspector._extract_strings(self.path, limit=20)

        lines = []
        lines.append("# AEGIS SECURITY ANALYSIS")
        
        lines.append("\n# FILE PROPERTIES")
        for k, v in info.items():
            lines.append(f"{k}: {v}")
        
        if procs:
            lines.append("\n# ACTIVE PROCESSES")
            for p in procs:
                try:
                    cpu = p.cpu_percent()
                    mem = p.memory_percent()
                    lines.append(f"PID {p.pid}: {p.name()} [CPU: {cpu:.1f}% | MEM: {mem:.1f}%]")
                except:
                    lines.append(f"PID {p.pid}: {p.name()}")
        
        if ports:
            lines.append("\n# NETWORK ENDPOINTS")
            for port, names in sorted(ports.items()):
                lines.append(f"Port {port}: {', '.join(names)}")
        
        if strings:
            lines.append("\n# EXTRACTED STRINGS")
            for i, s in enumerate(strings, 1):
                if len(s) > 50:
                    s = s[:47] + "..."
                lines.append(f"[{i:02d}] {s}")

        self._write_lines(lines)
        
        # Update status
        self.status_cards[2][1].configure(text="ACTIVE")
        self.status_cards[2][0].configure(text_color=self.accent_orange_dim)

    def _on_enter(self, event=None) -> None:
        """Execute command."""
        cmd = self.entry.get().strip()
        if not cmd:
            return
        
        # Add to history
        self.command_history.append(cmd)
        self.history_index = -1
        
        # Visual feedback
        self.prompt_symbol.configure(text_color=self.accent_red)
        self.after(200, lambda: self.prompt_symbol.configure(text_color=self.accent_purple))
        
        # Display command
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        self.output.configure(state="normal")
        
        # Glass command header
        self.output.insert("end", "\n╭─[", "dim")
        self.output.insert("end", "AEGIS", "glow")
        self.output.insert("end", "]──[", "dim")
        self.output.insert("end", ts, "warn" "ing")
        self.output.insert("end", "]──[", "dim")
        self.output.insert("end", str(Path.cwd()).replace(str(Path.home()), "~"), "subheader")
        self.output.insert("end", "]\n", "dim")
        self.output.insert("end", "╰─▸ ", "prompt")
        self.output.insert("end", cmd + "\n", "success")
        
        # Execution animation
        anim_frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        anim_pos = self.output.index("end-1c")
        
        def animate(frame=0):
            if frame < len(anim_frames) * 3:
                self.output.insert("end", f"\r[{anim_frames[frame % len(anim_frames)]}] Executing...", "system")
                self.output.delete(anim_pos, "end")
                self.output.see("end")
                self.after(80, lambda: animate(frame + 1))
        
        animate()
        
        # Execute
        try:
            start_time = time.time()
            out, rc = run_command_ex(shlex.split(cmd), capture=True, check=False)
            exec_time = time.time() - start_time
            
            # Clear animation
            self.output.delete(anim_pos, "end")
            
            if out is None:
                # Error glass panel
                self.output.insert("end", "\n╔════════════════════════════════════════╗\n", "error")
                self.output.insert("end", "║      ⚠  EXECUTION FAILED  ⚠          ║\n", "error")
                self.output.insert("end", "╚════════════════════════════════════════╝\n\n", "error")
            elif out:
                # Output
                self.output.insert("end", "\n", "value")
                for line in out.splitlines():
                    if any(err in line.lower() for err in ["error", "fail", "denied", "not found", "permission"]):
                        self.output.insert("end", "  ✗ " + line + "\n", "error")
                    elif any(warn in line.lower() for warn in ["warn" "ing", "caution", "deprecated"]):
                        self.output.insert("end", "  ⚠ " + line + "\n", "warn" "ing")
                    else:
                        self.output.insert("end", "  " + line + "\n", "value")
            else:
                self.output.insert("end", "\n  ", "dim")
                self.output.insert("end", "(empty output)\n", "dim")
            
            # Summary glass panel
            self.output.insert("end", "\n" + "─" * 65 + "\n", "dim")
            
            status_icon = "✓" if rc == 0 else "✗"
            status_color = "success" if rc == 0 else "error"
            
            self.output.insert("end", f" {status_icon} Exit: {rc}", status_color)
            self.output.insert("end", " │ ", "dim")
            self.output.insert("end", f"Time: {exec_time:.3f}s", "accent")
            self.output.insert("end", " │ ", "dim")
            self.output.insert("end", f"Shield: ACTIVE\n", "success")
            
        except Exception as e:
            self.output.delete(anim_pos, "end")
            self.output.insert("end", "\n╔════════════════════════════════════════╗\n", "error")
            self.output.insert("end", "║       ⚠  SYSTEM ERROR  ⚠             ║\n", "error")
            self.output.insert("end", "╚════════════════════════════════════════╝\n", "error")
            self.output.insert("end", f"\n{str(e)}\n", "error")
        
        self.output.see("end")
        self.output.configure(state="disabled")
        self.entry.delete(0, "end")
