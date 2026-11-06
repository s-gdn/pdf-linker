"""Layouts for controls that remain usable in narrow desktop windows."""
from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtWidgets import QLayout


class FlowLayout(QLayout):
    """Wrap whole controls onto extra rows, with consistent gaps in both axes."""
    def __init__(self, parent=None, horizontal_gap=8, vertical_gap=6):
        super().__init__(parent)
        self.items = []
        self.horizontal_gap = horizontal_gap
        self.vertical_gap = vertical_gap
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self.items.append(item)
        self.invalidate()

    def count(self):
        return len(self.items)

    def itemAt(self, index):
        return self.items[index] if 0 <= index < len(self.items) else None

    def takeAt(self, index):
        if 0 <= index < len(self.items):
            item = self.items.pop(index)
            self.invalidate()
            return item
        return None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self.arrange(QRect(0, 0, width, 0), measure=True)

    def minimumSize(self):
        size = QSize()
        for item in self.items:
            size = size.expandedTo(item.minimumSize())
        left, top, right, bottom = self.getContentsMargins()
        return size + QSize(left + right, top + bottom)

    def sizeHint(self):
        return self.minimumSize()

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self.arrange(rect)

    def arrange(self, rect, measure=False):
        left, top, right, bottom = self.getContentsMargins()
        area = rect.adjusted(left, top, -right, -bottom)
        x, y, row_height = area.x(), area.y(), 0
        for item in self.items:
            if item.isEmpty():
                continue
            size = item.sizeHint().expandedTo(item.minimumSize()).boundedTo(item.maximumSize())
            if x > area.x() and x + size.width() > area.x() + area.width():
                x = area.x()
                y += row_height + self.vertical_gap
                row_height = 0
            if not measure:
                item.setGeometry(QRect(x, y, size.width(), size.height()))
            x += size.width() + self.horizontal_gap
            row_height = max(row_height, size.height())
        return y + row_height - rect.y() + bottom
