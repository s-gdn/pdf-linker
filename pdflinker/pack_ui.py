"""Background semantic suggestions for the desktop app."""
import copy
import threading
from PySide6.QtCore import QThread, Signal, Qt
from .model_packs import PackMatcher
from .text_normalization import normalize_phrase
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QHeaderView,
                              QLabel, QTableWidget, QTableWidgetItem, QVBoxLayout)


class AbbreviationDialog(QDialog):
    """Confirm document-backed meanings before semantic matching starts."""
    def __init__(self,candidates,parent=None):
        super().__init__(parent)
        self.setWindowTitle('Review abbreviations')
        self.resize(620,360)
        layout=QVBoxLayout(self)
        note=QLabel('Check the detected abbreviations before suggesting links. Choose a meaning or type your own. '
                    'Leave a meaning blank to keep the abbreviation unchanged. Changes apply to this suggestion run.')
        note.setWordWrap(True);layout.addWidget(note)
        self.table=QTableWidget(len(candidates),2)
        self.table.setHorizontalHeaderLabels(['Abbreviation','Meaning'])
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(0,QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1,QHeaderView.ResizeMode.Stretch)
        self.editors={}
        for row,(key,values) in enumerate(candidates.items()):
            item=QTableWidgetItem(key.upper())
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row,0,item)
            editor=QComboBox();editor.setEditable(True);editor.addItem('');editor.addItems(values)
            editor.setCurrentIndex(1 if len(values)==1 else 0)
            editor.lineEdit().setPlaceholderText('Unresolved — enter or choose a meaning')
            self.table.setCellWidget(row,1,editor);self.editors[key]=editor
        layout.addWidget(self.table)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText('Continue')
        buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def expansions(self):
        return {key:normalize_phrase(editor.currentText()) for key,editor in self.editors.items()
                if normalize_phrase(editor.currentText())}


class MatchWorker(QThread):
    result=Signal(object,str)
    def __init__(self,manager,pack_id,fields,columns,existing,rows=None,minimum_score=.4,abbreviations=None,rrf=None):
        super().__init__()
        self.manager,self.pack_id=manager,pack_id
        self.fields=copy.deepcopy(fields);self.columns=list(columns);self.existing=dict(existing)
        self.rows=copy.deepcopy(rows) if rows is not None else None
        self.minimum_score=minimum_score
        self.abbreviations=copy.deepcopy(abbreviations)
        self.rrf=copy.deepcopy(rrf)
        self.cancelled=threading.Event()
    def run(self):
        try:
            from .field_matching import context_links
            prepared=context_links(self.fields,self.columns,self.existing,self.rows)
            if all(f.key in prepared or f.constant_value is not None or f.match_basis=='ambiguous_id' for f in self.fields):
                self.result.emit(prepared,'')
                return
            matcher=PackMatcher(self.manager,self.pack_id)
            links=matcher.links(self.fields,self.columns,prepared,self.cancelled,minimum_score=self.minimum_score,
                                rows=self.rows,abbreviations=self.abbreviations,rrf=self.rrf)
            self.result.emit(links,'')
        except Exception as error:self.result.emit({},str(error))
