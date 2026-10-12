"""
PySide6 user interface for the EXP tracker: a compact overlay sized to sit in the empty strip beside the
game's status bar (two chips, a resources placeholder), a click-to-open breakdown, and inline settings.
"""
from __future__ import annotations

import sys
import time
import traceback
from typing import Callable, List, NamedTuple, Optional, Sequence, Tuple

import numpy as np
from PySide6.QtCore import QEvent, QPointF, QRect, QRectF, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (QColor, QDesktopServices, QFont, QFontMetrics, QGuiApplication, QImage, QLinearGradient,
                           QPainter, QPainterPath, QPalette, QPen, QPixmap)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (QApplication, QComboBox, QDialog, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QPushButton, QSizePolicy, QSlider, QSpinBox, QStackedWidget,
                               QVBoxLayout, QWidget)

import exp_core as ec
import exp_items as ec_items

# --------------------------------------------------------------------------- #
# Theme
# --------------------------------------------------------------------------- #

C_BG = QColor(23, 23, 23)         # neutral-900
C_BORDER = QColor(38, 38, 38)     # neutral-800
C_TEXT = QColor(255, 255, 255)
C_TEXT200 = QColor(229, 229, 229)  # neutral-200
C_DIM = QColor(163, 163, 163)     # neutral-400
C_FAINT = QColor(115, 115, 115)   # neutral-500
C_HALF = QColor(255, 255, 255, 128)   # white/50
C_EXP = QColor(147, 197, 253)     # blue-300
C_MESO = QColor(240, 171, 252)    # fuchsia-300
C_OK = QColor(34, 197, 94)        # green-500

FONT_FAMILIES = ["Segoe UI", "Inter", "Helvetica Neue", "Arial", "DejaVu Sans"]
MONO_FAMILIES = ["Consolas", "Cascadia Mono", "DejaVu Sans Mono", "Courier New"]



def ui_font(px: float, weight=QFont.Weight.Normal, mono: bool = False) -> QFont:
    f = QFont()
    f.setFamilies(MONO_FAMILIES if mono else FONT_FAMILIES)
    f.setPixelSize(int(round(px)))
    f.setWeight(weight)
    return f


def rgba(c: QColor, a: int) -> QColor:
    out = QColor(c)
    out.setAlpha(max(0, min(255, a)))
    return out


def apply_dark_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    pal = QPalette()
    roles = {
        QPalette.ColorRole.Window: QColor(23, 23, 23), QPalette.ColorRole.WindowText: C_TEXT,
        QPalette.ColorRole.Base: QColor(10, 10, 10), QPalette.ColorRole.AlternateBase: QColor(23, 23, 23),
        QPalette.ColorRole.Text: C_TEXT, QPalette.ColorRole.Button: QColor(38, 38, 38),
        QPalette.ColorRole.ButtonText: C_TEXT, QPalette.ColorRole.ToolTipBase: QColor(38, 38, 38),
        QPalette.ColorRole.ToolTipText: C_TEXT, QPalette.ColorRole.Highlight: QColor(37, 99, 235),
        QPalette.ColorRole.HighlightedText: QColor(255, 255, 255), QPalette.ColorRole.PlaceholderText: C_DIM,
    }
    for r, c in roles.items():
        pal.setColor(r, c)
    for r in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText, QPalette.ColorRole.WindowText):
        pal.setColor(QPalette.ColorGroup.Disabled, r, QColor(110, 118, 134))
    app.setPalette(pal)
    app.setFont(ui_font(13))


def np_to_qimage(rgb: np.ndarray) -> QImage:
    h, w = rgb.shape[:2]
    arr = np.ascontiguousarray(rgb)
    return QImage(arr.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()


# --------------------------------------------------------------------------- #
# Small widgets
# --------------------------------------------------------------------------- #


# Tabler icons (MIT), 24x24. "currentColor" is replaced with the colour a button wants.
_STROKE = 'fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"'
ICON_SVG = {
    "reset": f'<g {_STROKE}><path d="M19.933 13.041a8 8 0 1 1-9.925-8.788c3.899-1 7.935 1.007 9.425 4.747"/>'
             '<path d="M20 4v5h-5"/></g>',
    "pause": '<path fill="currentColor" d="M9 4H7a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h2a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2m8 '
             '0h-2a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h2a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2"/>',
    "play": '<path fill="currentColor" d="M6 4v16a1 1 0 0 0 1.524.852l13-8a1 1 0 0 0 0-1.704l-13-8A1 1 0 0 0 6 4"/>',
    "settings": f'<path {_STROKE} d="M12 6a2 2 0 1 0 4 0a2 2 0 1 0-4 0M4 6h8m4 0h4M6 12a2 2 0 1 0 4 0a2 2 0 1 0-4 0m-2 '
                '0h2m4 0h10m-5 6a2 2 0 1 0 4 0a2 2 0 1 0-4 0M4 18h11m4 0h1"/>',
    "close": '<path fill="currentColor" d="M6.707 5.293L12 10.585l5.293-5.292a1 1 0 0 1 1.414 1.414L13.415 12l5.292 '
             '5.293a1 1 0 0 1-1.414 1.414L12 13.415l-5.293 5.292a1 1 0 1 1-1.414-1.414L10.585 12L5.293 6.707a1 1 0 0 1 '
             '1.414-1.414"/>',
    "back": f'<path {_STROKE} d="M15 6l-6 6l6 6"/>',
    "chart-line": '<path fill="currentColor" d="M14.06 9.94L12 9l2.06-.94L15 6l.94 2.06L18 9l-2.06.94L15 12zM4 14l.94-2.06L7 11l-2.06-.94L4 8l-.94 2.06L1 11l2.06.94zm4.5-5l1.09-2.41L12 5.5L9.59 4.41L8.5 2L7.41 4.41L5 5.5l2.41 1.09zm-4 11.5l6-6.01l4 4L23 8.93l-1.41-1.41l-7.09 7.97l-4-4L3 19z"/>',
    "coin": '<path fill="currentColor" d="M12.005 22.003c-5.523 0-10-4.477-10-10s4.477-10 10-10s10 4.477 10 10s-4.477 10-10 10m0-2a8 8 0 1 0 0-16a8 8 0 0 0 0 16m-3.5-6h5.5a.5.5 0 1 0 0-1h-4a2.5 2.5 0 1 1 0-5h1v-2h2v2h2.5v2h-5.5a.5.5 0 0 0 0 1h4a2.5 2.5 0 0 1 0 5h-1v2h-2v-2h-2.5z"/>',
    "trending-up": f'<path {_STROKE} d="M3 17l6-6l4 4l8-8M14 7h7v7"/>',
    "trending-down": f'<path {_STROKE} d="M3 7l6 6l4-4l8 8M21 10v7h-7"/>',
    "alert-triangle": f'<path {_STROKE} d="M12 9v4m-1.637-9.409L2.257 17.125a1.914 1.914 0 0 0 1.636 2.871h16.214a1.914 '
                      '1.914 0 0 0 1.636-2.87L13.637 3.59a1.914 1.914 0 0 0-3.274 0M12 16h.01"/>',
    "alert-octagon": f'<path {_STROKE} d="m12.802 2.165l5.575 2.389c.48.206.863.589 1.07 1.07l2.388 5.574c.22.512.22 '
                     '1.092 0 1.604l-2.389 5.575c-.206.48-.589.863-1.07 1.07l-5.574 2.388c-.512.22-1.092.22-1.604 '
                     '0l-5.575-2.389a2.04 2.04 0 0 1-1.07-1.07l-2.388-5.574a2.04 2.04 0 0 1 0-1.604l2.389-5.575c.206-.48.589'
                     '-.863 1.07-1.07l5.574-2.388a2.04 2.04 0 0 1 1.604 0M12 8v4m0 4h.01"/>',
}
# kind: (icon colour, colour on hover, background on hover)
_N400, _WHITE = QColor(163, 163, 163), QColor(255, 255, 255)
_HOVER_BG = QColor(38, 38, 38, 178)
ICON_STYLE = {
    "reset": (_N400, _WHITE, _HOVER_BG),
    "settings": (_N400, _WHITE, _HOVER_BG),
    "back": (_N400, _WHITE, _HOVER_BG),
    "play": (_N400, _WHITE, _HOVER_BG),
    "pause": (_N400, _WHITE, _HOVER_BG),
    "close": (_N400, QColor(244, 63, 94), QColor(159, 18, 57, 51)),
}
_RENDERERS: dict = {}


def svg_renderer(kind: str, color: QColor) -> QSvgRenderer:
    """Cached renderer for an icon in one colour (QSvgRenderer wants a literal colour, not currentColor)."""
    key = (kind, color.name(QColor.NameFormat.HexArgb))
    r = _RENDERERS.get(key)
    if r is None:
        rgb = f"rgb({color.red()},{color.green()},{color.blue()})"
        body = ICON_SVG[kind].replace("currentColor", rgb)
        if color.alpha() < 255:
            body = f'<g opacity="{color.alpha() / 255:.3f}">{body}</g>'
        svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24">{body}</svg>'
        r = _RENDERERS[key] = QSvgRenderer(svg.encode("utf-8"))
    return r


class IconButton(QWidget):
    """A flat 26x26 button showing one of the SVG icons above (hover tint per kind)."""
    clicked = Signal()

    def __init__(self, kind: str, tip: str = "", parent=None):
        super().__init__(parent)
        self.kind = kind
        self._hover = False
        self.setFixedSize(26, 26)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(tip)

    def set_kind(self, kind: str, tip: Optional[str] = None) -> None:
        self.kind = kind
        if tip is not None:
            self.setToolTip(tip)
        self.update()

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def mousePressEvent(self, e):
        e.accept()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        color, hover_color, hover_bg = ICON_STYLE.get(self.kind, ICON_STYLE["reset"])
        if self._hover:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(hover_bg)
            p.drawRoundedRect(QRectF(self.rect()), 6, 6)
        svg_renderer(self.kind, hover_color if self._hover else color).render(p, QRectF(4, 4, 18, 18))


def _text_baseline(rect: QRectF, fm: QFontMetrics) -> float:
    """Baseline that vertically centres a line of this font inside rect (so mixed sizes share one baseline)."""
    return rect.top() + (rect.height() - (fm.ascent() + fm.descent())) / 2 + fm.ascent()


def sparkline_points(series: Sequence[Tuple[float, float]], rect: QRectF) -> Optional[List[QPointF]]:
    if len(series) < 2:
        return None
    ts = [s[0] for s in series]
    vs = [s[1] for s in series]
    t0, t1 = min(ts), max(ts)
    lo, hi = min(vs), max(vs)
    mean = sum(vs) / len(vs)
    span = max(hi - lo, abs(mean) * 0.12, 1e-9)
    pad = span * 0.08
    lo, hi = lo - pad, hi + pad
    pts = []
    for t, v in series:
        x = rect.left() + (t - t0) / max(t1 - t0, 1e-9) * rect.width()
        y = rect.bottom() - (v - lo) / (hi - lo) * rect.height()
        pts.append(QPointF(x, y))
    return pts


class ModeButton(QWidget):
    """The AUTO / MANUAL switch next to the clock."""
    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.auto = True
        self._hover = False
        self._font = ui_font(11, QFont.Weight.DemiBold)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.set_auto(True)

    PAD_X, HEIGHT = 5, 22        # the prototype's px-1.25 and h-5.5

    def label(self) -> str:
        return "AUTO" if self.auto else "MANUAL"

    def set_auto(self, auto: bool) -> None:
        self.auto = bool(auto)
        self.setFixedSize(QFontMetrics(self._font).horizontalAdvance(self.label()) + 2 * self.PAD_X, self.HEIGHT)
        self.setToolTip("AUTO: the clock starts, and resumes after any pause, when you gain EXP. Click to switch to MANUAL." if self.auto else
                        "MANUAL: only the play button starts the clock. Click to switch to AUTO.")
        self.update()

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def mousePressEvent(self, e):
        e.accept()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self._hover:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(38, 38, 38, 178))
            p.drawRoundedRect(QRectF(self.rect()), 2, 2)
        p.setFont(self._font)
        p.setPen(C_TEXT if self._hover else C_DIM)
        p.drawText(QRectF(self.rect()), Qt.AlignmentFlag.AlignCenter, self.label())


class Row(NamedTuple):
    """One line under a chip's headline."""
    label: str
    value: str
    unit: str = ""
    arrow: Optional[str] = None          # "up" / "down": green / red trend arrow before the label
    note: str = ""                       # small dim text after the label
    color: Optional[QColor] = None       # value colour (default white)


HR = "/ hr"


class Chip(QWidget):
    """One metric: icon, name and headline value, plus extra rows when expanded and an optional footer line.
    The trend graph sits faintly in the background. Clicking cycles the views (the window decides what each
    shows); the footer's link has its own signal."""
    clicked = Signal()
    link_clicked = Signal()
    PAD_X, PAD_Y, HEAD, ROW, GAP, FOOT, ICON = 8, 4, 28, 20, 4, 14, 18
    AVAIL = 258 - 16                 # text width inside a chip

    def __init__(self, title: str, icon: str, label_color: QColor, tint: QColor, parent=None):
        super().__init__(parent)
        self.title, self.icon, self.label_color, self.tint = title, icon, label_color, tint
        self.suffix, self.value, self.unit = "", "---", HR
        self.rows: List[Row] = []
        self.series: List[Tuple[float, float]] = []
        self.footer, self.link = "", ""
        self._link_rect = QRectF()
        self.bg_alpha = 255          # background opacity (0-255); text is never affected
        self._hover = False
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(self.height_for(0, 0))

    def height_for(self, n_rows: int, footer_lines: int) -> int:
        return (2 * self.PAD_Y + self.HEAD + n_rows * (self.GAP + self.ROW)
                + (self.GAP + footer_lines * self.FOOT if footer_lines else 0))

    @classmethod
    def footer_layout(cls, footer: str, link: str) -> Tuple[List[str], bool]:
        """(lines, link fits at the end of the last line). The footer wraps instead of being cut off; the link goes
        on a line of its own when it doesn't fit after the text."""
        if not footer:
            return [], False
        fm = QFontMetrics(ui_font(11))
        lines: List[str] = []
        cur = ""
        for word in footer.split(" "):
            trial = f"{cur} {word}" if cur else word
            if cur and fm.horizontalAdvance(trial) > cls.AVAIL:
                lines.append(cur)
                cur = word
            else:
                cur = trial
        lines.append(cur)
        if not link:
            return lines, False
        if fm.horizontalAdvance(lines[-1]) + fm.horizontalAdvance(link) + 6 <= cls.AVAIL:
            return lines, True
        return lines + [""], False

    @classmethod
    def footer_lines(cls, footer: str, link: str) -> int:
        return len(cls.footer_layout(footer, link)[0])

    def set_data(self, suffix: str, value: str, unit: str, rows, series, footer: str = "", link: str = "") -> None:
        self.suffix, self.value, self.unit, self.rows, self.series = suffix, value, unit, list(rows), list(series)
        self.footer, self.link = footer, link
        self.setFixedHeight(self.height_for(len(self.rows), self.footer_lines(footer, link)))
        self.update()

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def mousePressEvent(self, e):
        e.accept()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self.rect().contains(e.position().toPoint()):
            if self.link and self._link_rect.contains(e.position()):
                self.link_clicked.emit()
            else:
                self.clicked.emit()

    def _value_run(self, p: QPainter, right: float, rect: QRectF, value: str, unit: str, vf: QFont, uf: QFont,
                   color: Optional[QColor] = None) -> None:
        """value then unit, right-aligned to `right`, sharing one baseline."""
        vfm, ufm = QFontMetrics(vf), QFontMetrics(uf)
        uw = ufm.horizontalAdvance(unit) + 4 if unit else 0
        base = _text_baseline(rect, vfm)
        x = right - uw - vfm.horizontalAdvance(value)
        p.setFont(vf)
        p.setPen(color or C_TEXT)
        p.drawText(QPointF(x, base), value)
        if unit:
            p.setFont(uf)
            p.setPen(C_HALF)
            p.drawText(QPointF(right - uw + 4, base), unit)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, 6, 6)
        k = self.bg_alpha / 255.0
        p.fillPath(path, rgba(self.tint, int((self.tint.alpha() + (10 if self._hover else 0)) * k)))
        # trend graph, very faint
        pts = sparkline_points(self.series, QRectF(r.left(), r.top() + r.height() * 0.30, r.width(), r.height() * 0.62))
        if pts:
            p.save()
            p.setClipPath(path)
            line = QPainterPath(pts[0])
            for pt in pts[1:]:
                line.lineTo(pt)
            area = QPainterPath(line)
            area.lineTo(QPointF(pts[-1].x(), r.bottom()))
            area.lineTo(QPointF(pts[0].x(), r.bottom()))
            area.closeSubpath()
            grad = QLinearGradient(0, r.top(), 0, r.bottom())
            grad.setColorAt(0.0, rgba(self.label_color, 34))
            grad.setColorAt(1.0, rgba(self.label_color, 3))
            p.fillPath(area, grad)
            pen = QPen(rgba(self.label_color, 80), 1.2)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(line)
            p.restore()
        p.setPen(QPen(rgba(self.tint, 26), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)

        L, R = self.PAD_X, r.width() - self.PAD_X
        head = QRectF(0, self.PAD_Y, r.width(), self.HEAD)
        svg_renderer(self.icon, self.label_color).render(
            p, QRectF(L, head.top() + (self.HEAD - self.ICON) / 2, self.ICON, self.ICON))
        tx = L + self.ICON + 4
        tf = ui_font(14, QFont.Weight.DemiBold)
        tfm = QFontMetrics(tf)
        p.setFont(tf)
        p.setPen(self.label_color)
        p.drawText(QPointF(tx, _text_baseline(head, tfm)), self.title)
        if self.suffix:
            sf = ui_font(11)
            sf.setItalic(True)
            p.setFont(sf)
            p.setPen(C_FAINT)
            p.drawText(QPointF(tx + tfm.horizontalAdvance(self.title) + 6, _text_baseline(head, QFontMetrics(sf))),
                       self.suffix)
        self._value_run(p, R, head, self.value, self.unit, ui_font(14, QFont.Weight.DemiBold), ui_font(12))
        lf, vf, uf = ui_font(14, QFont.Weight.DemiBold), ui_font(14, QFont.Weight.DemiBold), ui_font(12)
        nf = ui_font(11)
        nf.setItalic(True)
        y = self.PAD_Y + self.HEAD + self.GAP
        for row in self.rows:
            rect = QRectF(0, y, r.width(), self.ROW)
            if row.arrow:
                col = QColor(239, 68, 68) if row.arrow == "down" else QColor(34, 197, 94)
                svg_renderer("trending-down" if row.arrow == "down" else "trending-up", col).render(
                    p, QRectF(L, y + (self.ROW - 16) / 2, 16, 16))
            p.setFont(lf)
            p.setPen(C_TEXT200)
            lx = L + 22
            p.drawText(QPointF(lx, _text_baseline(rect, QFontMetrics(lf))), row.label)
            if row.note:
                p.setFont(nf)
                p.setPen(C_FAINT)
                p.drawText(QPointF(lx + QFontMetrics(lf).horizontalAdvance(row.label) + 6,
                                   _text_baseline(rect, QFontMetrics(nf))), row.note)
            self._value_run(p, R, rect, row.value, row.unit, vf, uf, row.color)
            y += self.ROW + self.GAP
        self._link_rect = QRectF()
        lines, inline = self.footer_layout(self.footer, self.link)
        if lines:
            ff = ui_font(11)
            fm = QFontMetrics(ff)
            top = self.height() - self.PAD_Y - len(lines) * self.FOOT
            p.setFont(ff)
            p.setPen(C_FAINT)
            for n, text in enumerate(lines):
                row = QRectF(0, top + n * self.FOOT, r.width(), self.FOOT)
                p.drawText(QPointF(L, _text_baseline(row, fm)), fm.elidedText(text, Qt.TextElideMode.ElideRight, int(R - L)))
            if self.link:
                lf2 = ui_font(11, QFont.Weight.DemiBold)
                lf2.setUnderline(True)
                lw = fm.horizontalAdvance(self.link)
                row = QRectF(0, top + (len(lines) - 1) * self.FOOT, r.width(), self.FOOT)
                lx = R - lw if inline else L
                p.setFont(lf2)
                p.setPen(self.label_color)
                p.drawText(QPointF(lx, _text_baseline(row, fm)), self.link)
                self._link_rect = QRectF(lx - 3, row.top(), lw + 6, self.FOOT)


class StatusStrip(QWidget):
    """The message under the buttons, left-aligned. Problems get an icon; long messages wrap beside it."""
    WIDTH = 258                  # inner width of the panel
    PAD_X, PAD_Y, MARGIN_BOTTOM, LH, ICON = 8, 2, 4, 16, 14
    COLORS = {"info": QColor(163, 163, 163), "ok": QColor(74, 222, 128), "warn": QColor(251, 191, 36, 220),
              "paused": QColor(234, 179, 8), "error": QColor(248, 113, 113)}
    ICONS = {"warn": "alert-triangle", "error": "alert-octagon"}

    def __init__(self, parent=None):
        super().__init__(parent)
        self._text, self.kind = "", "info"
        self._font = ui_font(12)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(self._height_for(self.LH))

    def text(self) -> str:
        return self._text

    def _height_for(self, text_h: int) -> int:
        return text_h + 2 * self.PAD_Y + self.MARGIN_BOTTOM

    def _text_rect(self) -> QRect:
        x = self.PAD_X + (self.ICON + 5 if self.kind in self.ICONS else 0)
        return QRect(x, self.PAD_Y, self.WIDTH - x - self.PAD_X, 1000)

    def set_message(self, text: str, kind: str = "info") -> None:
        self._text, self.kind = text, kind
        self.setVisible(bool(text))
        h = QFontMetrics(self._font).boundingRect(self._text_rect(), int(Qt.TextFlag.TextWordWrap), text).height()
        self.setFixedHeight(self._height_for(max(self.LH, h)) if text else 0)
        self.update()

    def paintEvent(self, e):
        if not self._text:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = self.COLORS.get(self.kind, self.COLORS["info"])
        icon = self.ICONS.get(self.kind)
        if icon:
            svg_renderer(icon, color).render(p, QRectF(self.PAD_X, self.PAD_Y + 1, self.ICON, self.ICON))
        p.setFont(self._font)
        p.setPen(color)
        p.drawText(QRectF(self._text_rect()), int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop |
                                                  Qt.TextFlag.TextWordWrap), self._text)


def _key(text: str) -> QLabel:
    l = QLabel(text)
    l.setStyleSheet(f"color: {C_DIM.name()}; background: transparent;")
    l.setFont(ui_font(11))
    return l


# --------------------------------------------------------------------------- #
# Dialogs
# --------------------------------------------------------------------------- #


def _top_dialog(d: QDialog) -> QDialog:
    d.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    return d


class CalibrateDialog(QDialog):
    """Shows what the tracker sees, lets you nudge the EXP box and teach unknown characters."""

    def __init__(self, overlay: "OverlayWindow", parent=None):
        super().__init__(parent)
        _top_dialog(self)
        self.ov = overlay
        self.cfg = overlay.cfg
        self.setWindowTitle("Check the EXP box")
        self.frozen = False
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("The red box is where the tracker looks for your EXP numbers. "
                             "It should hug the number (not the 'EXP.' label)."))
        self.context = QLabel()
        self.context.setMinimumHeight(90)
        lay.addWidget(self.context)
        self.crop = QLabel()
        lay.addWidget(self.crop)
        self.reads = QLabel("")
        self.reads.setFont(ui_font(13, QFont.Weight.Medium, mono=True))
        lay.addWidget(self.reads)
        spec = self.cfg["exp_region"]
        row = QHBoxLayout()
        self.spins = {}
        for key, label, lo, hi in (("dx", "Right of center", -600, 600), ("dy", "Above bottom", 4, 200),
                                   ("w", "Width", 10, 400), ("h", "Height", 6, 60)):
            col = QVBoxLayout()
            col.addWidget(QLabel(label))
            sp = QSpinBox()
            sp.setRange(lo, hi)
            sp.setValue(int(spec[key]))
            sp.valueChanged.connect(self._spec_changed)
            self.spins[key] = sp
            col.addWidget(sp)
            row.addLayout(col)
        lay.addLayout(row)
        self.teach_row = QWidget()
        tl = QHBoxLayout(self.teach_row)
        tl.setContentsMargins(0, 0, 0, 0)
        self.entry = QLineEdit()
        self.entry.setFont(ui_font(13, mono=True))
        self.teach_btn = QPushButton("Teach")
        tl.addWidget(QLabel("Unknown character(s). Type what you see:"))
        tl.addWidget(self.entry, 1)
        tl.addWidget(self.teach_btn)
        self.teach_row.hide()
        lay.addWidget(self.teach_row)
        self.msg = QLabel("")
        self.msg.setWordWrap(True)
        lay.addWidget(self.msg)
        bb = QHBoxLayout()
        reset = QPushButton("Forget taught characters")
        done = QPushButton("Done")
        done.setDefault(True)
        bb.addWidget(reset)
        bb.addStretch(1)
        bb.addWidget(done)
        lay.addLayout(bb)
        self.teach_btn.clicked.connect(self._teach)
        self.entry.returnPressed.connect(self._teach)
        reset.clicked.connect(self._forget)
        done.clicked.connect(self.accept)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(500)
        self._last_fr = None
        self.refresh()
        self.setMinimumWidth(560)

    def _spec(self) -> dict:
        return {k: s.value() for k, s in self.spins.items()}

    def _spec_changed(self):
        self.cfg["exp_region"].update(self._spec())
        self.frozen = False
        self.refresh()

    def _forget(self):
        self.ov.lib.clear_user()
        self.ov.lib.save()
        self.msg.setText("Forgot all taught characters (the built-in ones remain).")

    def _teach(self):
        fr = self._last_fr
        if fr is None:
            return
        try:
            n = ec.label_from_text(self.ov.lib, fr.glyphs, self.entry.text(), self.cfg["max_glyph_dist"])
        except ValueError as e:
            self.msg.setText(str(e))
            return
        self.ov.lib.save()
        self.msg.setText(f"Learned {n} new character shape(s).")
        self.frozen = False
        self.refresh()

    def refresh(self):
        if self.frozen:
            return
        spec = self._spec()
        win = self.ov.find_window(self.cfg)
        if not win:
            self.msg.setText("Game window not found. Open the game (windowed or borderless) and keep its title "
                             f"containing '{self.cfg['window_title']}'.")
            self.reads.setText("")
            return
        region = ec.compute_region(win, spec)
        if not region:
            self.msg.setText("With these numbers the box falls outside the game window.")
            return
        # context picture with the box outlined
        mx, my = 36, 10
        ctx = {"left": max(win["left"], region["left"] - mx), "top": max(win["top"], region["top"] - my)}
        ctx["width"] = min(win["left"] + win["width"], region["left"] + region["width"] + mx) - ctx["left"]
        ctx["height"] = min(win["top"] + win["height"], region["top"] + region["height"] + my) - ctx["top"]
        try:
            big = self.ov.capture.grab(ctx)
            small = self.ov.capture.grab(region)
        except Exception as e:  # pragma: no cover - capture problems are shown, not raised
            self.msg.setText(f"Screen capture failed: {e}")
            return
        z = max(1, min(6, 520 // max(ctx["width"], 1)))
        img = np_to_qimage(big).scaled(ctx["width"] * z, ctx["height"] * z, Qt.AspectRatioMode.IgnoreAspectRatio,
                                       Qt.TransformationMode.FastTransformation)
        pr = QPainter(img)
        pr.setPen(QPen(QColor(255, 60, 60), 2))
        pr.drawRect((region["left"] - ctx["left"]) * z, (region["top"] - ctx["top"]) * z,
                    region["width"] * z - 1, region["height"] * z - 1)
        pr.end()
        self.context.setPixmap(QPixmap.fromImage(img))
        zc = max(1, min(8, 520 // max(region["width"], 1)))
        self.crop.setPixmap(QPixmap.fromImage(np_to_qimage(small).scaled(
            region["width"] * zc, region["height"] * zc, Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.FastTransformation)))
        reading, fr = ec.read_exp(small, self.cfg, self.ov.lib)
        self._last_fr = fr
        if reading.exp is not None:
            pct = f"  {reading.pct:.2f}%" if reading.pct is not None else ""
            self.reads.setText(f"Reads: {reading.exp:,}{pct}")
            self.msg.setText("Looks good." if reading.pct is not None else
                             "EXP reads fine, but the percent is cut off. That's OK, but a slightly wider box "
                             "helps the tracker work out your level.")
            self.teach_row.hide()
        else:
            self.reads.setText(f"Reads: {reading.text!r}")
            if fr.unknown:
                self.frozen = True
                self.entry.setText(reading.text)
                self.teach_row.show()
                self.msg.setText("Replace each '?' with the real character (one per glyph) and press Teach.")
            elif not fr.glyphs:
                self.msg.setText("No text found in the box. Move it onto the EXP numbers.")
                self.teach_row.hide()
            else:
                self.msg.setText("Couldn't make sense of this text. Make sure the box covers only the number "
                                 "and the [percent].")
                self.teach_row.hide()

    def done(self, r):
        self.timer.stop()
        ec.save_config(self.cfg)
        super().done(r)


# --------------------------------------------------------------------------- #
# Quick slots: check what it sees, add items it doesn't know, teach it the count digits
# --------------------------------------------------------------------------- #


class QuickSlotDialog(QDialog):
    """One row per slot that holds an icon. Type the item's name and the quantity you see on screen: the icon is
    remembered (with its price) and the digit shapes are learned from the number, so it can read the counts."""

    def __init__(self, overlay: "OverlayWindow", parent=None):
        super().__init__(parent)
        _top_dialog(self)
        self.ov = overlay
        self.setWindowTitle("Quick slots")
        self.setMinimumWidth(460)
        self.rows: List[dict] = []
        lay = QVBoxLayout(self)
        intro = QLabel("These are the quick-slot icons it can see. For an item, give its name and price, and type the "
                       "quantity shown on it (that teaches it to read the numbers). Skills and empty slots can be "
                       "left blank.")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        self.grid = QVBoxLayout()
        lay.addLayout(self.grid)
        self.msg = QLabel("")
        self.msg.setWordWrap(True)
        lay.addWidget(self.msg)
        bb = QHBoxLayout()
        self.forget = QPushButton("Forget what I taught it")
        self.rescan = QPushButton("Rescan")
        self.save_btn = QPushButton("Save")
        self.save_btn.setDefault(True)
        close = QPushButton("Close")
        for b in (self.forget, self.rescan):
            bb.addWidget(b)
        bb.addStretch(1)
        bb.addWidget(self.save_btn)
        bb.addWidget(close)
        lay.addLayout(bb)
        self.forget.clicked.connect(self._forget)
        self.rescan.clicked.connect(self.populate)
        self.save_btn.clicked.connect(self.save)
        close.clicked.connect(self.accept)
        self.populate()

    @property
    def lib(self) -> ec_items.ItemLibrary:
        return self.ov.items

    def populate(self) -> None:
        self.ov.read_quickslots(self.ov.clock(), force=True)
        while self.grid.count():
            w = self.grid.takeAt(0)
            if w.widget():
                w.widget().deleteLater()
        self.rows = []
        scan, strip = self.ov.qscan, self.ov.last_strip
        if scan is None or strip is None or not scan.visible:
            self.msg.setText("The quick slots aren't visible. Open the game (windowed or borderless) and show them.")
            return
        for info in scan.slots:
            if not info.has_art:
                continue
            row = QWidget()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(0, 0, 0, 0)
            crop = ec_items.slot_picture(strip, info.index, scan.dx, scan.dy)       # with room for the number's left edge
            thumb = QLabel()
            thumb.setPixmap(QPixmap.fromImage(np_to_qimage(crop)).scaled(
                crop.shape[1] * 3, crop.shape[0] * 3, Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.FastTransformation))
            rl.addWidget(thumb)
            col = QVBoxLayout()
            top = QHBoxLayout()
            name = QLineEdit(info.name or "")
            name.setPlaceholderText("Item name")
            pick = QPushButton("▾")
            pick.setFixedWidth(28)
            pick.setToolTip("Pick from the known items")
            price = QSpinBox()
            price.setRange(0, 10_000_000)
            price.setSuffix(" mesos")
            price.setValue(self.lib.price(info.name) if info.name else 0)
            choices = QListWidget()                      # a plain widget inside the dialog, not a popup window
            choices.addItems(self.lib.names())
            choices.setMaximumHeight(104)
            choices.hide()
            name.textChanged.connect(lambda t, sp=price: sp.setValue(self.lib.price(t)) if t in self.lib.prices else None)
            pick.clicked.connect(lambda _=False, lw=choices: lw.setVisible(not lw.isVisible()))
            choices.itemClicked.connect(lambda item, n=name, lw=choices: (n.setText(item.text()), lw.hide()))
            top.addWidget(QLabel(f"{info.key}:"))
            top.addWidget(name, 1)
            top.addWidget(pick)
            top.addWidget(price)
            col.addLayout(top)
            col.addWidget(choices)
            qty = QLineEdit()
            if info.status == "ok":
                qty.setPlaceholderText(f"reads {info.count:,}. Type it only to teach more digits")
            else:
                qty.setPlaceholderText("quantity shown on the icon (leave blank for skills)" if info.has_count
                                       else "no quantity shown")
                qty.setEnabled(info.has_count)
            col.addWidget(qty)
            rl.addLayout(col, 1)
            self.grid.addWidget(row)
            self.rows.append({"info": info, "name": name, "price": price, "qty": qty, "choices": choices, "pick": pick})
        if not self.rows:
            self.msg.setText("No icons found in the quick slots (skills with no colour are ignored).")
        else:
            self.msg.setText("")

    def save(self) -> None:
        strip, scan = self.ov.last_strip, self.ov.qscan
        problems, learned = [], 0
        for r in self.rows:
            info, name = r["info"], r["name"].text().strip()
            typed = r["qty"].text().strip()
            if not name:
                if typed:
                    problems.append(f"{info.key}: give it a name first.")
                continue
            sig = ec_items.icon_signature(ec_items.slot_crop(strip, info.index, scan.dx, scan.dy))
            self.lib.add_item(name, r["price"].value(), sig)
            if typed:
                try:
                    learned += self.lib.digits.teach_slot(strip, info.index, typed, scan.dx, scan.dy)
                except ValueError as e:
                    problems.append(f"{info.key}: {e}")
        self.lib.save()
        self.ov.read_quickslots(self.ov.clock(), force=True)
        self.ov.refresh(self.ov.clock())
        self.msg.setText(" ".join(problems) if problems else
                         f"Saved. Learned {learned} new digit shape(s)." if learned else "Saved.")
        if not problems:
            self.populate_keep_message()

    def populate_keep_message(self) -> None:
        text = self.msg.text()
        self.populate()
        self.msg.setText(text)

    def _forget(self) -> None:
        self.lib.forget_user()
        self.lib.save()
        self.ov.stock.reset()
        self.ov.read_quickslots(self.ov.clock(), force=True)
        self.populate_keep_message()
        self.msg.setText("Forgot the items, prices and digits you added (the built-in ones remain).")


# --------------------------------------------------------------------------- #
# Settings page (inline; replaces the panel contents)
# --------------------------------------------------------------------------- #


class SettingsPage(QWidget):
    def __init__(self, ov: "OverlayWindow"):
        super().__init__()
        cfg = ov.cfg
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(8)
        form.setVerticalSpacing(5)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        self.timeout = QSpinBox()
        self.timeout.setRange(0, 3600)
        self.timeout.setSuffix(" s")
        self.timeout.setSpecialValueText("Never")
        self.timeout.setValue(int(cfg["timeout_seconds"]))
        self.timeout.setToolTip("AUTO mode only: stop the clock after this long without EXP. It carries on when EXP comes in.")
        form.addRow(_key("Auto-pause after"), self.timeout)
        self.level = QSpinBox()
        self.level.setRange(0, ec.MAX_LEVEL)
        self.level.setSpecialValueText("Auto-detect")
        self.level.setValue(int(cfg["level_override"]))
        self.level.setToolTip("Only needed if the tracker can't work out your level by itself.")
        form.addRow(_key("Level"), self.level)
        self.mode = QComboBox()
        self.mode.addItem("Find by title", "auto")
        self.mode.addItem("Whole screen", "screen")
        self.mode.setCurrentIndex(0 if cfg["window_mode"] == "auto" else 1)
        form.addRow(_key("Game window"), self.mode)
        self.title = QLineEdit(cfg["window_title"])
        self.title.setToolTip("The game window's title bar must contain this text.")
        form.addRow(_key("Title contains"), self.title)
        self.interval = QDoubleSpinBox()
        self.interval.setRange(0.5, 5.0)
        self.interval.setSingleStep(0.5)
        self.interval.setSuffix(" s")
        self.interval.setValue(float(cfg["interval"]))
        form.addRow(_key("Read every"), self.interval)
        self.opacity = QSlider(Qt.Orientation.Horizontal)
        self.opacity.setRange(60, 100)
        self.opacity.setValue(int(round(float(cfg["opacity"]) * 100)))
        self.opacity.valueChanged.connect(lambda v: ov.set_opacity(v / 100.0))
        form.addRow(_key("Opacity"), self.opacity)
        lay.addLayout(form)
        self.cal = QPushButton("Check / adjust EXP box…")
        self.cal.clicked.connect(ov.open_calibrate)
        lay.addWidget(self.cal)
        self.slots_btn = QPushButton("Check quick slots…")
        self.slots_btn.clicked.connect(ov.open_quickslots)
        lay.addWidget(self.slots_btn)
        row = QHBoxLayout()
        row.setSpacing(6)
        self.dock_l, self.dock_r = QPushButton("Dock left"), QPushButton("Dock right")
        self.dock_l.clicked.connect(lambda: ov.dock("left"))
        self.dock_r.clicked.connect(lambda: ov.dock("right"))
        row.addWidget(self.dock_l)
        row.addWidget(self.dock_r)
        lay.addLayout(row)
        self.folder = QPushButton("Open data folder")
        self.folder.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(ec.data_dir()))))
        lay.addWidget(self.folder)

    def inputs(self) -> List[QWidget]:
        return [self.timeout, self.level, self.title, self.interval]

    def apply(self, c: dict) -> None:
        c["timeout_seconds"] = self.timeout.value()
        c["level_override"] = self.level.value()
        c["window_mode"] = self.mode.currentData()
        c["window_title"] = self.title.text().strip() or "MapleStory"
        c["interval"] = float(self.interval.value())
        c["opacity"] = self.opacity.value() / 100.0


# --------------------------------------------------------------------------- #
# The overlay
# --------------------------------------------------------------------------- #


EXP_HINT = "Make sure the EXP number is showing."


def _ago(sec: float) -> str:
    sec = int(max(0, sec))
    if sec < 60:
        return f"{sec}s ago"
    if sec < 3600:
        return f"{sec // 60}m ago"
    return f"{sec // 3600}h ago"


class OverlayWindow(QWidget):
    WIDTH = 268
    MARGIN = 8       # gap to the game window's edge when docking

    def __init__(self, cfg: Optional[dict] = None, capture=None, find_window: Optional[Callable] = None,
                 clock: Callable[[], float] = time.monotonic, start_timer: bool = True):
        super().__init__()
        self.cfg = cfg or ec.load_config()
        self.lib = ec.GlyphLibrary().load()
        self.table = ec.ExpTable()
        self.clock = clock
        self.capture = capture or ec.Capturer()
        self.find_window = find_window or ec.find_game_window
        self.tracker = ec.SessionTracker(self.table, self.cfg["timeout_seconds"], self.cfg["auto_start"],
                                         self.cfg["level_override"])
        self.inventory = ec.InventoryReader(float(self.cfg["max_glyph_dist"]))
        self.items = ec_items.ItemLibrary().load()
        self.stock = ec_items.StockTracker()
        self.qscan: Optional[ec_items.Scan] = None
        self.last_strip: Optional[np.ndarray] = None
        self._qs_prev: dict = {}
        self._qs_accepted: dict = {}
        self._qs_streak: dict = {}
        self._stock_session = 0
        self.status_flash_kind = "warn"
        self.status_text = ""
        self.status_until = 0.0
        self.status_flash = ""
        self.meso_synced_at: Optional[float] = None
        self._timer_col = ""
        self.views = {"exp": 0, "meso": 0}      # which view each metric is showing (click to cycle)
        self.in_settings = False
        self.focus_open = False
        self.last_win: Optional[dict] = None
        self._docked_at_launch = False
        self._err_logged = False
        self._drag = None
        self._moved = False
        self._anchor = None

        self.setWindowTitle("EXP Tracker")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint |
                            Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.opacity = 1.0
        self.setFixedWidth(self.WIDTH)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(5, 5, 5, 5)          # 1 px border + 4 px padding
        outer.setSpacing(0)
        self.pages = QStackedWidget()
        outer.addWidget(self.pages)

        # --- main page
        self.main = QWidget()
        root = QVBoxLayout(self.main)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)
        bar = QHBoxLayout()
        bar.setSpacing(0)
        self.btn_reset = IconButton("reset", "Reset the session")
        self.btn_play = IconButton("play", "Start tracking")
        self.timer_lbl = QLabel("00:00:00")
        tf = ui_font(14, QFont.Weight.DemiBold)
        tf.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.35)
        self.timer_lbl.setFont(tf)
        self.timer_lbl.setContentsMargins(8, 0, 8, 0)
        self.btn_mode = ModeButton()
        self.btn_mode.set_auto(bool(self.cfg["auto_start"]))
        self.btn_gear = IconButton("settings", "Settings")
        self.btn_close = IconButton("close", "Close")
        bar.addWidget(self.timer_lbl)
        bar.addWidget(self.btn_play)
        bar.addWidget(self.btn_reset)
        bar.addWidget(self.btn_mode)
        bar.addStretch(1)
        bar.addWidget(self.btn_gear)
        bar.addWidget(self.btn_close)
        root.addLayout(bar)

        self.status_lbl = StatusStrip()
        root.addWidget(self.status_lbl)

        self.chip_exp = Chip("EXP", "chart-line", C_EXP, QColor(59, 130, 246, 26))
        self.chip_meso = Chip("Mesos", "coin", C_MESO, QColor(217, 70, 239, 26))
        root.addWidget(self.chip_exp)
        root.addWidget(self.chip_meso)
        self.pages.addWidget(self.main)

        # --- settings page
        self.settings_page = QWidget()
        sl = QVBoxLayout(self.settings_page)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(8)
        head = QHBoxLayout()
        head.setSpacing(0)
        self.btn_back = IconButton("back", "Back")
        ttl = QLabel("Settings")
        ttl.setFont(ui_font(13, QFont.Weight.Bold))
        ttl.setContentsMargins(4, 0, 0, 0)
        ttl.setStyleSheet("background: transparent;")
        self.btn_gear2 = IconButton("settings", "Back")
        self.btn_close2 = IconButton("close", "Close")
        head.addWidget(self.btn_back)
        head.addWidget(ttl)
        head.addStretch(1)
        head.addWidget(self.btn_gear2)
        head.addWidget(self.btn_close2)
        sl.addLayout(head)
        self.settings = SettingsPage(self)
        sl.addWidget(self.settings)
        self.pages.addWidget(self.settings_page)

        for b, fn in ((self.btn_reset, self.on_reset), (self.btn_play, self.on_toggle),
                      (self.btn_gear, self.toggle_settings), (self.btn_gear2, self.toggle_settings),
                      (self.btn_back, self.toggle_settings), (self.btn_close, self.close),
                      (self.btn_mode, self.toggle_mode),
                      (self.btn_close2, self.close)):
            b.clicked.connect(fn)
        self.chip_exp.clicked.connect(lambda: self.cycle_view("exp"))
        self.chip_meso.clicked.connect(lambda: self.cycle_view("meso"))
        self.chip_meso.link_clicked.connect(self.open_quickslots)

        # inputs that need the keyboard (see focus gate)
        self._inputs: List[QWidget] = []
        for w in self.settings.inputs():
            self._register_input(w)

        self._set_page(0)
        self.set_opacity(float(self.cfg["opacity"]))
        self.place()
        self.resize(self.WIDTH, self._refit())
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.on_tick)
        self.top_timer = QTimer(self)
        self.top_timer.timeout.connect(self.keep_on_top)
        if start_timer:
            self.top_timer.start(700)
            self.timer.start(int(float(self.cfg["interval"]) * 1000))
            QTimer.singleShot(50, self.on_tick)
        self.refresh(self.clock())

    # -- window plumbing -------------------------------------------------------
    def _screen_geo(self):
        scr = self.screen() or QApplication.primaryScreen()
        return scr.availableGeometry() if scr is not None else None

    def place(self) -> None:
        pos = self.cfg["overlay"]
        x, y = int(pos.get("x", 60)), int(pos.get("y", 60))
        scr = QApplication.primaryScreen()
        if scr is not None:
            geo = scr.virtualGeometry()
            if not geo.contains(x + 40, y + 20):
                x, y = geo.left() + 60, geo.top() + 60
        self.move(x, y)

    def dock(self, side: str) -> None:
        """Park the panel in the empty strip beside the game's status bar (bottom-left / bottom-right)."""
        win = self.last_win
        if not win:
            try:
                win = self.find_window(self.cfg)
            except Exception:
                win = None
        if not win:
            self.flash("Game window not found, so there is nothing to dock to.", 5)
            self.refresh(self.clock())
            return
        scr = QApplication.primaryScreen()
        dpr = scr.devicePixelRatio() if scr is not None else 1.0
        left, top = win["left"] / dpr, win["top"] / dpr
        w, h = win["width"] / dpr, win["height"] / dpr
        hh = self._refit()
        x = left + self.MARGIN if side == "left" else left + w - self.WIDTH - self.MARGIN
        self._set_geometry_on_screen(x, top + h - hh - self.MARGIN, hh)
        self.cfg["overlay"].update(x=self.x(), y=self.y(), placed=True)
        self._save_cfg()

    def _refit(self) -> int:
        """Recompute the layout and return the height the panel wants."""
        for w in (self.main, self.settings_page, self.pages, self):
            if w.layout() is not None:
                w.layout().invalidate()
            w.updateGeometry()          # QWidgetItem caches size hints until the widget says they changed
        self.layout().activate()
        return self.layout().totalSizeHint().height()

    def _set_geometry_on_screen(self, x: int, y: int, h: int) -> None:
        geo = self._screen_geo()
        if geo is not None:
            x = min(max(x, geo.left()), max(geo.left(), geo.right() - self.WIDTH + 1))
            y = min(max(y, geo.top()), max(geo.top(), geo.bottom() - h + 1))
        self.setGeometry(int(x), int(y), self.WIDTH, int(h))

    def _clamp(self) -> None:
        self._set_geometry_on_screen(self.x(), self.y(), self.height())

    def _begin_resize(self) -> None:
        # Remember where the panel sits before its contents change (showing a child may resize it at once).
        self._anchor = (self.y(), self.y() + self.height())

    def _resize_keep_anchor(self) -> None:
        """Re-fit the height. A panel in the lower half of the screen grows upward, so it never covers
        the status bar; otherwise it grows downward. Always kept on screen."""
        old_top, old_bottom = self._anchor or (self.y(), self.y() + self.height())
        self._anchor = None
        h = self._refit()
        geo = self._screen_geo()
        grow_up = geo is not None and old_bottom > geo.top() + geo.height() * 0.5
        self._set_geometry_on_screen(self.x(), old_bottom - h if grow_up else old_top, h)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
        p.fillPath(path, rgba(C_BG, int(round(255 * self.opacity))))
        p.setPen(QPen(C_BORDER, 1))
        p.drawPath(path)

    def set_opacity(self, v: float) -> None:
        """Opacity of the backgrounds only (panel and chips); text and graphs stay solid."""
        self.opacity = max(0.6, min(1.0, float(v)))
        alpha = int(round(255 * self.opacity))
        for chip in (self.chip_exp, self.chip_meso):
            chip.bg_alpha = alpha
            chip.update()
        self.update()

    def keep_on_top(self) -> None:
        """Windows can push a topmost window behind the game when you alt-tab; put it back (no focus change)."""
        if sys.platform != "win32" or QGuiApplication.platformName() != "windows" or not self.isVisible():
            return
        try:
            import ctypes
            from ctypes import wintypes
            f = ctypes.windll.user32.SetWindowPos
            f.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                          wintypes.UINT]
            # HWND_TOPMOST, SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE | SWP_SHOWWINDOW
            f(wintypes.HWND(int(self.winId())), wintypes.HWND(-1), 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010 | 0x0040)
        except Exception:
            pass

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self._moved = False

    def mouseMoveEvent(self, e):
        if self._drag is not None and e.buttons() & Qt.MouseButton.LeftButton:
            self._moved = True
            self.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, e):
        if self._drag is not None:
            self._drag = None
            if self._moved:
                self.cfg["overlay"].update(x=self.x(), y=self.y(), placed=True)
                self._save_cfg()

    def _save_cfg(self) -> None:
        try:
            ec.save_config(self.cfg)
        except OSError:
            pass

    # -- keyboard focus gate ---------------------------------------------------
    # The panel normally never takes focus, so clicking it can't pull the keyboard away from the game.
    # Typing into a text field needs focus, so it is allowed only while such a field is being used.
    def _register_input(self, w: QWidget) -> None:
        for t in {w, getattr(w, "viewport", lambda: None)() or w, getattr(w, "lineEdit", lambda: None)() or w}:
            t.installEventFilter(self)
        self._inputs.append(w)

    def _is_input(self, obj) -> bool:
        for w in self._inputs:
            if obj is w or obj is (w.viewport() if hasattr(w, "viewport") else None) or \
                    obj is (w.lineEdit() if hasattr(w, "lineEdit") else None):
                return True
        return False

    def eventFilter(self, obj, ev):
        t = ev.type()
        if t == QEvent.Type.MouseButtonPress and self._is_input(obj) and not self.focus_open:
            self._focus_mode(True)
            QTimer.singleShot(0, lambda o=obj: o.setFocus())
        elif t == QEvent.Type.FocusOut and self.focus_open and self._is_input(obj):
            QTimer.singleShot(80, self._maybe_release_focus)
        return super().eventFilter(obj, ev)

    def _focus_mode(self, on: bool) -> None:
        if on == self.focus_open:
            return
        self.focus_open = on
        pos = self.pos()
        self.setWindowFlag(Qt.WindowType.WindowDoesNotAcceptFocus, not on)
        self.show()
        self.move(pos)
        if on:
            self.activateWindow()

    def _maybe_release_focus(self) -> None:
        fw = QApplication.focusWidget()
        if fw is not None and self._is_input(fw):
            return
        for w in self._inputs:
            if w.hasFocus():
                return
        self._focus_mode(False)

    # -- pages / breakdown -----------------------------------------------------
    def _set_page(self, idx: int) -> None:
        self.pages.setCurrentIndex(idx)
        for i in range(self.pages.count()):
            pol = QSizePolicy.Policy.Ignored if i != idx else QSizePolicy.Policy.Preferred
            self.pages.widget(i).setSizePolicy(pol, pol)

    def toggle_settings(self) -> None:
        self._begin_resize()
        if self.in_settings:
            self.settings.apply(self.cfg)
            self.in_settings = False
            self._set_page(0)
            self.apply_settings()
        else:
            self.in_settings = True
            self._set_page(1)
        self._resize_keep_anchor()

    def cycle_view(self, which: str) -> None:
        """Click a metric to step through its views (EXP has four, mesos three), then back to the first."""
        self.views[which] = (self.views[which] + 1) % (4 if which == "exp" else 3)
        self.refresh(self.clock())

    def toggle_mode(self) -> None:
        """AUTO: EXP gain starts the clock. MANUAL: only the play button does."""
        self.cfg["auto_start"] = not self.cfg["auto_start"]
        self.tracker.configure(self.cfg["timeout_seconds"], self.cfg["auto_start"], self.cfg["level_override"])
        self.btn_mode.set_auto(self.cfg["auto_start"])
        self._save_cfg()
        self.refresh(self.clock())

    # -- reading loop ----------------------------------------------------------
    def flash(self, text: str, seconds: float = 4.0, kind: str = "warn") -> None:
        self.status_flash, self.status_flash_kind = text, kind
        self.status_until = self.clock() + seconds

    def capture_exp_crop(self) -> Tuple[Optional[np.ndarray], str]:
        win = self.find_window(self.cfg)
        self.last_win = win
        if not win:
            return None, "window"
        if not self._docked_at_launch:          # every launch starts docked bottom-left (drag it afterwards if you like)
            self._docked_at_launch = True
            self.dock("left")
        region = ec.compute_region(win, self.cfg["exp_region"])
        if not region:
            return None, "small"
        return self.capture.grab(region), ""

    def on_tick(self) -> None:
        now = self.clock()
        base = ""
        try:
            crop, why = self.capture_exp_crop()
            if crop is None:
                base = ("Game window not found. Is MapleStory open?" if why == "window"
                        else "The game window is too small to contain the EXP bar.")
            else:
                self.read_inventory(now)
                self.read_quickslots(now)
                reading, fr = ec.read_exp(crop, self.cfg, self.lib)
                if reading.exp is None:
                    if not fr.glyphs:
                        base = EXP_HINT
                    elif fr.unknown:
                        base = EXP_HINT
                    else:
                        base = EXP_HINT
                else:
                    ev = self.tracker.feed(now, reading.exp, reading.pct)
                    base = self._event_message(ev)
            self.tracker.tick(now)
            self.status_text = base
            self._err_logged = False
        except Exception as ex:
            self.status_text = f"Error: {ex}"
            if not self._err_logged:
                traceback.print_exc()
                self._err_logged = True
        self.refresh(now)

    SLIP_READS = 4        # reads in a row before a count that looks like a lost / gained digit is believed

    def _trusted_counts(self, counts: dict) -> dict:
        """A new count is believed once it has been read twice in a row. If it only differs from the accepted one by a
        digit appearing or vanishing (37 -> 3), it must hold for several reads: that is how a misread looks."""
        out = {}
        for name, c in counts.items():
            accepted = self._qs_accepted.get(name)
            if accepted is None or c == accepted:
                self._qs_streak.pop(name, None)
                if accepted is None and self._qs_prev.get(name) != c:
                    self._qs_streak[name] = (c, 1)
                    continue
                self._qs_accepted[name] = c
            else:
                value, n = self._qs_streak.get(name, (None, 0))
                n = n + 1 if value == c else 1
                self._qs_streak[name] = (c, n)
                if n >= (self.SLIP_READS if ec_items.digit_slip(accepted, c) else 2):
                    self._qs_accepted[name] = c
                    self._qs_streak.pop(name, None)
            out[name] = self._qs_accepted[name]
        self._qs_prev = dict(counts)
        return out

    def read_quickslots(self, now: float, force: bool = False) -> None:
        """Look at the quick-slot panel: which consumables are in it and how many of each. The counts feed the
        stock tracker (potion cost). `force` rescans even when the setting is off (the check dialog)."""
        if not force and not self.cfg.get("read_quickslots", True):
            return
        win = self.last_win or (self.find_window(self.cfg) if force else None)
        region = ec_items.strip_region(win) if win else None
        if not region:
            self.qscan, self.last_strip = None, None
            return
        try:
            strip = self.capture.grab(region)
            scan = ec_items.scan_strip(strip, self.items)
        except Exception:
            self.qscan, self.last_strip = None, None
            return
        self.qscan, self.last_strip = scan, strip
        confirmed = self._trusted_counts(scan.counts())
        tr = self.tracker
        if tr.has_session() and self._stock_session != tr.session_id:
            self.stock.begin()
            self._stock_session = tr.session_id
        elif not tr.has_session() and self._stock_session:
            self._stock_session = 0
            self.stock.reset()
        self.stock.update(confirmed, {n: self.items.price(ec_items.base_name(n)) for n in confirmed},
                          tr.state == ec.RUNNING)

    def read_inventory(self, now: float) -> None:
        """While the inventory window is open, take the mesos from it."""
        if not self.cfg.get("read_mesos", True) or not self.last_win:
            return
        try:
            mesos = self.inventory.poll(self.capture, self.last_win, now)
        except Exception:
            mesos = None
        if mesos is not None and self.tracker.set_meso(now, mesos):
            self.meso_synced_at = now

    def _event_message(self, ev: str) -> str:
        if ev == "levelup":
            self.flash("Level up!", 6, "ok")
        elif ev == "rebased":
            self.flash("Level changed: re-synced.", 6)
        elif ev == "rejected":
            self.flash("Ignored an odd reading.", 3)
        elif ev == "lost":
            self.flash("Lost track of your level. Detecting it again…", 6)
        return {
            "waiting": "Detecting your level…",
            "ambiguous": "Detecting your level… (locks on once EXP changes)",
            "need_pct": "The percent isn't readable; set your level in Settings.",
            "mismatch": "Your EXP doesn't fit the level set in Settings.",
        }.get(ev, "")

    # -- UI refresh ------------------------------------------------------------
    def status_line(self, now: float) -> Tuple[str, str]:
        """(text, kind): kind is info (grey), ok, paused (amber), warn (amber, icon) or error (red, icon)."""
        if now < self.status_until and self.status_flash:
            return self.status_flash, self.status_flash_kind
        if self.status_text:
            return self.status_text, "error" if self.status_text.startswith("Error:") else "warn"
        tr = self.tracker
        if tr.state == ec.RUNNING:
            stale = self.meso_synced_at is None or now - self.meso_synced_at > 60
            return "Tracking" + (". Open inventory to sync mesos." if stale else ""), "info"
        if tr.state in (ec.PAUSED, ec.TIMEOUT):
            return "Paused—" + ("gain EXP or press play" if tr.auto_start else "press play") + " to resume", "paused"
        if tr.level is None:
            return "Detecting your level…", "info"
        return ("Ready—gain EXP or press play to start" if tr.auto_start else "Ready—press play to start"), "info"

    @staticmethod
    def _arrow(window_rate: Optional[float], session_rate: Optional[float]) -> Optional[str]:
        """Up / down against the session average (nothing while they are the same or unknown)."""
        if window_rate is None or session_rate is None or abs(window_rate - session_rate) <= 0.005 * abs(session_rate):
            return None
        return "up" if window_rate > session_rate else "down"

    def refresh(self, now: float) -> None:
        """Update everything shown. If that changes the panel's height (another view, a message that wraps, a longer
        footer) the new contents, the new size and the new position are applied together, with painting held back
        until the end, so there is no frame with the old size around the new content."""
        def heights():
            return self.status_lbl.height(), self.chip_exp.height(), self.chip_meso.height()

        self.setUpdatesEnabled(False)
        try:
            self._begin_resize()
            before = heights()
            self._refresh_contents(now)
            changed = heights() != before
            if changed:
                self._resize_keep_anchor()
            else:
                self._anchor = None
        finally:
            self.setUpdatesEnabled(True)
        if changed and self.isVisible():
            self.repaint()                      # paint at once, before the event loop can show a half-way state

    def _refresh_contents(self, now: float) -> None:
        tr = self.tracker
        playing = tr.state == ec.RUNNING
        self.btn_play.set_kind("pause" if playing else "play",
                               "Pause" if playing else ("Resume" if tr.has_session() else "Start tracking"))
        self.btn_mode.set_auto(tr.auto_start)
        self.timer_lbl.setText(ec.fmt_clock(tr.active(now)))
        col = C_OK.name() if playing else C_DIM.name()
        if col != self._timer_col:
            self._timer_col = col
            self.timer_lbl.setStyleSheet(f"color: {col}; background: transparent;")
        msg = self.status_line(now)
        if msg != (self.status_lbl.text(), self.status_lbl.kind):
            self.status_lbl.set_message(*msg)       # a long message wraps, so the panel's height can change
        self._refresh_exp(now)
        self._refresh_meso(now)

    def _refresh_exp(self, now: float) -> None:
        tr, view = self.tracker, self.views["exp"]
        r = tr.rate(now)
        value = "---" if r is None else ec.fmt_int(r[0] * 3600)
        rows: List[Row] = []
        if view == 1:
            if tr.level is None:
                eta = "Detecting level…"
            elif tr.level >= ec.MAX_LEVEL:
                eta = "Max level"
            else:
                eta = ec.fmt_eta(tr.eta_seconds(now))
            rows = [Row("EXP (%)", "--%" if r is None else f"{r[1] * 3600:.2f}%", HR), Row("Next level up", eta)]
        elif view in (2, 3):
            for label, win in (("Last 15m", 900), ("Last 5m", 300), ("Last 1m", 60)):
                w = tr.rate(now, win)
                if w is None:
                    rows.append(Row(label, "---"))
                elif view == 2:
                    rows.append(Row(label, ec.fmt_int(w[0] * 3600), "", self._arrow(w[0], r and r[0])))
                else:
                    rows.append(Row(label, f"{w[1] * 3600:.2f}%", "", self._arrow(w[1], r and r[1])))
        self.chip_exp.set_data("", value, HR, rows, tr.rate_series(now))

    def detection_line(self) -> Tuple[str, str]:
        """(text, link) for the footer of the second mesos view: what the quick slots show right now."""
        scan = self.qscan
        if scan is None or not scan.visible:
            return "Quick slots not visible", ""
        names: List[str] = []
        for s in scan.known:
            label = s.name + ("" if s.status == "ok" else " (count?)")
            if label not in names:
                names.append(label)
        if not names:
            return "No known consumables found in quick slots.", "[Add custom]"
        link = "[Add custom]" if scan.unknown else ("[Teach counts]" if scan.unreadable else "")
        return "Detected " + ", ".join(names), link

    def _refresh_meso(self, now: float) -> None:
        tr, view = self.tracker, self.views["meso"]
        mr = tr.meso_rate()
        synced = "" if self.meso_synced_at is None else _ago(now - self.meso_synced_at)
        rows: List[Row] = []
        footer = link = ""
        if view == 1:
            gain = tr.meso_gain()
            tracked = tr.has_session() and self.stock.tracked()
            cost = self.stock.cost() if tracked else None
            profit = None if gain is None else gain - (cost or 0)
            rows = [Row("Mesos gained", "---" if gain is None else f"{gain:,}"),
                    Row("Potion cost", "---" if cost is None else f"{cost:,}", note="(quick slots only)"),
                    Row("Estimated profit", "---" if profit is None else f"{profit:,}",
                        color=None if profit is None else (QColor(74, 222, 128) if profit >= 0 else QColor(248, 113, 113)))]
            footer, link = self.detection_line()
        elif view == 2:
            for label, win in (("Last 15m", 900), ("Last 5m", 300), ("Last 1m", 60)):
                w = tr.meso_rate(win)
                rows.append(Row(label, "---" if w is None else ec.fmt_int(w), "", self._arrow(w, mr)))
        self.chip_meso.set_data(synced, "---" if mr is None else ec.fmt_int(mr), HR, rows, tr.meso_series(),
                                footer, link)

    # -- actions ---------------------------------------------------------------
    def on_toggle(self) -> None:
        self.tracker.toggle(self.clock())
        if self.tracker.state == ec.IDLE and self.tracker.want_start:
            self.flash("Will start as soon as your level is detected.", 5)
        self.refresh(self.clock())

    def on_reset(self) -> None:
        self.tracker.reset()
        self.stock.reset()
        self._stock_session = 0
        self.meso_synced_at = None
        self.status_text = ""
        self.status_flash = ""
        self.refresh(self.clock())

    def apply_settings(self) -> None:
        c = self.cfg
        self.tracker.configure(c["timeout_seconds"], c["auto_start"], c["level_override"])
        self.set_opacity(float(c["opacity"]))
        self.timer.start(int(float(c["interval"]) * 1000))
        self.btn_mode.set_auto(c["auto_start"])
        self._save_cfg()
        self.status_text = ""
        self.refresh(self.clock())

    def open_quickslots(self) -> None:
        d = QuickSlotDialog(self, self)
        was_on = self.top_timer.isActive()
        self.top_timer.stop()                         # re-stacking the overlay now would fight the dialog
        try:
            d.exec()
        finally:
            if was_on:
                self.top_timer.start(700)
        self.items.save()
        self.refresh(self.clock())

    def open_calibrate(self) -> None:
        d = CalibrateDialog(self, self)
        was_on = self.top_timer.isActive()
        self.top_timer.stop()
        try:
            d.exec()
        finally:
            if was_on:
                self.top_timer.start(700)
        self._save_cfg()

    def closeEvent(self, e):
        self.timer.stop()
        self.top_timer.stop()
        if self.in_settings:
            self.settings.apply(self.cfg)
        self.cfg["overlay"].update(x=self.x(), y=self.y())
        self._save_cfg()
        e.accept()
        QApplication.quit()
