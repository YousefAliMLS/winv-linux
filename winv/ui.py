"""The popup window: clipboard history + emoji picker (GTK4 / libadwaita).

Runs as a resident, single-instance GtkApplication on the *native* Wayland
backend so it receives proper keyboard focus. ``winv toggle`` reaches the
running instance over D-Bus (org.gtk.Actions), which is near-instant.
"""
from __future__ import annotations

import logging
import sys
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk  # noqa: E402

from . import APP_ID, APP_NAME, config  # noqa: E402
from . import emoji as emoji_mod  # noqa: E402
from .paste import Paster  # noqa: E402
from .storage import Item, Store  # noqa: E402

log = logging.getLogger("winv.ui")

# Marks clipboard content set by the emoji picker so the watcher won't record it.
TRANSIENT_MIME = "application/x-winv-transient"
PREVIEW_CHARS = 400

CSS = """
.winv-list { background: transparent; }
.winv-list > row { border-radius: 10px; margin: 2px 6px; padding: 6px 4px 6px 10px; }
.winv-list > row:selected { background-color: alpha(@accent_bg_color, 0.18); }
.winv-meta { font-size: 0.8em; }
.winv-thumb { border-radius: 6px; }
.emoji-cell { font-size: 26px; min-width: 42px; min-height: 42px; }
gridview.emoji-grid > child { border-radius: 8px; padding: 0; }
gridview.emoji-grid > child:selected { background-color: alpha(@accent_bg_color, 0.25); }
.cat-button { font-size: 17px; padding: 2px 0; min-width: 30px; min-height: 30px; }
.emoji-status { font-size: 0.85em; padding: 4px 10px 6px 10px; }
"""


def time_ago(ts: float) -> str:
    d = max(0.0, time.time() - ts)
    if d < 60:
        return "Just now"
    if d < 3600:
        return f"{int(d // 60)} min ago"
    if d < 86400:
        return f"{int(d // 3600)} h ago"
    return f"{int(d // 86400)} d ago"


class EmojiObject(GObject.Object):
    __gtype_name__ = "WinVEmojiObject"

    def __init__(self, emoji: emoji_mod.Emoji) -> None:
        super().__init__()
        self.emoji = emoji


class HistoryRow(Gtk.ListBoxRow):
    def __init__(self, win: "MainWindow", item: Item) -> None:
        super().__init__()
        self.item = item
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, hexpand=True)

        if item.kind == "text":
            preview = item.content[:PREVIEW_CHARS].replace("\t", "    ").strip("\n")
            label = Gtk.Label(
                label=preview, xalign=0, wrap=True, wrap_mode=2,  # Pango.WrapMode.WORD_CHAR
                lines=3, ellipsize=3, max_width_chars=40,  # Pango.EllipsizeMode.END
            )
            body.append(label)
            meta = f"{len(item.content):,} characters" if len(item.content) > PREVIEW_CHARS else ""
        else:
            picture = Gtk.Picture(
                can_shrink=True, content_fit=Gtk.ContentFit.CONTAIN, height_request=110,
                halign=Gtk.Align.START,
            )
            picture.add_css_class("winv-thumb")
            texture = win.thumbnail(item)
            if texture is not None:
                picture.set_paintable(texture)
            body.append(picture)
            meta = f"Image · {item.width}×{item.height}"

        parts = (["Pinned"] if item.pinned else []) + ([meta] if meta else []) + [time_ago(item.used)]
        meta_label = Gtk.Label(label=" · ".join(parts), xalign=0)
        meta_label.add_css_class("dim-label")
        meta_label.add_css_class("winv-meta")
        body.append(meta_label)
        box.append(body)

        buttons = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.START)
        pin = Gtk.ToggleButton(icon_name="view-pin-symbolic", active=item.pinned,
                               tooltip_text="Unpin" if item.pinned else "Pin (kept when clearing)")
        pin.add_css_class("flat")
        pin.add_css_class("circular")
        pin.connect("toggled", lambda b: win.set_pinned(item, b.get_active()))
        delete = Gtk.Button(icon_name="user-trash-symbolic", tooltip_text="Delete")
        delete.add_css_class("flat")
        delete.add_css_class("circular")
        delete.connect("clicked", lambda _b: win.delete_item(item))
        buttons.append(pin)
        buttons.append(delete)
        box.append(buttons)
        self.set_child(box)

    def matches(self, terms: list[str]) -> bool:
        if not terms:
            return True
        hay = self.item.content.lower() if self.item.kind == "text" else "image picture screenshot png"
        return all(t in hay for t in terms)


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app: "WinVApp") -> None:
        super().__init__(application=app, title=APP_NAME)
        self.app = app
        self.set_default_size(400, 560)
        self.set_hide_on_close(True)
        self._thumb_cache: dict[str, Gdk.Texture] = {}
        self._signature: tuple | None = None
        self._poll_id = 0
        self._was_active = False

        self.toasts = Adw.ToastOverlay()
        toolbar = Adw.ToolbarView()
        self.toasts.set_child(toolbar)
        self.set_content(self.toasts)

        # Header with tab switcher
        self.stack = Adw.ViewStack()
        header = Adw.HeaderBar(decoration_layout=":close")
        header.set_title_widget(Adw.ViewSwitcher(stack=self.stack, policy=Adw.ViewSwitcherPolicy.WIDE))
        toolbar.add_top_bar(header)

        # Search bar shared by both tabs
        self.search = Gtk.SearchEntry(hexpand=True, placeholder_text="Search clipboard…")
        self.search.set_key_capture_widget(self)
        self.search.connect("search-changed", self._on_search_changed)
        self.search.connect("activate", lambda _e: self.activate_selected(paste=True))
        self.search.connect("stop-search", lambda _e: self.hide_popup())
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_search_key)
        self.search.add_controller(keys)
        search_box = Gtk.Box(margin_start=10, margin_end=10, margin_bottom=6)
        search_box.append(self.search)
        toolbar.add_top_bar(search_box)

        toolbar.set_content(self.stack)
        self._build_clipboard_page()
        self._build_emoji_page()
        self.stack.connect("notify::visible-child-name", self._on_page_changed)

        win_keys = Gtk.EventControllerKey()
        win_keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        win_keys.connect("key-pressed", self._on_window_key)
        self.add_controller(win_keys)
        self.connect("notify::is-active", self._on_active_changed)

    # ------------------------------------------------------------ clipboard tab
    def _build_clipboard_page(self) -> None:
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        bar = Gtk.Box(margin_start=14, margin_end=8, margin_bottom=2)
        title = Gtk.Label(label="Clipboard history", xalign=0, hexpand=True)
        title.add_css_class("heading")
        clear = Gtk.Button(label="Clear all", tooltip_text="Delete all unpinned items")
        clear.add_css_class("flat")
        clear.connect("clicked", lambda _b: self.clear_history())
        bar.append(title)
        bar.append(clear)
        page.append(bar)

        self.listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE, activate_on_single_click=True)
        self.listbox.add_css_class("winv-list")
        self.listbox.set_filter_func(self._filter_row)
        self.listbox.connect("row-activated", lambda _lb, row: self.app.commit_item(row.item, paste=True))
        self.placeholder = Adw.StatusPage(icon_name="edit-paste-symbolic", title="Nothing copied yet",
                                          description="Copy some text or an image and it will show up here.")
        self.placeholder.add_css_class("compact")
        self.listbox.set_placeholder(self.placeholder)

        self.list_scroll = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.list_scroll.set_child(self.listbox)
        page.append(self.list_scroll)
        self.stack.add_titled_with_icon(page, "clipboard", "Clipboard", "edit-paste-symbolic")

    def thumbnail(self, item: Item) -> Gdk.Texture | None:
        tex = self._thumb_cache.get(item.hash)
        if tex is None:
            path = item.thumb_path if item.thumb_path.exists() else item.image_path
            try:
                tex = Gdk.Texture.new_from_filename(str(path))
            except GLib.Error as exc:
                log.warning("Missing image for entry %s: %s", item.id, exc.message)
                return None
            self._thumb_cache[item.hash] = tex
        return tex

    def refresh_history(self, force: bool = False) -> None:
        try:
            items = self.app.store.items()
        except Exception:  # noqa: BLE001
            log.exception("Could not read history")
            items = []
        signature = tuple((i.id, i.used, i.pinned) for i in items)
        if not force and signature == self._signature:
            return
        self._signature = signature
        selected = self.listbox.get_selected_row()
        selected_id = selected.item.id if selected else None

        self.listbox.remove_all()
        for item in items:
            self.listbox.append(HistoryRow(self, item))
        live = {i.hash for i in items}
        self._thumb_cache = {h: t for h, t in self._thumb_cache.items() if h in live}
        self._update_placeholder()
        self._select_visible(prefer_id=selected_id)

    def _filter_row(self, row: HistoryRow) -> bool:
        return row.matches(self.search.get_text().lower().split())

    def _visible_rows(self) -> list[HistoryRow]:
        rows, i = [], 0
        while (row := self.listbox.get_row_at_index(i)) is not None:
            if row.get_child_visible():
                rows.append(row)
            i += 1
        return rows

    def _select_visible(self, prefer_id: int | None = None) -> None:
        rows = self._visible_rows()
        target = next((r for r in rows if r.item.id == prefer_id), rows[0] if rows else None)
        self.listbox.select_row(target)
        if target is not None:
            GLib.idle_add(self._scroll_to_row, target)

    def _move_selection(self, delta: int) -> None:
        rows = self._visible_rows()
        if not rows:
            return
        current = self.listbox.get_selected_row()
        idx = rows.index(current) if current in rows else -1
        target = rows[max(0, min(len(rows) - 1, idx + delta))]
        self.listbox.select_row(target)
        self._scroll_to_row(target)

    def _scroll_to_row(self, row: Gtk.ListBoxRow) -> bool:
        ok, rect = row.compute_bounds(self.listbox)
        if ok:
            adj = self.list_scroll.get_vadjustment()
            top, bottom = rect.get_y(), rect.get_y() + rect.get_height()
            if top < adj.get_value():
                adj.set_value(top)
            elif bottom > adj.get_value() + adj.get_page_size():
                adj.set_value(bottom - adj.get_page_size())
        return GLib.SOURCE_REMOVE

    def _update_placeholder(self) -> None:
        if self.search.get_text():
            self.placeholder.set_title("No matches")
            self.placeholder.set_description("Try a different search.")
        else:
            self.placeholder.set_title("Nothing copied yet")
            self.placeholder.set_description("Copy some text or an image and it will show up here.")

    def set_pinned(self, item: Item, pinned: bool) -> None:
        self.app.store.set_pinned(item.id, pinned)
        GLib.idle_add(self.refresh_history)

    def delete_item(self, item: Item) -> None:
        self.app.store.delete(item.id)
        GLib.idle_add(self.refresh_history)

    def clear_history(self) -> None:
        self.app.store.clear(keep_pinned=True)
        self.refresh_history(force=True)
        self.toasts.add_toast(Adw.Toast(title="History cleared (pinned items kept)", timeout=2))

    # ---------------------------------------------------------------- emoji tab
    def _build_emoji_page(self) -> None:
        all_emoji = emoji_mod.load_emoji()
        self._emoji_by_char = {e.char: EmojiObject(e) for e in all_emoji}
        self.emoji_store = Gio.ListStore(item_type=EmojiObject)
        self.emoji_store.splice(0, 0, list(self._emoji_by_char.values()))
        self.recent_store = Gio.ListStore(item_type=EmojiObject)
        self.category = "Smileys & Emotion"

        self.emoji_filter = Gtk.CustomFilter.new(self._emoji_filter_func)
        self.emoji_filtered = Gtk.FilterListModel(model=self.emoji_store, filter=self.emoji_filter)
        self.emoji_selection = Gtk.SingleSelection(model=self.emoji_filtered)
        self.emoji_selection.connect("notify::selected-item", self._on_emoji_selected)

        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", lambda _f, li: li.set_child(self._make_emoji_cell()))
        factory.connect("bind", self._bind_emoji_cell)

        self.grid = Gtk.GridView(model=self.emoji_selection, factory=factory,
                                 min_columns=8, max_columns=8, single_click_activate=True)
        self.grid.add_css_class("emoji-grid")
        self.grid.connect("activate", lambda _g, pos: self._activate_emoji_at(pos))

        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        cats = Gtk.Box(homogeneous=True, margin_start=6, margin_end=6, margin_bottom=4)
        self.cat_buttons: dict[str, Gtk.ToggleButton] = {}
        group = None
        for name, icon in emoji_mod.CATEGORIES:
            btn = Gtk.ToggleButton(label=icon, tooltip_text=name)
            btn.add_css_class("flat")
            btn.add_css_class("cat-button")
            if group is None:
                group = btn
            else:
                btn.set_group(group)
            btn.connect("toggled", self._on_category_toggled, name)
            cats.append(btn)
            self.cat_buttons[name] = btn
        page.append(cats)

        scroll = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        scroll.set_child(self.grid)
        page.append(scroll)
        self.emoji_status = Gtk.Label(xalign=0, ellipsize=3)
        self.emoji_status.add_css_class("dim-label")
        self.emoji_status.add_css_class("emoji-status")
        page.append(self.emoji_status)
        self.stack.add_titled_with_icon(page, "emoji", "Emoji", "face-smile-symbolic")

    @staticmethod
    def _make_emoji_cell() -> Gtk.Label:
        label = Gtk.Label()
        label.add_css_class("emoji-cell")
        return label

    @staticmethod
    def _bind_emoji_cell(_factory, list_item: Gtk.ListItem) -> None:
        obj: EmojiObject = list_item.get_item()
        label: Gtk.Label = list_item.get_child()
        label.set_text(obj.emoji.char)
        label.set_tooltip_text(obj.emoji.name)

    def _emoji_filter_func(self, obj: EmojiObject) -> bool:
        query = self.search.get_text().strip()
        if query:
            return emoji_mod.matches(obj.emoji, query)
        return obj.emoji.group == self.category

    def _on_category_toggled(self, button: Gtk.ToggleButton, name: str) -> None:
        if not button.get_active():
            return
        self.category = name
        if self.search.get_text():
            self.search.set_text("")  # triggers _update_emoji_view via search-changed
        else:
            self._update_emoji_view()

    def _update_emoji_view(self) -> None:
        query = self.search.get_text().strip()
        if not query and self.category == "Recent":
            self.emoji_selection.set_model(self.recent_store)
        else:
            if self.emoji_selection.get_model() is not self.emoji_filtered:
                self.emoji_selection.set_model(self.emoji_filtered)
            self.emoji_filter.changed(Gtk.FilterChange.DIFFERENT)
        if self.emoji_selection.get_n_items():
            self.emoji_selection.set_selected(0)
            self.grid.scroll_to(0, Gtk.ListScrollFlags.NONE, None)
        self._on_emoji_selected()

    def _on_emoji_selected(self, *_args) -> None:
        obj = self.emoji_selection.get_selected_item()
        if obj is not None:
            self.emoji_status.set_text(f"{obj.emoji.char}  {obj.emoji.name}")
        elif self.category == "Recent" and not self.search.get_text():
            self.emoji_status.set_text("Emoji you use will appear here")
        else:
            self.emoji_status.set_text("No emoji found")

    def _reload_recent(self) -> None:
        objs = [self._emoji_by_char[c] for c in emoji_mod.load_recent() if c in self._emoji_by_char]
        self.recent_store.splice(0, self.recent_store.get_n_items(), objs)

    def _activate_emoji_at(self, position: int, paste: bool = True) -> None:
        obj = self.emoji_selection.get_model().get_item(position)
        if obj is None:
            return
        emoji_mod.push_recent(obj.emoji.char)
        self.app.commit_text(obj.emoji.char, paste=paste, transient=True)

    # ----------------------------------------------------------------- behaviour
    def show_popup(self, page: str) -> None:
        self.app.cfg = config.load_config()
        self.stack.set_visible_child_name(page)
        self.search.set_text("")
        self._reload_recent()
        start_cat = "Recent" if self.recent_store.get_n_items() else "Smileys & Emotion"
        self.cat_buttons[start_cat].set_active(True)
        self.category = start_cat
        self.refresh_history(force=True)
        self._update_emoji_view()
        self._on_page_changed()
        self.present()
        self.search.grab_focus()
        if not self._poll_id:
            self._poll_id = GLib.timeout_add(800, self._poll)

    def hide_popup(self) -> None:
        self._was_active = False
        self.set_visible(False)
        if self._poll_id:
            GLib.source_remove(self._poll_id)
            self._poll_id = 0

    def _poll(self) -> bool:
        if not self.get_visible():
            self._poll_id = 0
            return GLib.SOURCE_REMOVE
        self.refresh_history()
        return GLib.SOURCE_CONTINUE

    def _on_active_changed(self, *_args) -> None:
        log.debug("window active=%s visible=%s", self.is_active(), self.get_visible())
        if self.is_active():
            self._was_active = True
        elif self._was_active and self.get_visible() and self.app.cfg.hide_on_focus_loss:
            self.hide_popup()

    def _on_page_changed(self, *_args) -> None:
        page = self.stack.get_visible_child_name()
        self.search.set_placeholder_text("Search clipboard…" if page == "clipboard" else "Search emoji…")
        self._on_search_changed(self.search)

    def _on_search_changed(self, _entry) -> None:
        if self.stack.get_visible_child_name() == "clipboard":
            self.listbox.invalidate_filter()
            self._update_placeholder()
            self._select_visible()
        else:
            self._update_emoji_view()

    def activate_selected(self, paste: bool) -> None:
        if self.stack.get_visible_child_name() == "clipboard":
            row = self.listbox.get_selected_row()
            if row is None or not row.get_child_visible():
                rows = self._visible_rows()
                row = rows[0] if rows else None
            if row is not None:
                self.app.commit_item(row.item, paste=paste)
        else:
            pos = self.emoji_selection.get_selected()
            if pos == Gtk.INVALID_LIST_POSITION:
                pos = 0
            if self.emoji_selection.get_n_items():
                self._activate_emoji_at(pos, paste=paste)

    def _on_search_key(self, _ctrl, keyval: int, _code: int, state: Gdk.ModifierType) -> bool:
        on_clipboard = self.stack.get_visible_child_name() == "clipboard"
        if keyval in (Gdk.KEY_Down, Gdk.KEY_Up) and on_clipboard:
            self._move_selection(1 if keyval == Gdk.KEY_Down else -1)
            return True
        if keyval == Gdk.KEY_Down and not on_clipboard and self.emoji_selection.get_n_items():
            pos = max(0, self.emoji_selection.get_selected())
            self.grid.scroll_to(pos, Gtk.ListScrollFlags.FOCUS | Gtk.ListScrollFlags.SELECT, None)
            return True
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter) and state & Gdk.ModifierType.SHIFT_MASK:
            self.activate_selected(paste=False)  # Shift+Enter: copy only
            return True
        return False

    def _on_window_key(self, _ctrl, keyval: int, _code: int, state: Gdk.ModifierType) -> bool:
        ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)
        alt = bool(state & Gdk.ModifierType.ALT_MASK)
        if keyval == Gdk.KEY_Escape:
            self.hide_popup()
            return True
        if (ctrl and keyval in (Gdk.KEY_Tab, Gdk.KEY_ISO_Left_Tab)) or (alt and keyval in (Gdk.KEY_1, Gdk.KEY_2)):
            if alt:
                name = "clipboard" if keyval == Gdk.KEY_1 else "emoji"
            else:
                name = "emoji" if self.stack.get_visible_child_name() == "clipboard" else "clipboard"
            self.stack.set_visible_child_name(name)
            self.search.grab_focus()
            return True
        if self.stack.get_visible_child_name() == "clipboard":
            row = self.listbox.get_selected_row()
            if row is not None and ctrl and keyval in (Gdk.KEY_p, Gdk.KEY_P):
                self.set_pinned(row.item, not row.item.pinned)
                return True
            if row is not None and keyval == Gdk.KEY_Delete and (ctrl or not self.search.get_text()):
                self.delete_item(row.item)
                return True
        return False


class WinVApp(Adw.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.add_main_option("hidden", 0, GLib.OptionFlags.NONE, GLib.OptionArg.NONE,
                             "Start in the background without showing the window", None)
        self.add_main_option("toggle", 0, GLib.OptionFlags.NONE, GLib.OptionArg.NONE,
                             "Show the clipboard popup, or hide it if visible", None)
        self.add_main_option("emoji", 0, GLib.OptionFlags.NONE, GLib.OptionArg.NONE,
                             "Show the popup on the emoji tab", None)
        self.win: MainWindow | None = None
        self._warned_paste = False

    def do_startup(self) -> None:
        Adw.Application.do_startup(self)
        self.hold()  # stay resident while hidden
        self.cfg = config.load_config()
        self.store = Store()
        self.paster = Paster(self.cfg.paste_backend, self.cfg.paste_keys)

        css = Gtk.CssProvider()
        css.load_from_string(CSS)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        for name, callback in (
            ("toggle", lambda *_: self.toggle("clipboard")),
            ("show-clipboard", lambda *_: self.show_page("clipboard")),
            ("show-emoji", lambda *_: self.toggle("emoji")),
            ("quit", lambda *_: self.quit()),
        ):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", callback)
            self.add_action(action)
        self.win = MainWindow(self)

    def do_activate(self) -> None:
        self.show_page("clipboard")

    def do_command_line(self, command_line: Gio.ApplicationCommandLine) -> int:
        opts = command_line.get_options_dict().end().unpack()
        if opts.get("hidden"):
            return 0
        if opts.get("emoji"):
            self.toggle("emoji")
        elif opts.get("toggle"):
            self.toggle("clipboard")
        else:
            self.show_page("clipboard")
        return 0

    def show_page(self, page: str) -> None:
        self.win.show_popup(page)

    def toggle(self, page: str) -> None:
        if self.win.get_visible() and self.win.stack.get_visible_child_name() == page:
            self.win.hide_popup()
        else:
            self.show_page(page)

    # ------------------------------------------------------------ clipboard I/O
    def _clipboard(self) -> Gdk.Clipboard:
        return self.win.get_display().get_clipboard()

    def commit_item(self, item: Item, paste: bool) -> None:
        if item.kind == "text":
            self.commit_text(item.content, paste=paste)
        else:
            try:
                texture = Gdk.Texture.new_from_filename(str(item.image_path))
            except GLib.Error as exc:
                self.win.toasts.add_toast(Adw.Toast(title=f"Image file missing: {exc.message}"))
                return
            # The GValue must be typed GdkTexture (not the GdkMemoryTexture subtype)
            # or GTK won't find its image/png, image/jpeg, ... serializers.
            value = GObject.Value(Gdk.Texture, texture)
            self._clipboard().set_content(Gdk.ContentProvider.new_for_value(value))
            self._finish(paste)
        try:
            self.store.touch(item.id)
        except Exception:  # noqa: BLE001
            log.exception("Could not update usage time")

    def commit_text(self, text: str, paste: bool, transient: bool = False) -> None:
        provider = Gdk.ContentProvider.new_for_value(text)
        if transient:
            marker = Gdk.ContentProvider.new_for_bytes(TRANSIENT_MIME, GLib.Bytes.new(b"1"))
            provider = Gdk.ContentProvider.new_union([provider, marker])
        self._clipboard().set_content(provider)
        self._finish(paste)

    def _finish(self, paste: bool) -> None:
        self.win.hide_popup()
        if not (paste and self.cfg.auto_paste):
            return
        if self.paster.available:
            GLib.timeout_add(max(0, self.cfg.paste_delay_ms), self._send_paste)
        elif not self._warned_paste:
            self._warned_paste = True
            note = Gio.Notification.new("Copied — press Ctrl+V to paste")
            note.set_body(f"Auto-paste is unavailable: {self.paster.error}")
            self.send_notification("winv-paste", note)

    def _send_paste(self) -> bool:
        self.paster.paste()
        return GLib.SOURCE_REMOVE


def main(argv: list[str] | None = None) -> int:
    app = WinVApp()
    return app.run(argv if argv is not None else sys.argv)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sys.exit(main())
